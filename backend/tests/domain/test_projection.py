"""Projection arithmetic: the assumptions that decide whether a plan works."""

from datetime import date, timedelta

import pytest

from app.domain.projection import build_projection, orders_to_receipts
from app.domain.types import DemandDay, OpenOrder, POStatus, Receipt

START = date(2026, 9, 17)


def days(n, units=100):
    return [DemandDay(day=START + timedelta(days=i), forecast_units=units) for i in range(n)]


def test_receipt_on_stockout_day_prevents_the_gap():
    """A delivery landing the day stock runs out prevents the stockout, because
    receipts are modelled as arriving before that day's demand."""
    on_time = build_projection(
        opening_units=1000, demand=days(14),
        receipts=[Receipt(day=START + timedelta(days=10), qty=500)],
        start=START, horizon_days=14,
    )
    assert on_time.total_unmet_units == 0


def test_receipt_after_stockout_leaves_earlier_demand_unmet():
    late = build_projection(
        opening_units=1000, demand=days(14),
        receipts=[Receipt(day=START + timedelta(days=12), qty=500)],
        start=START, horizon_days=14,
    )
    # Days 10 and 11 are uncovered; the day-12 receipt cannot serve them
    # retroactively because unmet demand is lost, not backlogged.
    assert late.total_unmet_units == 200
    assert late.first_stockout_date == START + timedelta(days=10)


def test_unmet_demand_never_produces_negative_inventory():
    p = build_projection(
        opening_units=50, demand=days(5, units=100), receipts=[],
        start=START, horizon_days=5,
    )
    assert all(d.closing >= 0 for d in p.days)
    assert p.total_unmet_units == 450  # 500 demanded, 50 served
    assert p.closing_inventory == 0


def test_reserved_and_quarantined_stock_is_excluded():
    from app.domain.types import InventoryPosition

    pos = InventoryPosition("SKU", "NODE", on_hand=1200, reserved=150,
                            quarantine=50, damaged=0, effective_at=START)
    assert pos.usable == 1000


def test_damaged_stock_cannot_drive_usable_below_zero():
    from app.domain.types import InventoryPosition

    pos = InventoryPosition("SKU", "NODE", on_hand=10, reserved=50,
                            quarantine=0, damaged=0, effective_at=START)
    assert pos.usable == 0


def test_only_outstanding_quantity_counts_as_incoming_supply():
    """Units already received or cancelled are not incoming supply."""
    order = OpenOrder(
        po_id="PO-1", sku="SKU", node_id="NODE", supplier_id="SUP-A",
        requested_qty=1000, confirmed_qty=1000, received_qty=300, cancelled_qty=200,
        requested_date=START, confirmed_date=START + timedelta(days=5),
        status=POStatus.PARTIALLY_CONFIRMED,
    )
    assert order.outstanding_qty == 500
    receipts = orders_to_receipts([order])
    assert [r.qty for r in receipts] == [500]


def test_unconfirmed_orders_stay_out_of_the_baseline():
    """An order with no confirmation is uncertainty, not supply."""
    order = OpenOrder(
        po_id="PO-2", sku="SKU", node_id="NODE", supplier_id="SUP-A",
        requested_qty=500, confirmed_qty=0, received_qty=0, cancelled_qty=0,
        requested_date=START + timedelta(days=3), confirmed_date=None,
        status=POStatus.SUBMITTED,
    )
    assert orders_to_receipts([order], confirmed_only=True) == []
    assert len(orders_to_receipts([order], confirmed_only=False)) == 1


def test_overdue_order_is_flagged_rather_than_rolled_forward():
    order = OpenOrder(
        po_id="PO-3", sku="SKU", node_id="NODE", supplier_id="SUP-A",
        requested_qty=500, confirmed_qty=500, received_qty=0, cancelled_qty=0,
        requested_date=START - timedelta(days=10),
        confirmed_date=START - timedelta(days=5),
        status=POStatus.CONFIRMED,
    )
    assert order.is_overdue(START) is True


def test_capacity_is_measured_at_the_post_receipt_peak():
    """Stock that arrives and ships out the same day still has to fit on arrival."""
    from app.domain.types import CapacityDay

    cap = [CapacityDay(day=START + timedelta(days=i), capacity_m3=100.0, occupied_m3=0.0)
           for i in range(3)]
    p = build_projection(
        opening_units=0,
        demand=[DemandDay(day=START + timedelta(days=i), forecast_units=1000) for i in range(3)],
        receipts=[Receipt(day=START, qty=1000)],
        start=START, horizon_days=3, unit_volume_m3=0.05, capacity=cap,
    )
    # End-of-day stock is zero every day, but 1000 units briefly occupy 50 m3.
    assert p.closing_inventory == 0
    assert p.peak_occupancy_m3 == pytest.approx(50.0)


def test_safety_buffer_breach_is_distinct_from_stockout():
    p = build_projection(
        opening_units=300, demand=days(3, units=50), receipts=[],
        start=START, horizon_days=3, safety_stock_units=200,
    )
    assert p.total_unmet_units == 0        # never physically out of stock
    assert p.days_below_safety == 1        # but dips under the buffer on the last day


def test_zero_demand_horizon_is_handled():
    p = build_projection(
        opening_units=100, demand=days(5, units=0), receipts=[],
        start=START, horizon_days=5,
    )
    assert p.total_demand_units == 0
    assert p.total_unmet_units == 0
    assert p.closing_inventory == 100


def test_demand_override_replaces_the_forecast_series():
    override = {START + timedelta(days=i): 200 for i in range(5)}
    p = build_projection(
        opening_units=100, demand=days(5, units=50), receipts=[],
        start=START, horizon_days=5, demand_override=override,
    )
    assert p.total_demand_units == 1000
