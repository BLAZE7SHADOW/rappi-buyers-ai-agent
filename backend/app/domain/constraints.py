"""Hard-constraint checks.

Every check returns a :class:`ConstraintCheck` carrying a human-readable
``binding_reason``. That string is what the UI shows beside an infeasible option
and what the agent quotes when it explains why a recommendation was rejected --
so a constraint failure is always explainable, never a bare boolean.

A constraint that fails here cannot be waived by a buyer clicking "approve".
Budget and capacity are physical/financial facts; changing them requires
recording new budget or new space, then revalidating.
"""

from __future__ import annotations

from datetime import date

from app.domain.types import (
    Budget,
    CapacityDay,
    Candidate,
    ConstraintCheck,
    Minor,
    PolicyConfig,
    Projection,
    SupplierQuote,
)


def money(minor: Minor) -> str:
    return f"${minor / 100:,.2f}"


def check_budget(candidate: Candidate, budget: Budget | None) -> ConstraintCheck:
    cost = candidate.total_cost_minor
    if budget is None:
        return ConstraintCheck(
            "budget", False, "No budget record found; treating missing data as blocking."
        )
    if cost <= budget.available_minor:
        return ConstraintCheck(
            "budget", True,
            f"{money(cost)} within {money(budget.available_minor)} available.",
            limit=budget.available_minor, required=cost,
        )
    return ConstraintCheck(
        "budget", False,
        f"Order total {money(cost)} exceeds available budget {money(budget.available_minor)} "
        f"by {money(cost - budget.available_minor)}.",
        limit=budget.available_minor, required=cost,
    )


def check_capacity(
    candidate: Candidate,
    projection_after: Projection,
    capacity: list[CapacityDay],
    unit_volume_m3: float,
) -> ConstraintCheck:
    """Capacity is judged at the post-receipt peak.

    Checking only end-of-day stock hides the case where a delivery lands, briefly
    overflows the node, and is drawn down by that day's demand. The goods still
    have to physically fit when they arrive.
    """
    if unit_volume_m3 <= 0 or not capacity:
        return ConstraintCheck("capacity", True, "No volume or capacity data modelled.")

    limit = min(c.capacity_m3 for c in capacity)
    peak = projection_after.peak_occupancy_m3
    if peak <= limit:
        return ConstraintCheck(
            "capacity", True,
            f"Peak post-receipt occupancy {peak:.2f} m³ within {limit:.2f} m³.",
            limit=limit, required=peak,
        )
    overflow_units = int((peak - limit) / unit_volume_m3) if unit_volume_m3 else 0
    return ConstraintCheck(
        "capacity", False,
        f"Peak post-receipt occupancy {peak:.2f} m³ exceeds node capacity {limit:.2f} m³ "
        f"(about {overflow_units} units too many).",
        limit=limit, required=peak,
    )


def check_moq_pack(candidate: Candidate, quote: SupplierQuote | None) -> ConstraintCheck:
    if quote is None or candidate.qty <= 0:
        return ConstraintCheck("moq_pack", True, "Not an ordering action.")
    if candidate.qty < quote.moq:
        return ConstraintCheck(
            "moq_pack", False,
            f"{candidate.qty} units is below supplier {quote.supplier_id} minimum "
            f"order quantity of {quote.moq}.",
            limit=quote.moq, required=candidate.qty,
        )
    if quote.pack_size > 1 and candidate.qty % quote.pack_size != 0:
        return ConstraintCheck(
            "moq_pack", False,
            f"{candidate.qty} units is not a multiple of pack size {quote.pack_size}.",
            limit=quote.pack_size, required=candidate.qty,
        )
    return ConstraintCheck(
        "moq_pack", True,
        f"{candidate.qty} units satisfies MOQ {quote.moq} and pack size {quote.pack_size}.",
    )


def check_availability(candidate: Candidate, quote: SupplierQuote | None) -> ConstraintCheck:
    if quote is None or candidate.qty <= 0:
        return ConstraintCheck("availability", True, "Not an ordering action.")
    if candidate.qty <= quote.available_units:
        return ConstraintCheck(
            "availability", True,
            f"Supplier can supply {candidate.qty} of {quote.available_units} available.",
            limit=quote.available_units, required=candidate.qty,
        )
    return ConstraintCheck(
        "availability", False,
        f"Supplier {quote.supplier_id} has only {quote.available_units} units available; "
        f"{candidate.qty} requested.",
        limit=quote.available_units, required=candidate.qty,
    )


