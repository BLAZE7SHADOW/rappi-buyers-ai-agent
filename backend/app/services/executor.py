"""Idempotent action execution.

The ordering here is deliberate and is the whole point of the module:

1. **Persist the intent first.** If anything later fails, there is a durable
   record that this action was attempted.
2. **Call the supplier in its own transaction.** The supplier is an external
   system; it cannot share ours. Modelling it that way is what makes the
   "committed remotely, response lost" case reachable instead of theoretical.
3. **Apply internal effects atomically.** The purchase order, the budget
   commitment and the capacity reservation land together or not at all, so there
   is never an order without its matching commitment.

Every action carries a stable idempotency key derived from the plan it came from.
Retrying is therefore always safe: the supplier returns the original answer rather
than creating a second order.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.db import schema as s
from app.db.engine import transaction
from app.db.repo import append_event
from app.domain.types import ActionType, Candidate, EventKind
from app.integrations import mock_supplier as supplier
from app.integrations.mock_supplier import SupplierRejected, SupplierTimeout


class ActionOutcomeUnknown(Exception):
    """The supplier's outcome could not be established.

    Never retried automatically: a blind retry is exactly how duplicate orders
    get created. Escalates to a human instead.
    """


def idempotency_key(
    case_id: str, proposal_id: str, version: int, candidate: Candidate
) -> str:
    """Derive a stable key for one intended action.

    Includes the proposal *version*, so a materially revised plan is a genuinely
    different action rather than a retry of the old one.
    """
    payload = json.dumps(
        {
            "case_id": case_id,
            "proposal_id": proposal_id,
            "version": version,
            "action_type": candidate.action_type.value,
            "supplier_id": candidate.supplier_id,
            "po_id": candidate.po_id,
            "qty": candidate.qty,
            "date": (
                candidate.new_date.isoformat() if candidate.new_date
                else candidate.expected_receipt_date.isoformat()
                if candidate.expected_receipt_date else None
            ),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _existing_action(conn, key: str):
    return conn.execute(
        select(s.actions).where(s.actions.c.idempotency_key == key)
    ).mappings().first()


def execute(
    *,
    case_id: str,
    proposal_id: str,
    version: int,
    candidate: Candidate,
    behavior: str = "confirm_full",
    node_id: str = "",
    sku: str = "",
    budget_period: str = "",
) -> dict:
    """Execute one authorised action and return its persisted result."""
    key = idempotency_key(case_id, proposal_id, version, candidate)

    # ---- Step 0: has this exact action already completed? ------------------- #
    with transaction() as conn:
        prior = _existing_action(conn, key)
        if prior and prior["state"] in ("completed", "rejected"):
            append_event(
                conn, case_id, EventKind.ACTION,
                "Duplicate submission suppressed",
                {
                    "idempotency_key": key,
                    "action_id": prior["action_id"],
                    "state": prior["state"],
                    "note": "An action with this key already completed; returning the original result.",
                },
            )
            return {
                "action_id": prior["action_id"],
                "state": prior["state"],
                "po_id": prior["po_id"],
                "response": json.loads(prior["response_json"] or "{}"),
                "duplicate_suppressed": True,
            }

        action_id = prior["action_id"] if prior else f"ACT-{uuid.uuid4().hex[:8].upper()}"
        request = {
            "action_type": candidate.action_type.value,
            "supplier_id": candidate.supplier_id,
            "po_id": candidate.po_id,
            "qty": candidate.qty,
            "unit_price_minor": candidate.unit_price_minor,
            "fee_minor": candidate.fee_minor,
            "requested_date": (
                candidate.new_date or candidate.expected_receipt_date
            ),
        }

        # ---- Step 1: persist intent BEFORE contacting the supplier ---------- #
        if not prior:
            conn.execute(s.actions.insert().values(
                action_id=action_id, case_id=case_id, proposal_id=proposal_id,
                proposal_version=version, action_type=candidate.action_type.value,
                idempotency_key=key, request_json=json.dumps(request, default=str),
                state="submitted", attempts=1,
            ))
        else:
            conn.execute(s.actions.update()
                         .where(s.actions.c.action_id == action_id)
                         .values(attempts=prior["attempts"] + 1, state="submitted"))
        append_event(conn, case_id, EventKind.ACTION, "Action submitted to supplier",
                     {"action_id": action_id, "idempotency_key": key, "request": request})

    requested_date = candidate.new_date or candidate.expected_receipt_date or date.today()

    # ---- Step 2: the supplier call, in its own transaction ------------------ #
    try:
        response = supplier.submit(
            idempotency_key=key,
            kind="expedite" if candidate.action_type is ActionType.EXPEDITE_PO else "create",
            request=request, requested_qty=candidate.qty,
            requested_date=requested_date, behavior=behavior,
        )

    except SupplierTimeout:
        # The supplier may have committed. Ask it rather than guessing.
        recovered = supplier.lookup(key)
        with transaction() as conn:
            if recovered is None:
                conn.execute(s.actions.update()
                             .where(s.actions.c.action_id == action_id)
                             .values(state="outcome_unknown"))
                append_event(conn, case_id, EventKind.ERROR, "Action outcome unknown",
                             {"action_id": action_id, "idempotency_key": key,
                              "note": "Timeout and no supplier record found. Not retried "
                                      "automatically; a blind retry could duplicate the order."})
                raise ActionOutcomeUnknown(key)

            append_event(
                conn, case_id, EventKind.ACTION, "Recovered lost response via idempotency key",
                {"action_id": action_id, "idempotency_key": key,
                 "external_ref": recovered.external_ref,
                 "note": "Transport timed out but the supplier had already committed. "
                         "Reconciled from the supplier's record instead of resubmitting."},
            )
            response = recovered

    except SupplierRejected as exc:
        with transaction() as conn:
            conn.execute(s.actions.update()
                         .where(s.actions.c.action_id == action_id)
                         .values(state="rejected",
                                 response_json=json.dumps({"error": str(exc)})))
            append_event(conn, case_id, EventKind.ACTION, "Supplier rejected the order",
                         {"action_id": action_id, "reason": str(exc)})
        return {"action_id": action_id, "state": "rejected", "po_id": None,
                "response": {"error": str(exc)}, "duplicate_suppressed": False}

    # ---- Step 3: apply internal effects atomically -------------------------- #
    with transaction() as conn:
        if candidate.action_type is ActionType.EXPEDITE_PO:
            po_id = _apply_expedite(conn, candidate, response)
        else:
            po_id = _apply_create(conn, candidate, response, node_id=node_id, sku=sku,
                                  case_id=case_id)

        _commit_budget(conn, node_id, budget_period, candidate)

        conn.execute(s.actions.update()
                     .where(s.actions.c.action_id == action_id)
                     .values(state="completed", po_id=po_id,
                             response_json=json.dumps(response.to_dict())))
        append_event(conn, case_id, EventKind.ACTION, "Supplier response recorded",
                     {"action_id": action_id, "po_id": po_id, "response": response.to_dict()})

    return {"action_id": action_id, "state": "completed", "po_id": po_id,
            "response": response.to_dict(), "duplicate_suppressed": False}


# --------------------------------------------------------------------------- #
# Internal effects
# --------------------------------------------------------------------------- #


def _apply_create(conn, candidate: Candidate, response, *, node_id, sku, case_id) -> str:
    po_id = f"PO-{uuid.uuid4().hex[:6].upper()}"
    cancelled = max(0, candidate.qty - response.confirmed_qty)
    conn.execute(s.purchase_orders.insert().values(
        po_id=po_id, sku=sku, node_id=node_id, supplier_id=candidate.supplier_id or "",
        requested_qty=candidate.qty, confirmed_qty=response.confirmed_qty,
        received_qty=0, cancelled_qty=cancelled,
        unit_price_minor=candidate.unit_price_minor, fee_minor=candidate.fee_minor,
        requested_date=candidate.expected_receipt_date, confirmed_date=response.confirmed_date,
        status=response.status, acknowledged_at=response.confirmed_date,
        created_by_case=case_id, version=1,
    ))
    return po_id


def _apply_expedite(conn, candidate: Candidate, response) -> str:
    """Move an existing receipt earlier. Quantity is never changed here.

    A partial expedite confirmation reduces the confirmed quantity and cancels the
    remainder, which is what makes the shortfall real rather than cosmetic.
    """
    row = conn.execute(
        select(s.purchase_orders).where(s.purchase_orders.c.po_id == candidate.po_id)
    ).mappings().first()
    if row is None:
        raise ActionOutcomeUnknown(f"Purchase order {candidate.po_id} no longer exists.")

    outstanding = row["confirmed_qty"] or row["requested_qty"]
    confirmed = min(response.confirmed_qty, outstanding)
    cancelled = row["cancelled_qty"] + max(0, outstanding - confirmed)

    updated = conn.execute(
        s.purchase_orders.update()
        .where(s.purchase_orders.c.po_id == candidate.po_id,
               s.purchase_orders.c.version == row["version"])
        .values(confirmed_qty=confirmed, cancelled_qty=cancelled,
                confirmed_date=response.confirmed_date, status=response.status,
                acknowledged_at=response.confirmed_date,
                fee_minor=row["fee_minor"] + candidate.fee_minor,
                version=row["version"] + 1)
    )
    if updated.rowcount != 1:
        raise ActionOutcomeUnknown(
            f"Purchase order {candidate.po_id} changed while the supplier request was in flight."
        )
    return candidate.po_id


def _commit_budget(conn, node_id: str, period: str, candidate: Candidate) -> None:
    """Move funds from available to committed, once."""
    cost = candidate.total_cost_minor
    if cost <= 0:
        return
    row = conn.execute(
        select(s.budgets).where(
            s.budgets.c.scope == node_id,
            s.budgets.c.period == period,
        )
    ).mappings().first()
    if row is None:
        # Unreachable through the normal path -- a missing budget is blocking at
        # the constraint layer, so the plan is refused before the supplier is
        # called. This covers the remaining window: the supplier has committed and
        # the spend cannot be recorded. Returning quietly would leave a real order
        # with untracked money, so it is the same class of failure as the lost
        # optimistic update below.
        raise ActionOutcomeUnknown(
            f"No budget exists for {node_id}/{period}; the committed spend of "
            f"{cost} minor units could not be recorded."
        )
    updated = conn.execute(
        s.budgets.update()
        .where(s.budgets.c.id == row["id"], s.budgets.c.version == row["version"])
        .values(committed_minor=row["committed_minor"] + cost, version=row["version"] + 1)
    )
    if updated.rowcount != 1:
        raise ActionOutcomeUnknown(
            f"Budget {node_id}/{period} changed while the supplier request was in flight."
        )
