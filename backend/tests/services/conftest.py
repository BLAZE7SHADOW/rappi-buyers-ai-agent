"""Isolated database per test, so execution tests never share state."""

import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

START = date(2026, 9, 17)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Fresh SQLite file plus tight autonomy limits, rebuilt for every test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t_{uuid.uuid4().hex[:6]}.db")
    monkeypatch.setenv("AUTONOMY_SPEND_LIMIT_MINOR", "200000")   # $2,000
    monkeypatch.setenv("AUTONOMY_FEE_LIMIT_MINOR", "25000")      # $250

    import app.config as config
    config.get_settings.cache_clear()

    import app.db.engine as engine_mod
    engine_mod._engine = None
    engine_mod.create_all()

    yield engine_mod

    engine_mod._engine = None
    config.get_settings.cache_clear()


def make_case(
    *,
    sku="SKU-1001",
    node_id="NODE-BOG",
    on_hand=1200,
    reserved=150,
    quarantine=50,
    demand_per_day=100,
    horizon=28,
    budget_minor=900_000,
    po=("PO-501", 2000, 14),
    behavior="confirm_full",
    expedite=True,
    unit_price=1500,
    capacity_m3=200.0,
):
    """Seed one purchasing situation and return its case id."""
    from app.db import schema as s
    from app.db.engine import transaction

    case_id = f"CASE-{uuid.uuid4().hex[:6].upper()}"
    with transaction() as conn:
        conn.execute(s.products.insert().values(
            sku=sku, name="Test product", unit_volume_m3=0.02, status="active"))
        conn.execute(s.nodes.insert().values(
            node_id=node_id, name="Bogota DC", timezone="America/Bogota",
            capacity_m3=capacity_m3))
        conn.execute(s.inventory_snapshots.insert().values(
            sku=sku, node_id=node_id, on_hand=on_hand, reserved=reserved,
            quarantine=quarantine, damaged=0, effective_at=START, version=1))
        conn.execute(s.demand_records.insert(), [
            {"sku": sku, "node_id": node_id, "date": START + timedelta(days=i),
             "forecast_units": demand_per_day, "actual_sales_units": None,
             "in_stock_pct": None, "promotion_id": None}
            for i in range(horizon)
        ])
        conn.execute(s.capacity_projections.insert(), [
            {"node_id": node_id, "date": START + timedelta(days=i),
             "capacity_m3": capacity_m3, "occupied_m3": 20.0, "inbound_m3": 0.0, "version": 1}
            for i in range(horizon)
        ])
        conn.execute(s.suppliers.insert().values(
            supplier_id="SUP-A", name="Supplier A", reliability_score=0.95))
        conn.execute(s.supplier_quotes.insert().values(
            supplier_id="SUP-A", sku=sku, unit_price_minor=unit_price, moq=500,
            pack_size=50, lead_time_days=7, available_units=5000,
            quote_expires_at=START + timedelta(days=20), eligible=True,
            expedite_available=expedite, expedite_fee_minor=45000, expedite_days_saved=4))
        conn.execute(s.budgets.insert().values(
            scope=node_id, period=START.strftime("%Y-%m"), limit_minor=budget_minor,
            committed_minor=0, reserved_minor=0, version=1))
        if po:
            po_id, qty, day_offset = po
            conn.execute(s.purchase_orders.insert().values(
                po_id=po_id, sku=sku, node_id=node_id, supplier_id="SUP-A",
                requested_qty=qty, confirmed_qty=qty, received_qty=0, cancelled_qty=0,
                unit_price_minor=unit_price, fee_minor=0,
                requested_date=START + timedelta(days=day_offset),
                confirmed_date=START + timedelta(days=day_offset),
                status="confirmed", acknowledged_at=START, version=1))
        conn.execute(s.cases.insert().values(
            case_id=case_id, fixture_id="TEST", sku=sku, node_id=node_id,
            trigger_type="recommendation", trigger_payload='{"recommended_qty": 800}',
            signal_source="replenishment_system",
            title="Test case", state="investigating", replan_count=0,
            as_of_date=START, supplier_behavior=behavior))
    return case_id


def expedite_args(po_id="PO-501", days=4):
    return {"po_id": po_id, "new_date": (START + timedelta(days=14 - days)).isoformat(),
            "fee_minor": 45000, "supplier_id": "SUP-A"}


def create_po_args(qty=500, lead=7):
    return {"supplier_id": "SUP-A", "qty": qty,
            "expected_receipt_date": (START + timedelta(days=lead)).isoformat()}
