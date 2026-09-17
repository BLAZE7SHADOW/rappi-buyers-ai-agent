"""Independent outcome validation.

This module never reads the agent's claims. It reads the *authorised plan* and
the *persisted state*, compares them, and decides what actually happened. That
independence is the point: if the agent reports success and the supplier confirmed
60% of the order, the verdict is PARTIAL regardless of what the model said.

Three layers, in order of increasing strictness:

1. **Proposal validity** -- was there sufficient evidence and did the hard
   constraints pass? Checked before execution.
2. **Execution validity** -- does the persisted order match what was authorised:
   supplier, product, node, quantity, date, cost?
3. **Business outcome validity** -- does the confirmed supply actually close the
   coverage gap the plan existed to close?

A pending acknowledgement is reported as awaiting confirmation. It is never
reported as coverage: confirmation and physical receipt are different milestones.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.db import schema as s
from app.domain.candidates import baseline_projection
from app.domain.types import Verdict, VerdictKind
from app.services.context import build_context

# Cost may drift slightly (rounding, fees) without invalidating the authorisation.
COST_TOLERANCE_MINOR = 100


def _check(layer: str, name: str, passed: bool, detail: str) -> dict:
    return {"layer": layer, "name": name, "passed": passed, "detail": detail}


def validate_action(conn: Connection, case: dict, action_row: dict) -> Verdict:
    """Compare an executed action against its authorisation and its purpose."""
    request = json.loads(action_row["request_json"] or "{}")
    response = json.loads(action_row["response_json"] or "{}")

    expected = {
        "action_type": request.get("action_type"),
        "supplier_id": request.get("supplier_id"),
        "qty": request.get("qty", 0),
        "receipt_date": request.get("requested_date"),
        # An expedite buys speed, not goods: its authorised cost is the fee alone.
        "cost_minor": (
            request.get("fee_minor", 0)
            if request.get("action_type") == "expedite_po"
            else request.get("qty", 0) * request.get("unit_price_minor", 0)
            + request.get("fee_minor", 0)
        ),
    }

    # ---- Layer 2: execution validity -- read back what was actually persisted #
    po_row = None
    if action_row["po_id"]:
        po_row = conn.execute(
            select(s.purchase_orders).where(s.purchase_orders.c.po_id == action_row["po_id"])
        ).mappings().first()

    checks: list[dict] = []

    if action_row["state"] == "rejected":
        actual = {"status": "rejected", "qty": 0, "note": response.get("error", "")}
        checks.append(_check("execution", "supplier_accepted_order", False,
                             "Supplier rejected the order outright."))
        return _finish(conn, case, expected, actual, checks, VerdictKind.FAIL,
                       "replan_required")

    if action_row["state"] == "outcome_unknown":
        actual = {"status": "unknown"}
        checks.append(_check("execution", "outcome_established", False,
                             "Supplier outcome could not be established; not retried "
                             "automatically to avoid duplicating a real order."))
        return _finish(conn, case, expected, actual, checks, VerdictKind.UNKNOWN, "escalate")

    if po_row is None:
        actual = {"status": "no_order_found"}
        checks.append(_check("execution", "order_persisted", False,
                             "No purchase order found for this action."))
        return _finish(conn, case, expected, actual, checks, VerdictKind.FAIL, "escalate")

    actual = {
        "po_id": po_row["po_id"],
        "supplier_id": po_row["supplier_id"],
        "qty": po_row["confirmed_qty"],
        "cancelled_qty": po_row["cancelled_qty"],
        "receipt_date": po_row["confirmed_date"].isoformat() if po_row["confirmed_date"] else None,
        "status": po_row["status"],
        # Taken from the supplier's own response so this is genuinely a comparison
        # of authorised versus charged, not a recomputation of our own number.
        "cost_minor": response.get("charged_minor", 0),
        "supplier_note": response.get("note", ""),
    }

    checks.append(_check(
        "execution", "supplier_and_sku_match",
        po_row["supplier_id"] == expected["supplier_id"] and po_row["sku"] == case["sku"],
        f"Order is with {po_row['supplier_id']} for {po_row['sku']}.",
    ))

    qty_ok = po_row["confirmed_qty"] >= expected["qty"]
    checks.append(_check(
        "execution", "qty_matches_authorized", qty_ok,
        f"Authorised {expected['qty']} units; supplier confirmed {po_row['confirmed_qty']}."
        + ("" if qty_ok else f" Shortfall of {expected['qty'] - po_row['confirmed_qty']} units."),
    ))

    date_ok = True
    if expected["receipt_date"] and po_row["confirmed_date"]:
        date_ok = po_row["confirmed_date"] <= date.fromisoformat(str(expected["receipt_date"])[:10])
    checks.append(_check(
        "execution", "date_matches_authorized", date_ok,
        f"Authorised arrival {expected['receipt_date']}; confirmed {actual['receipt_date']}."
        + ("" if date_ok else " Arrival is later than authorised."),
    ))

    cost_ok = actual["cost_minor"] <= expected["cost_minor"] + COST_TOLERANCE_MINOR
    checks.append(_check(
        "execution", "cost_within_authorized_tolerance", cost_ok,
        f"Authorised ${expected['cost_minor'] / 100:,.2f}; actual ${actual['cost_minor'] / 100:,.2f}.",
    ))

    # An order that is confirmed on paper has not arrived. Say so explicitly.
    if po_row["status"] in ("submitted", "draft"):
        checks.append(_check("execution", "supplier_acknowledged", False,
                             "Order is submitted but not yet acknowledged by the supplier."))
        return _finish(conn, case, expected, actual, checks, VerdictKind.UNKNOWN,
                       "awaiting_confirmation")

    # ---- Layer 3: business outcome -- did this actually close the gap? ------- #
    ctx = build_context(conn, case)
    after = baseline_projection(ctx)
    gap_closed = after.total_unmet_units == 0

    checks.append(_check(
        "business", "coverage_gap_closed", gap_closed,
        "Projected demand is fully covered." if gap_closed else
        f"{after.total_unmet_units} units of demand remain unserved from "
        f"{after.first_stockout_date.isoformat() if after.first_stockout_date else 'n/a'}.",
    ))

    residual = {
        "unmet_units": after.total_unmet_units,
        "first_stockout_date": (
            after.first_stockout_date.isoformat() if after.first_stockout_date else None
        ),
        "unmet_days": [d.day.isoformat() for d in after.days if d.unmet > 0],
        "closing_inventory": after.closing_inventory,
    }

    execution_ok = all(c["passed"] for c in checks if c["layer"] == "execution")
    if execution_ok and gap_closed:
        kind, follow_up = VerdictKind.PASS, "resolved"
    elif not gap_closed or not qty_ok or not date_ok:
        # Something is materially different from the plan. The case is not done.
        kind, follow_up = VerdictKind.PARTIAL, "reopened_case"
    else:
        kind, follow_up = VerdictKind.FAIL, "escalate"

    return _finish(conn, case, expected, actual, checks, kind, follow_up, residual)


def _finish(conn, case, expected, actual, checks, kind, follow_up, residual=None) -> Verdict:
    deltas = {}
    if "qty" in expected and "qty" in actual:
        deltas["qty"] = actual.get("qty", 0) - expected.get("qty", 0)
    if expected.get("cost_minor") is not None and actual.get("cost_minor") is not None:
        deltas["cost_minor"] = actual["cost_minor"] - expected["cost_minor"]
    if expected.get("receipt_date") and actual.get("receipt_date"):
        try:
            d1 = date.fromisoformat(str(expected["receipt_date"])[:10])
            d2 = date.fromisoformat(str(actual["receipt_date"])[:10])
            deltas["receipt_days_late"] = (d2 - d1).days
        except ValueError:
            pass

    return Verdict(
        verdict=kind,
        expected=expected,
        actual=actual,
        deltas=deltas,
        checks=checks,
        residual_exposure=residual or {},
        follow_up=follow_up,
    )


def next_case_state(verdict: Verdict, replan_count: int, max_replans: int) -> str:
    """Translate a verdict into the case's next state.

    A PARTIAL or FAIL result reopens the case so the agent replans against the new
    reality -- until the replan budget runs out, at which point it escalates rather
    than looping.
    """
    if verdict.verdict is VerdictKind.PASS:
        return "resolved"
    if verdict.follow_up == "awaiting_confirmation":
        return "awaiting_confirmation"
    if verdict.verdict is VerdictKind.UNKNOWN or verdict.follow_up == "escalate":
        return "escalated"
    if replan_count >= max_replans:
        return "escalated"
    return "reopened"
