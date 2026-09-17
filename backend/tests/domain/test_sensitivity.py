"""The rule that decides when a person has to be asked.

These are the tests that make the ask-or-assume decision defensible: it is
arithmetic on the plan, not a judgement the model happens to make that run.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.domain.candidates import PlanningContext
from app.domain.sensitivity import UnverifiedSignal, evaluate
from app.domain.types import (
    Budget, CapacityDay, DemandDay, InventoryPosition, SupplierQuote,
)

TODAY = date(2026, 9, 17)


def day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def context(*, per_day: int = 60, on_hand: int = 600) -> PlanningContext:
    return PlanningContext(
        sku="SKU-X", node_id="N", today=TODAY,
        inventory=InventoryPosition(sku="SKU-X", node_id="N", on_hand=on_hand,
                                    reserved=0, quarantine=0, damaged=0, effective_at=TODAY),
        demand=[DemandDay(day=day(i), forecast_units=per_day) for i in range(28)],
        open_orders=[],
        quotes=[SupplierQuote(supplier_id="SUP-A", sku="SKU-X", unit_price_minor=900,
                              moq=100, pack_size=100, lead_time_days=5,
                              available_units=50_000, quote_expires_at=day(20), eligible=True)],
        budget=Budget(scope="N", period="2026-09", limit_minor=5_000_000,
                      committed_minor=0, reserved_minor=0),
        capacity=[CapacityDay(day=day(i), capacity_m3=400.0, occupied_m3=20.0, inbound_m3=0.0)
                  for i in range(28)],
        unit_volume_m3=0.02,
    )


def signal(units: int = 500, **kw) -> UnverifiedSignal:
    payload = {"units": units, "needed_by": day(13).isoformat(),
               "source": "sales", "description": "possible corporate bulk order"}
    payload.update(kw)
    return UnverifiedSignal.from_payload(payload)


# --------------------------------------------------------------------------- #
# Reading the signal
# --------------------------------------------------------------------------- #


def test_a_confirmed_signal_is_not_an_open_question():
    """Once confirmed it is ordinary demand and belongs in the forecast."""
    assert UnverifiedSignal.from_payload(
        {"units": 500, "needed_by": day(13).isoformat(), "confirmed": True}
    ) is None


def test_an_absent_or_malformed_signal_is_ignored_rather_than_guessed_at():
    assert UnverifiedSignal.from_payload(None) is None
    assert UnverifiedSignal.from_payload({}) is None
    assert UnverifiedSignal.from_payload({"units": 500}) is None          # no date
    assert UnverifiedSignal.from_payload({"needed_by": day(1).isoformat()}) is None
    assert UnverifiedSignal.from_payload({"units": 0, "needed_by": day(1).isoformat()}) is None
    assert UnverifiedSignal.from_payload(
        {"units": "many", "needed_by": day(1).isoformat()}) is None


# --------------------------------------------------------------------------- #
# The decision itself
# --------------------------------------------------------------------------- #


def test_no_signal_means_no_question():
    assert evaluate(context(), None) is None


def test_a_signal_that_would_change_the_order_is_material():
    result = evaluate(context(), signal(units=500))

    assert result.material is True
    assert result.quantity_with > result.quantity_without
    assert result.difference == 500
    # The two worlds must be described honestly to whoever is asked.
    assert str(result.quantity_without) in result.question()
    assert str(result.quantity_with) in result.question()
    assert len(result.options()) == 2


def test_a_signal_too_small_to_change_the_order_is_not_worth_asking_about():
    """Not every unknown deserves an interruption; that is the other failure mode."""
    result = evaluate(context(), signal(units=20))

    assert result.material is False
    assert result.difference < result.threshold_units


def test_materiality_scales_with_the_order_rather_than_being_a_flat_number():
    """200 units means something different on an order of 300 than on 30,000."""
    small = evaluate(context(per_day=10, on_hand=100), signal(units=300))
    large = evaluate(context(per_day=600, on_hand=6000), signal(units=300))

    assert large.threshold_units > small.threshold_units
    assert small.material is True       # 300 units dominates a small order
    assert large.material is False      # the same 300 disappears into a large one


def test_the_floor_stops_a_tiny_order_making_rounding_an_interruption():
    ctx = context(per_day=5, on_hand=50)
    assert evaluate(ctx, signal(units=10)).threshold_units == (
        ctx.policy.sensitivity_materiality_floor_units
    )


def test_the_threshold_is_policy_and_can_be_retuned_without_touching_the_rule():
    ctx = context()
    strict = replace(ctx, policy=replace(ctx.policy, sensitivity_materiality_pct=1.0,
                                         sensitivity_materiality_floor_units=1))
    relaxed = replace(ctx, policy=replace(ctx.policy, sensitivity_materiality_pct=90.0,
                                          sensitivity_materiality_floor_units=1))

    assert evaluate(strict, signal(units=200)).material is True
    assert evaluate(relaxed, signal(units=200)).material is False


def test_the_comparison_changes_only_the_signal_day():
    """Both worlds must run identical arithmetic or the difference means nothing."""
    ctx = context()
    result = evaluate(ctx, signal(units=500))

    # Baseline is untouched by the evaluation.
    assert result.quantity_without == evaluate(ctx, signal(units=500)).quantity_without
    assert [d.forecast_units for d in ctx.demand] == [60] * 28
    assert ctx.demand_override is None
