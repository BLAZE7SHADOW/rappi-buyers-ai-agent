"""Seed fixture data for the AI Purchasing Agent.

This package is the single source of truth for demo/eval fixture numbers. Every
number here is chosen so it has been run through the actual domain engine
(``app.domain.candidates`` / ``app.domain.projection`` / ``app.domain.demand``)
and produces the outcome recorded in each fixture's ``expected`` dict -- see
``backend/tests/domain/test_fixtures.py`` for the assertions that hold this
promise.

Layout: each fixture is a plain dict of rows, one list per database table,
shaped to match ``app.db.schema`` columns exactly (so ``app.db.seed`` can just
``INSERT`` each list). Dates are stored as ``datetime.date`` objects computed
from ``ANCHOR`` ("day 0" = 2026-09-17, "today" for every fixture). Money is
integer minor units (cents); quantities are integers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

ANCHOR: date = date(2026, 9, 17)


@dataclass(frozen=True)
class Fixture:
    """One seedable scenario: DB rows to insert, plus the one place its expected
    outcome is recorded. ``seed.py`` inserts the rows; ``test_fixtures.py`` and
    any eval harness both read ``expected`` instead of hard-coding numbers twice.
    """

    fixture_id: str
    case_id: str
    sku: str
    node_id: str
    products: list[dict] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    inventory_snapshots: list[dict] = field(default_factory=list)
    demand_records: list[dict] = field(default_factory=list)
    promotions: list[dict] = field(default_factory=list)
    suppliers: list[dict] = field(default_factory=list)
    supplier_quotes: list[dict] = field(default_factory=list)
    purchase_orders: list[dict] = field(default_factory=list)
    budgets: list[dict] = field(default_factory=list)
    capacity_projections: list[dict] = field(default_factory=list)
    case: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)


def day(offset: int) -> date:
    """``offset`` days from the anchor date. Negative offsets are in the past."""
    return ANCHOR + timedelta(days=offset)


PERIOD = ANCHOR.strftime("%Y-%m")  # "2026-09" -- the budget period every fixture uses


# --------------------------------------------------------------------------- #
# Shared builders
# --------------------------------------------------------------------------- #


def _product(sku: str, name: str, unit_volume_m3: float = 0.02) -> dict:
    return {"sku": sku, "name": name, "unit_volume_m3": unit_volume_m3, "status": "active"}


def _node(node_id: str = "NODE-BOG", name: str = "Bogota DC", capacity_m3: float = 200.0) -> dict:
    return {"node_id": node_id, "name": name, "timezone": "America/Bogota", "capacity_m3": capacity_m3}


def _inventory(sku: str, node_id: str, on_hand: int, reserved: int = 0,
                quarantine: int = 0, damaged: int = 0) -> dict:
    return {
        "sku": sku, "node_id": node_id, "on_hand": on_hand, "reserved": reserved,
        "quarantine": quarantine, "damaged": damaged, "effective_at": day(0), "version": 1,
    }


def _flat_demand(sku: str, node_id: str, units_per_day: int, horizon: int = 28,
                  start_offset: int = 0) -> list[dict]:
    """``horizon`` days of plain forecast demand, no sales evidence."""
    return [
        {"sku": sku, "node_id": node_id, "date": day(start_offset + i),
         "forecast_units": units_per_day, "actual_sales_units": None,
         "in_stock_pct": None, "promotion_id": None}
        for i in range(horizon)
    ]


def _steady_history(sku: str, node_id: str, units_per_day: int, days: int = 14) -> list[dict]:
    """Past days where sales matched forecast and stock never ran out.

    Every fixture that plans from a flat forecast needs one. Without it the
    lookback window is empty, and an empty window reads as *zero sales* rather
    than *no data* -- the exact trap this system exists to avoid. A live run
    caught it: the agent stopped to ask why a 35/day forecast had seen no sales
    in fourteen days, which was a fair question about fixture data rather than
    about purchasing. F4 is deliberately excluded; its censored and promotional
    history is the scenario itself.
    """
    return [
        {"sku": sku, "node_id": node_id, "date": day(-offset),
         "forecast_units": units_per_day, "actual_sales_units": units_per_day,
         "in_stock_pct": 1.0, "promotion_id": None}
        for offset in range(days, 0, -1)
    ]


def _supplier(supplier_id: str, name: str, reliability_score: float = 0.95) -> dict:
    return {"supplier_id": supplier_id, "name": name, "reliability_score": reliability_score}


def _quote(supplier_id: str, sku: str, unit_price_minor: int, moq: int, pack_size: int,
           lead_time_days: int, available_units: int, expires_offset: int = 20,
           eligible: bool = True, expedite_available: bool = False,
           expedite_fee_minor: int = 0, expedite_days_saved: int = 0) -> dict:
    return {
        "supplier_id": supplier_id, "sku": sku, "unit_price_minor": unit_price_minor,
        "moq": moq, "pack_size": pack_size, "lead_time_days": lead_time_days,
        "available_units": available_units, "quote_expires_at": day(expires_offset),
        "eligible": eligible, "expedite_available": expedite_available,
        "expedite_fee_minor": expedite_fee_minor, "expedite_days_saved": expedite_days_saved,
    }


def _po(po_id: str, sku: str, node_id: str, supplier_id: str, requested_qty: int,
        confirmed_qty: int, unit_price_minor: int, confirmed_offset: int,
        requested_offset: int = -7, status: str = "confirmed",
        acknowledged_offset: int | None = 0) -> dict:
    return {
        "po_id": po_id, "sku": sku, "node_id": node_id, "supplier_id": supplier_id,
        "requested_qty": requested_qty, "confirmed_qty": confirmed_qty, "received_qty": 0,
        "cancelled_qty": 0, "unit_price_minor": unit_price_minor, "fee_minor": 0,
        "requested_date": day(requested_offset), "confirmed_date": day(confirmed_offset),
        "status": status,
        "acknowledged_at": day(acknowledged_offset) if acknowledged_offset is not None else None,
        "created_by_case": None, "version": 1,
    }


def _budget(node_id: str, limit_minor: int, committed_minor: int = 0, reserved_minor: int = 0) -> dict:
    return {
        "scope": node_id, "period": PERIOD, "limit_minor": limit_minor,
        "committed_minor": committed_minor, "reserved_minor": reserved_minor, "version": 1,
    }


def _capacity(node_id: str, capacity_m3: float, occupied_m3: float, horizon: int = 28) -> list[dict]:
    return [
        {"node_id": node_id, "date": day(i), "capacity_m3": capacity_m3,
         "occupied_m3": occupied_m3, "inbound_m3": 0.0, "version": 1}
        for i in range(horizon)
    ]


def _case(case_id: str, fixture_id: str, sku: str, node_id: str, trigger_type: str,
          trigger_payload: str, title: str, supplier_behavior: str) -> dict:
    signal_source = "demand_monitor" if trigger_type == "demand_spike" else "replenishment_system"
    return {
        "case_id": case_id, "fixture_id": fixture_id, "sku": sku, "node_id": node_id,
        "trigger_type": trigger_type, "trigger_payload": trigger_payload,
        "signal_source": signal_source, "title": title,
        "state": "investigating", "replan_count": 0, "as_of_date": day(0),
        "supplier_behavior": supplier_behavior,
    }


# --------------------------------------------------------------------------- #
# F1 -- headline: reject the 800-unit recommendation, expedite PO-501 instead
# --------------------------------------------------------------------------- #

_F1_SKU, _F1_NODE = "SKU-1001", "NODE-BOG-F1"

F1 = {
    "fixture_id": "F1",
    "products": [_product(_F1_SKU, "Sparkling Water 330ml · 12-pack")],
    "nodes": [_node(_F1_NODE, name="Bogotá North Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F1_SKU, _F1_NODE, on_hand=1200, reserved=150, quarantine=50)],
    "demand_records": (_steady_history(_F1_SKU, _F1_NODE, units_per_day=100)
                       + _flat_demand(_F1_SKU, _F1_NODE, units_per_day=100)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95), _supplier("SUP-B", "Supplier B", 0.9)],
    "supplier_quotes": [
        _quote("SUP-A", _F1_SKU, unit_price_minor=1500, moq=500, pack_size=50, lead_time_days=7,
               available_units=5000, expires_offset=20, expedite_available=True,
               expedite_fee_minor=45000, expedite_days_saved=4),
        _quote("SUP-B", _F1_SKU, unit_price_minor=1750, moq=250, pack_size=50, lead_time_days=3,
               available_units=3000, expires_offset=20),
    ],
    "purchase_orders": [
        _po("PO-501", _F1_SKU, _F1_NODE, "SUP-A", requested_qty=2000, confirmed_qty=2000,
            unit_price_minor=1500, confirmed_offset=14),
    ],
    # $10,000. Tuned so the recommended 800 units ($12,000) is genuinely
    # unaffordable, while the 600-unit follow-up after a partial confirmation
    # ($9,000 + the $450 expedite fee already committed) still fits -- so the
    # feedback loop has a real second lever rather than dead-ending.
    "budgets": [_budget(_F1_NODE, limit_minor=1_000_000)],
    "capacity_projections": _capacity(_F1_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F1", "F1", _F1_SKU, _F1_NODE, "recommendation",
        '{"recommended_qty": 800, "reason": "Reorder point breach"}',
        "Sparkling Water · review 800-unit recommendation", "confirm_partial",
    ),
    "expected": {
        "baseline_unmet": 400,
        "first_stockout": "2026-09-27",
        "recommended_qty": 800,
        "recommended_800_binding_constraints": ["budget"],
        "disposition": "reject",
        "action_type": "expedite_po",
        "po_id": "PO-501",
        "expedite_new_date": "2026-09-27",
        "expedite_fee_minor": 45000,
        "after_unmet": 0,
        "autonomy_fee_limit_minor": 25_000,
        "approval_required": True,
    },
}


# --------------------------------------------------------------------------- #
# F2 -- accept: the 800-unit recommendation is exactly right
# --------------------------------------------------------------------------- #

_F2_SKU, _F2_NODE = "SKU-1002", "NODE-BOG-F2"

F2 = {
    "fixture_id": "F2",
    "products": [_product(_F2_SKU, "UHT Whole Milk 1L")],
    "nodes": [_node(_F2_NODE, name="Bogotá Central Fulfillment Center")],
    # on_hand 430 - reserved 50 = usable 380
    "inventory_snapshots": [_inventory(_F2_SKU, _F2_NODE, on_hand=430, reserved=50)],
    "demand_records": (_steady_history(_F2_SKU, _F2_NODE, units_per_day=35)
                       + _flat_demand(_F2_SKU, _F2_NODE, units_per_day=35)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F2_SKU, unit_price_minor=1200, moq=500, pack_size=100,
               lead_time_days=7, available_units=5000, expires_offset=20),
    ],
    "purchase_orders": [],
    "budgets": [_budget(_F2_NODE, limit_minor=2_000_000)],
    "capacity_projections": _capacity(_F2_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F2", "F2", _F2_SKU, _F2_NODE, "recommendation",
        '{"recommended_qty": 800}',
        "UHT Whole Milk · review 800-unit recommendation", "confirm_full",
    ),
    "expected": {
        "baseline_unmet": 600,
        "required_quantity": 800,
        "recommended_qty": 800,
        "disposition": "accept",
        "action_type": "create_po",
        "qty": 800,
        "cost_minor": 960_000,
        "feasible": True,
        "after_unmet": 0,
    },
}


# --------------------------------------------------------------------------- #
# F3 -- modify down: capacity AND demand both cap the 800-unit recommendation
# --------------------------------------------------------------------------- #

_F3_SKU, _F3_NODE = "SKU-1003", "NODE-BOG-F3"

F3 = {
    "fixture_id": "F3",
    "products": [_product(_F3_SKU, "Frozen Blueberries 500g")],
    "nodes": [_node(_F3_NODE, name="Bogotá Cold-chain Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F3_SKU, _F3_NODE, on_hand=176)],
    "demand_records": (_steady_history(_F3_SKU, _F3_NODE, units_per_day=17)
                       + _flat_demand(_F3_SKU, _F3_NODE, units_per_day=17)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F3_SKU, unit_price_minor=1300, moq=250, pack_size=50,
               lead_time_days=7, available_units=5000, expires_offset=20),
    ],
    "purchase_orders": [],
    "budgets": [_budget(_F3_NODE, limit_minor=5_000_000)],
    # Tight headroom: at the arrival date, roughly 12 m3 is free before the
    # 200 m3 ceiling is hit, capping an order at ~600 units (0.02 m3/unit).
    "capacity_projections": _capacity(_F3_NODE, capacity_m3=200.0, occupied_m3=186.86),
    "case": _case(
        "CASE-F3", "F3", _F3_SKU, _F3_NODE, "recommendation",
        '{"recommended_qty": 800}',
        "Frozen Blueberries · capacity-constrained recommendation", "confirm_full",
    ),
    "expected": {
        "baseline_unmet": 300,
        "first_stockout": "2026-09-27",
        "required_quantity": 500,
        "recommended_qty": 800,
        "recommended_800_binding_constraints": ["capacity", "excess_stock"],
        "disposition": "modify",
        "action_type": "create_po",
        "qty": 500,
        "qty_band": [450, 600],
        "after_unmet": 0,
    },
}


# --------------------------------------------------------------------------- #
# F4 -- demand spike + stockout-censored trap
# --------------------------------------------------------------------------- #

_F4_SKU, _F4_NODE = "SKU-1004", "NODE-BOG-F4"
_F4_PROMO_START, _F4_PROMO_END = -10, 6


def _f4_demand_records() -> list[dict]:
    rows: list[dict] = []
    # 14 days of history: 130/day actual sales except three stockout-censored days.
    for i in range(-14, 0):
        censored = i in (-11, -10, -9)
        promo_active = _F4_PROMO_START <= i <= _F4_PROMO_END
        rows.append({
            "sku": _F4_SKU, "node_id": _F4_NODE, "date": day(i), "forecast_units": 50,
            "actual_sales_units": 0 if censored else 130,
            "in_stock_pct": 0.0 if censored else 1.0,
            "promotion_id": "PROMO-1" if promo_active else None,
        })
    # 28-day forward horizon: forecast only, no sales evidence yet.
    for i in range(28):
        promo_active = _F4_PROMO_START <= i <= _F4_PROMO_END
        rows.append({
            "sku": _F4_SKU, "node_id": _F4_NODE, "date": day(i), "forecast_units": 50,
            "actual_sales_units": None, "in_stock_pct": None,
            "promotion_id": "PROMO-1" if promo_active else None,
        })
    return rows


F4 = {
    "fixture_id": "F4",
    "products": [_product(_F4_SKU, "Energy Drink 250ml")],
    "nodes": [_node(_F4_NODE, name="Bogotá West Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F4_SKU, _F4_NODE, on_hand=1000)],
    "demand_records": _f4_demand_records(),
    "promotions": [{
        "promotion_id": "PROMO-1", "sku": _F4_SKU,
        "start_date": day(_F4_PROMO_START), "end_date": day(_F4_PROMO_END),
        "uplift_factor": 2.6, "label": "Spike promo",
    }],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F4_SKU, unit_price_minor=1400, moq=300, pack_size=50,
               lead_time_days=7, available_units=5000, expires_offset=20),
    ],
    "purchase_orders": [],
    "budgets": [_budget(_F4_NODE, limit_minor=5_000_000)],
    "capacity_projections": _capacity(_F4_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F4", "F4", _F4_SKU, _F4_NODE, "demand_spike",
        '{"forecast_daily_units": 50, "note": "Recent sales are running well above forecast"}',
        "Energy Drink · promotion demand spike", "confirm_full",
    ),
    "expected": {
        "censored_day_count": 3,
        "censored_days": ["2026-09-06", "2026-09-07", "2026-09-08"],
        "observed_daily_sales_excluding_censored": 130.0,
        "forecast_daily_units": 50.0,
        "active_promotion_id": "PROMO-1",
        "promotion_end_date": "2026-09-23",
        # Promotion-bounded: observed rate through the promo's end, forecast x
        # 1.2 residual afterwards. NOT the naive "130/day forever" extrapolation.
        "promotion_bounded_total_demand": 2170,
        "naive_sustained_total_demand": 3640,
    },
}


# --------------------------------------------------------------------------- #
# F5 -- recovery: same shape as F1, but the supplier times out after success
# --------------------------------------------------------------------------- #

_F5_SKU, _F5_NODE = "SKU-1005", "NODE-BOG-F5"

F5 = {
    "fixture_id": "F5",
    "products": [_product(_F5_SKU, "Baby Diapers Size M · 40-pack")],
    "nodes": [_node(_F5_NODE, name="Bogotá South Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F5_SKU, _F5_NODE, on_hand=1200, reserved=150, quarantine=50)],
    "demand_records": (_steady_history(_F5_SKU, _F5_NODE, units_per_day=100)
                       + _flat_demand(_F5_SKU, _F5_NODE, units_per_day=100)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95), _supplier("SUP-B", "Supplier B", 0.9)],
    "supplier_quotes": [
        _quote("SUP-A", _F5_SKU, unit_price_minor=1500, moq=500, pack_size=50, lead_time_days=7,
               available_units=5000, expires_offset=20, expedite_available=True,
               expedite_fee_minor=45000, expedite_days_saved=4),
        _quote("SUP-B", _F5_SKU, unit_price_minor=1750, moq=250, pack_size=50, lead_time_days=3,
               available_units=3000, expires_offset=20),
    ],
    "purchase_orders": [
        _po("PO-505", _F5_SKU, _F5_NODE, "SUP-A", requested_qty=2000, confirmed_qty=2000,
            unit_price_minor=1500, confirmed_offset=14),
    ],
    "budgets": [_budget(_F5_NODE, limit_minor=1_000_000)],
    "capacity_projections": _capacity(_F5_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F5", "F5", _F5_SKU, _F5_NODE, "recommendation",
        '{"recommended_qty": 800, "reason": "Reorder point breach"}',
        "Baby Diapers · supplier timeout recovery", "timeout_after_success",
    ),
    "expected": {
        # Same engine outcome as F1 -- this fixture is about the retry path, not
        # a different purchasing decision.
        "baseline_unmet": 400,
        "first_stockout": "2026-09-27",
        "disposition": "reject",
        "action_type": "expedite_po",
        "po_id": "PO-505",
        "after_unmet": 0,
        "approval_required": True,
        # What the executor layer (backend/tests/services/test_execution.py,
        # `timeout_after_success` behavior) is responsible for proving: a retry
        # after an ambiguous timeout must not create a second purchase order.
        # The mechanism it relies on is this UNIQUE constraint.
        "idempotency_guarantee": "actions.idempotency_key UNIQUE constraint",
        "expected_po_count_after_retry": 1,
    },
}


# --------------------------------------------------------------------------- #
# F6 -- escalate: a genuine shortfall with no affordable lever
# --------------------------------------------------------------------------- #

_F6_SKU, _F6_NODE = "SKU-1006", "NODE-BOG-F6"

F6 = {
    "fixture_id": "F6",
    "products": [_product(_F6_SKU, "Basmati Rice 5kg")],
    "nodes": [_node(_F6_NODE, name="Bogotá East Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F6_SKU, _F6_NODE, on_hand=800)],
    "demand_records": (_steady_history(_F6_SKU, _F6_NODE, units_per_day=50)
                       + _flat_demand(_F6_SKU, _F6_NODE, units_per_day=50)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F6_SKU, unit_price_minor=1000, moq=100, pack_size=50,
               lead_time_days=7, available_units=2000, expires_offset=20),
    ],
    "purchase_orders": [],
    "budgets": [_budget(_F6_NODE, limit_minor=0)],
    "capacity_projections": _capacity(_F6_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F6", "F6", _F6_SKU, _F6_NODE, "recommendation",
        '{"recommended_qty": 600}',
        "Basmati Rice · shortfall with no available budget", "confirm_full",
    ),
    "expected": {
        "baseline_unmet": 600,
        "budget_available_minor": 0,
        "recommended_qty": 600,
        "recommended_600_binding_constraints": ["budget"],
        "disposition": "escalate",
        "action_type": "none",
    },
}


# --------------------------------------------------------------------------- #
# F7 -- investigate: a commercial fact no system of record holds
#
# The fourth Scenario-1 outcome. Sales flagged a possible one-off bulk order that
# appears in no forecast, promotion or purchase order. What makes this a question
# rather than an assumption is that the answer changes the action: covering it is
# genuinely feasible here (1,800 units still sits inside the 12-day cover
# ceiling), so "yes" and "no" lead to different orders 500 units and $4,500 apart.
#
# An earlier version of this fixture used a bulk order so large that hedging
# breached the excess-stock ceiling. The agent correctly refused to ask, because
# no answer could have changed what it did. Asking is only right when the answer
# has somewhere to go.
# --------------------------------------------------------------------------- #

_F7_SKU, _F7_NODE = "SKU-1007", "NODE-BOG-F7"

F7 = {
    "fixture_id": "F7",
    "products": [_product(_F7_SKU, "Ground Coffee 500g")],
    "nodes": [_node(_F7_NODE, name="Bogotá Center-North Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F7_SKU, _F7_NODE, on_hand=600)],
    # Steady, well-supplied history so the forecast is not in doubt: the single
    # open question is the bulk order, which appears nowhere in the data.
    "demand_records": (_steady_history(_F7_SKU, _F7_NODE, units_per_day=60)
                       + _flat_demand(_F7_SKU, _F7_NODE, units_per_day=60)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F7_SKU, unit_price_minor=900, moq=100, pack_size=100,
               lead_time_days=5, available_units=5000, expires_offset=20),
    ],
    "purchase_orders": [],
    "budgets": [_budget(_F7_NODE, limit_minor=3_000_000)],
    "capacity_projections": _capacity(_F7_NODE, capacity_m3=400.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F7", "F7", _F7_SKU, _F7_NODE, "recommendation",
        '{"recommended_qty": 1300, "note": "Sales flagged a possible one-off bulk order '
        'of about 500 units from a corporate customer this month. It is not confirmed, '
        'and it is not in the forecast."}',
        "Ground Coffee · unconfirmed bulk order changes the answer", "confirm_full",
    ),
    "expected": {
        "baseline_unmet": 1080,
        "first_stockout": "2026-09-27",
        # Raw need is 1280; the supplier's 100-unit pack rounds the order to 1300.
        "required_quantity": 1280,
        "recommended_qty": 1300,
        # Round one: the answer would change the order, so the agent must ask.
        "expects_buyer_question": True,
        "buyer_answer": (
            "The bulk order is not confirmed and may never happen. Do not buy stock for "
            "it. Cover the normal forecast demand only."
        ),
        # Round two, after the answer: forecast-only demand, not the phantom order.
        "disposition": "accept",
        "action_type": "create_po",
        "qty_band": [1200, 1400],
        # Covering the unconfirmed order is feasible -- which is exactly why the
        # question is worth asking -- so a proposal at this size means the agent
        # acted on the bulk order despite being told it is not confirmed.
        "qty_if_answer_ignored": 1800,
        "hedge_is_feasible": True,
        "feasible": True,
        "after_unmet": 0,
    },
}


# --------------------------------------------------------------------------- #
# F8 -- autonomous: small enough that no human is needed
#
# Every other fixture costs more than the $2,000 autonomy limit, so all of them
# stop for approval and the delegated-authority path is never demonstrated. This
# one is deliberately cheap: $1,650, no residual shortage, no missing evidence.
# The gate authorises it, the server executes it, and the validator checks it --
# with nobody clicking anything.
# --------------------------------------------------------------------------- #

_F8_SKU, _F8_NODE = "SKU-1008", "NODE-BOG-F8"

F8 = {
    "fixture_id": "F8",
    "products": [_product(_F8_SKU, "Paper Towels 6-roll")],
    "nodes": [_node(_F8_NODE, name="Bogotá Airport Fulfillment Center")],
    "inventory_snapshots": [_inventory(_F8_SKU, _F8_NODE, on_hand=350)],
    "demand_records": (_steady_history(_F8_SKU, _F8_NODE, units_per_day=25)
                       + _flat_demand(_F8_SKU, _F8_NODE, units_per_day=25)),
    "promotions": [],
    "suppliers": [_supplier("SUP-A", "Supplier A", 0.95)],
    "supplier_quotes": [
        _quote("SUP-A", _F8_SKU, unit_price_minor=300, moq=100, pack_size=50,
               lead_time_days=3, available_units=5000, expires_offset=20),
    ],
    # No open order: an unacknowledged or overdue one would be missing evidence,
    # and the gate refuses to act autonomously on incomplete information.
    "purchase_orders": [],
    "budgets": [_budget(_F8_NODE, limit_minor=500_000)],
    "capacity_projections": _capacity(_F8_NODE, capacity_m3=200.0, occupied_m3=20.0),
    "case": _case(
        "CASE-F8", "F8", _F8_SKU, _F8_NODE, "recommendation",
        '{"recommended_qty": 550, "reason": "Reorder point breach"}',
        "Paper Towels · low-value replenishment within delegated authority", "confirm_full",
    ),
    "expected": {
        "baseline_unmet": 350,
        "first_stockout": "2026-10-01",
        "required_quantity": 550,
        "recommended_qty": 550,
        "disposition": "accept",
        "action_type": "create_po",
        "qty": 550,
        "cost_minor": 165_000,
        "feasible": True,
        "after_unmet": 0,
        # Closing 200 against a 12-day cover ceiling of 300 leaves real margin, so
        # the autonomous outcome does not depend on landing exactly on a limit.
        "after_closing_inventory": 200,
        "excess_ceiling_units": 300,
        "gate_outcome": "autonomous",
        "approval_required": False,
        "expected_case_state": "resolved",
        "expected_verdict": "PASS",
    },
}


def _as_fixture(raw: dict) -> Fixture:
    return Fixture(
        fixture_id=raw["fixture_id"],
        case_id=raw["case"]["case_id"],
        sku=raw["case"]["sku"],
        node_id=raw["case"]["node_id"],
        products=raw["products"],
        nodes=raw["nodes"],
        inventory_snapshots=raw["inventory_snapshots"],
        demand_records=raw["demand_records"],
        promotions=raw["promotions"],
        suppliers=raw["suppliers"],
        supplier_quotes=raw["supplier_quotes"],
        purchase_orders=raw["purchase_orders"],
        budgets=raw["budgets"],
        capacity_projections=raw["capacity_projections"],
        case=raw["case"],
        expected=raw["expected"],
    )


FIXTURES: dict[str, Fixture] = {
    fid: _as_fixture(raw)
    for fid, raw in {"F1": F1, "F2": F2, "F3": F3, "F4": F4, "F5": F5, "F6": F6,
                     "F7": F7, "F8": F8}.items()
}
