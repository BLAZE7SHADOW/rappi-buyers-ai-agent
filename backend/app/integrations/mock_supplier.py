"""Mock supplier API.

Modelled as a genuinely separate system with its own state, because the
interesting failures in purchasing integrations all live at that boundary:

* the supplier accepts less than was ordered;
* it accepts, but promises a later date;
* it rejects outright;
* it succeeds and the *response* is lost, leaving our side unsure whether
  anything happened.

That last one is the reason ``supplier_ledger`` is a separate table keyed by
idempotency key. After an ambiguous timeout the caller can ask the supplier what
it actually recorded instead of guessing -- and a blind retry cannot create a
second order.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from app.db import schema as s
from app.db.engine import connection, transaction


class SupplierTimeout(Exception):
    """Transport failed after the supplier may already have committed.

    Deliberately distinct from a rejection: the outcome is *unknown*, and the only
    safe response is to look the action up by its idempotency key.
    """

    def __init__(self, idempotency_key: str):
        super().__init__(f"Timeout; outcome unknown for idempotency key {idempotency_key}")
        self.idempotency_key = idempotency_key


class SupplierRejected(Exception):
    """A definite, final refusal. Safe to release reservations and replan."""


BEHAVIORS = (
    "confirm_full",
    "confirm_partial",
    "confirm_late",
    "reject",
    "timeout_after_success",
)


@dataclass
class SupplierResponse:
    external_ref: str
    confirmed_qty: int
    confirmed_date: date
    status: str
    # What the supplier will actually charge for THIS action. For a new order that
    # is goods plus fees; for an expedite it is the fee alone, because the goods
    # were already committed when the original order was placed. Reporting it here
    # lets the validator compare authorised cost against charged cost directly,
    # instead of re-deriving it and double-counting the original order value.
    charged_minor: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "external_ref": self.external_ref,
            "confirmed_qty": self.confirmed_qty,
            "confirmed_date": self.confirmed_date.isoformat(),
            "status": self.status,
            "charged_minor": self.charged_minor,
            "note": self.note,
        }


def lookup(idempotency_key: str) -> SupplierResponse | None:
    """Ask the supplier what it recorded for this key.

    This is what turns an ambiguous timeout into a knowable outcome. It opens its
    own connection deliberately: the supplier is a separate system, and a caller
    whose transaction just rolled back must still be able to ask it what happened.
    """
    with connection() as conn:
        row = conn.execute(
            select(s.supplier_ledger).where(
                s.supplier_ledger.c.idempotency_key == idempotency_key
            )
        ).mappings().first()
    if row is None:
        return None
    payload = json.loads(row["response_json"])
    return SupplierResponse(
        external_ref=payload["external_ref"],
        confirmed_qty=payload["confirmed_qty"],
        confirmed_date=date.fromisoformat(payload["confirmed_date"]),
        status=payload["status"],
        charged_minor=payload.get("charged_minor", 0),
        note=payload.get("note", ""),
    )


def _price(kind: str, qty: int, unit_price_minor: int, fee_minor: int) -> int:
    """What this action costs. An expedite buys no goods, only speed."""
    if kind == "expedite":
        return fee_minor
    return qty * unit_price_minor + fee_minor


def _decide(
    behavior: str, requested_qty: int, requested_date: date,
    *, kind: str, unit_price_minor: int, fee_minor: int,
) -> SupplierResponse:
    """Translate a configured behaviour into the supplier's answer."""
    ref = f"SUP-EXT-{uuid.uuid4().hex[:8].upper()}"

    if behavior == "reject":
        raise SupplierRejected("Supplier declined the order.")

    if behavior == "confirm_partial":
        # Confirms roughly 60% and cancels the rest outright. The residual is
        # *cancelled*, not backordered, so the shortfall is real and permanent.
        confirmed = max(1, int(requested_qty * 0.6))
        return SupplierResponse(
            ref, confirmed, requested_date, "partially_confirmed",
            charged_minor=_price(kind, confirmed, unit_price_minor, fee_minor),
            note=(
                f"Only {confirmed} of {requested_qty} units available. "
                f"Remaining {requested_qty - confirmed} units cancelled, not backordered."
            ),
        )

    if behavior == "confirm_late":
        return SupplierResponse(
            ref, requested_qty, requested_date + timedelta(days=5), "confirmed",
            charged_minor=_price(kind, requested_qty, unit_price_minor, fee_minor),
            note="Confirmed in full but 5 days later than requested.",
        )

    return SupplierResponse(
        ref, requested_qty, requested_date, "confirmed",
        charged_minor=_price(kind, requested_qty, unit_price_minor, fee_minor),
        note="Confirmed in full as requested.",
    )


def _record(key: str, kind: str, request: dict, resp: SupplierResponse) -> None:
    """Commit the supplier's own record, in the supplier's own transaction.

    This must be durable before any timeout is raised: the scenario being modelled
    is precisely that the supplier committed and we never heard about it.
    """
    with transaction() as conn:
        conn.execute(
            s.supplier_ledger.insert().values(
                idempotency_key=key,
                external_ref=resp.external_ref,
                kind=kind,
                request_json=json.dumps(request, default=str),
                response_json=json.dumps(resp.to_dict()),
            )
        )


def submit(
    *,
    idempotency_key: str,
    kind: str,
    request: dict,
    requested_qty: int,
    requested_date: date,
    behavior: str = "confirm_full",
) -> SupplierResponse:
    """Submit an order or expedite request.

    Replaying the same idempotency key returns the original answer instead of
    creating a second commitment -- the supplier, not our retry logic, is the
    authority on whether this action already happened.
    """
    existing = lookup(idempotency_key)
    if existing is not None:
        return existing

    response = _decide(
        behavior, requested_qty, requested_date, kind=kind,
        unit_price_minor=int(request.get("unit_price_minor") or 0),
        fee_minor=int(request.get("fee_minor") or 0),
    )
    _record(idempotency_key, kind, request, response)

    if behavior == "timeout_after_success":
        # The supplier has committed and the ledger row is written; only the
        # response is lost. Any caller that retries blindly here would duplicate
        # a real order.
        raise SupplierTimeout(idempotency_key)

    return response