def check_quote_validity(quote: SupplierQuote | None, today: date) -> ConstraintCheck:
    if quote is None:
        return ConstraintCheck("quote_validity", True, "No quote required.")
    if quote.is_expired(today):
        return ConstraintCheck(
            "quote_validity", False,
            f"Quote from {quote.supplier_id} expired on "
            f"{quote.quote_expires_at.isoformat()}; a refreshed quote is required.",
        )
    return ConstraintCheck(
        "quote_validity", True,
        f"Quote valid through {quote.quote_expires_at.isoformat()}.",
    )


def check_supplier_eligibility(quote: SupplierQuote | None) -> ConstraintCheck:
    if quote is None:
        return ConstraintCheck("supplier_eligibility", True, "No supplier required.")
    if not quote.eligible:
        return ConstraintCheck(
            "supplier_eligibility", False,
            f"Supplier {quote.supplier_id} is not approved for {quote.sku}. Changing "
            f"eligibility is a master-data decision outside the agent's authority.",
        )
    return ConstraintCheck(
        "supplier_eligibility", True, f"Supplier {quote.supplier_id} is approved for {quote.sku}."
    )


def check_lead_time(
    candidate: Candidate, projection_before: Projection, today: date
) -> ConstraintCheck:
    """Informational rather than blocking.

    A delivery that lands after the shortage begins is still worth placing -- it
    just does not prevent the whole gap. The check records that partial benefit
    instead of discarding the option.
    """
    if candidate.expected_receipt_date is None:
        return ConstraintCheck("lead_time", True, "No dated receipt in this action.")
    stockout = projection_before.first_stockout_date
    if stockout is None:
        return ConstraintCheck("lead_time", True, "No projected stockout to beat.")
    if candidate.expected_receipt_date <= stockout:
        return ConstraintCheck(
            "lead_time", True,
            f"Arrives {candidate.expected_receipt_date.isoformat()}, on or before the "
            f"projected stockout on {stockout.isoformat()}.",
        )
    late_days = (candidate.expected_receipt_date - stockout).days
    return ConstraintCheck(
        "lead_time", True,
        f"Arrives {candidate.expected_receipt_date.isoformat()}, {late_days} day(s) after "
        f"the projected stockout on {stockout.isoformat()}; earlier demand stays unmet.",
    )


def check_excess_stock(
    projection_after: Projection, policy: PolicyConfig
) -> ConstraintCheck:
    """Guard against solving a shortage by creating a large overstock.

    Expressed as days of cover so it scales with demand. A zero-demand product
    cannot be divided by, so it falls back to a flat unit cap.
    """
    closing = projection_after.closing_inventory
    horizon = max(1, len(projection_after.days))
    avg_daily = projection_after.total_demand_units / horizon

    if avg_daily <= 0:
        cap = policy.zero_demand_unit_cap
        if closing <= cap:
            return ConstraintCheck(
                "excess_stock", True,
                f"Zero forecast demand; closing {closing} units within the {cap}-unit cap.",
                limit=cap, required=closing,
            )
        return ConstraintCheck(
            "excess_stock", False,
            f"Zero forecast demand and closing stock of {closing} units exceeds the "
            f"{cap}-unit cap for non-moving products.",
            limit=cap, required=closing,
        )

    cap_units = int(policy.max_days_cover * avg_daily)
    days_cover = closing / avg_daily
    if closing <= cap_units:
        return ConstraintCheck(
            "excess_stock", True,
            f"Closing {closing} units is {days_cover:.1f} days of cover, within the "
            f"{policy.max_days_cover}-day policy.",
            limit=cap_units, required=closing,
        )
    return ConstraintCheck(
        "excess_stock", False,
        f"Closing {closing} units is {days_cover:.1f} days of cover, above the "
        f"{policy.max_days_cover}-day policy limit of {cap_units} units.",
        limit=cap_units, required=closing,
    )


def checks_to_dicts(checks: list[ConstraintCheck]) -> list[dict]:
    return [
        {
            "name": c.name,
            "passed": c.passed,
            "binding_reason": c.binding_reason,
            "limit": c.limit,
            "required": c.required,
        }
        for c in checks
    ]
