"""Day-by-day inventory projection.

This is the only place inventory arithmetic happens. The agent never computes
these numbers; it calls ``simulate_plan`` and reads them back.

Model assumptions, stated explicitly because they change how results should be
read:

* **Daily resolution.** Intraday stockouts are outside the model.
* **Receipts land before that day's demand.** A delivery arriving on the day
  stock would otherwise run out prevents the stockout.
* **Unmet demand is lost, not backlogged.** It is recorded separately and
  physical inventory is clamped at zero rather than going negative.
* **Only confirmed supply enters the baseline.** Tentative or unacknowledged
  receipts are surfaced as uncertainty instead of being silently counted.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.types import (
    CapacityDay,
    DemandDay,
    ProjectionDay,
    Projection,
    Receipt,
)


def receipts_by_day(receipts: list[Receipt], confirmed_only: bool = True) -> dict[date, int]:
    """Collapse receipts into a per-day total.

    ``confirmed_only`` is what keeps unconfirmed supply out of the baseline: an
    overdue PO with no acknowledgement must not quietly prop up the projection.
    """
    out: dict[date, int] = {}
    for r in receipts:
        if confirmed_only and not r.confirmed:
            continue
        out[r.day] = out.get(r.day, 0) + r.qty
    return out


def build_projection(
    *,
    opening_units: int,
    demand: list[DemandDay],
    receipts: list[Receipt],
    start: date,
    horizon_days: int,
    safety_stock_units: int = 0,
    unit_volume_m3: float = 0.0,
    capacity: list[CapacityDay] | None = None,
    confirmed_only: bool = True,
    demand_override: dict[date, int] | None = None,
) -> Projection:
    """Run the projection and return per-day rows plus summary metrics.

    ``demand_override`` lets a caller supply an adjusted demand series (for
    example a promotion-bounded uplift) while keeping the same arithmetic.
    """
    receipt_map = receipts_by_day(receipts, confirmed_only=confirmed_only)
    demand_map = {d.day: d.forecast_units for d in demand}
    if demand_override:
        demand_map.update(demand_override)

    capacity_map = {c.day: c for c in (capacity or [])}

    rows: list[ProjectionDay] = []
    opening = max(0, opening_units)
    total_demand = 0
    total_unmet = 0
    first_stockout: date | None = None
    days_below_safety = 0
    peak_occupancy = 0.0

    for offset in range(horizon_days):
        day = start + timedelta(days=offset)
        receipts_today = receipt_map.get(day, 0)
        demand_today = max(0, demand_map.get(day, 0))

        # Receipts are available to serve the same day's demand.
        available = opening + receipts_today
        served = min(available, demand_today)
        unmet = max(0, demand_today - available)
        closing = max(0, available - demand_today)

        # Capacity is checked at the post-receipt peak, not at end of day. Stock
        # that arrives and then ships out the same day still has to physically fit.
        if unit_volume_m3 > 0:
            cap_day = capacity_map.get(day)
            other_occupied = cap_day.occupied_m3 if cap_day else 0.0
            peak_occupancy = max(peak_occupancy, available * unit_volume_m3 + other_occupied)

        below_safety = closing < safety_stock_units
        if below_safety:
            days_below_safety += 1
        if unmet > 0 and first_stockout is None:
            first_stockout = day

        rows.append(
            ProjectionDay(
                day=day,
                opening=opening,
                receipts=receipts_today,
                available=available,
                demand=demand_today,
                served=served,
                unmet=unmet,
                closing=closing,
                below_safety=below_safety,
            )
        )

        total_demand += demand_today
        total_unmet += unmet
        opening = closing

    return Projection(
        days=rows,
        total_demand_units=total_demand,
        total_unmet_units=total_unmet,
        first_stockout_date=first_stockout,
        days_below_safety=days_below_safety,
        closing_inventory=opening,
        peak_occupancy_m3=round(peak_occupancy, 4),
    )


def orders_to_receipts(orders, confirmed_only: bool = True) -> list[Receipt]:
    """Convert open purchase orders into projected receipts.

    Only the outstanding quantity counts -- units already received or cancelled
    are not incoming supply. An order without a confirmed date is marked
    unconfirmed so the caller can decide whether to include it.
    """
    out: list[Receipt] = []
    for o in orders:
        qty = o.outstanding_qty
        if qty <= 0:
            continue
        day = o.confirmed_date or o.requested_date
        is_confirmed = o.confirmed_date is not None and o.confirmed_qty > 0
        if confirmed_only and not is_confirmed:
            continue
        out.append(Receipt(day=day, qty=qty, po_id=o.po_id, confirmed=is_confirmed))
    return out


def summarize(projection: Projection) -> dict:
    """Compact, JSON-safe view for tool results and UI panels."""
    return {
        "total_demand_units": projection.total_demand_units,
        "total_unmet_units": projection.total_unmet_units,
        "first_stockout_date": (
            projection.first_stockout_date.isoformat()
            if projection.first_stockout_date
            else None
        ),
        "days_below_safety": projection.days_below_safety,
        "closing_inventory": projection.closing_inventory,
        "peak_occupancy_m3": projection.peak_occupancy_m3,
        "has_shortage": projection.has_shortage,
    }


def projection_rows(projection: Projection) -> list[dict]:
    return [
        {
            "day": r.day.isoformat(),
            "opening": r.opening,
            "receipts": r.receipts,
            "demand": r.demand,
            "served": r.served,
            "unmet": r.unmet,
            "closing": r.closing,
            "below_safety": r.below_safety,
        }
        for r in projection.days
    ]
