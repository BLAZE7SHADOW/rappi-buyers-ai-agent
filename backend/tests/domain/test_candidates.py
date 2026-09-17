"""Candidate shaping, constraint enforcement, and ranking."""

from datetime import date, timedelta

from app.domain.candidates import (
    PlanningContext, baseline_projection, generate_candidates, rank,
    required_quantity, round_to_pack, simulate, simulate_all,
)
from app.domain.constraints import check_budget, check_excess_stock
from app.domain.types import (
    ActionType, Budget, CapacityDay, Candidate, DemandDay, InventoryPosition,
    OpenOrder, POStatus, PolicyConfig, SupplierQuote,
)

START = date(2026, 9, 17)


def ctx(**over):
    base = dict(
        sku="SKU-1001", node_id="NODE-BOG", today=START,
        inventory=InventoryPosition("SKU-1001", "NODE-BOG", 1200, 150, 50, 0, START),
        demand=[DemandDay(day=START + timedelta(days=i), forecast_units=100) for i in range(28)],
        open_orders=[OpenOrder("PO-501", "SKU-1001", "NODE-BOG", "SUP-A", 2000, 2000, 0, 0,
                               START + timedelta(days=14), START + timedelta(days=14),
                               POStatus.CONFIRMED, acknowledged_at=START)],
        quotes=[SupplierQuote("SUP-A", "SKU-1001", 1500, 500, 50, 7, 5000,
                              START + timedelta(days=20), True,
                              expedite_available=True, expedite_fee_minor=45000,
                              expedite_days_saved=4)],
        budget=Budget("NODE-BOG", "2026-09", 900_000, 0, 0),
        capacity=[CapacityDay(day=START + timedelta(days=i), capacity_m3=200.0, occupied_m3=20.0)
                  for i in range(28)],
        unit_volume_m3=0.02, policy=PolicyConfig(),
    )
    base.update(over)
    return PlanningContext(**base)


# --- quantity shaping ------------------------------------------------------- #

def test_quantity_rounds_up_to_moq_then_pack():
    q = SupplierQuote("SUP-A", "SKU", 1000, moq=500, pack_size=50, lead_time_days=7,
                      available_units=5000, quote_expires_at=START)
    assert round_to_pack(120, q) == 500      # below MOQ, lifted to MOQ
    assert round_to_pack(510, q) == 550      # above MOQ, rounded to pack
    assert round_to_pack(0, q) == 0          # no order means no rounding


def test_moq_rounding_can_break_budget_and_must_be_rechecked():
    """Rounding happens before feasibility, so an MOQ-inflated order can fail."""
    q = SupplierQuote("SUP-A", "SKU", 1500, moq=500, pack_size=50, lead_time_days=7,
                      available_units=5000, quote_expires_at=START)
    qty = round_to_pack(100, q)
    assert qty == 500
    tight = Budget("N", "P", 100_000, 0, 0)  # $1,000 available
    cand = Candidate(ActionType.CREATE_PO, supplier_id="SUP-A", qty=qty, unit_price_minor=1500)
    check = check_budget(cand, tight)
    assert check.passed is False
    assert "exceeds available budget" in check.binding_reason


# --- the F1 decision -------------------------------------------------------- #

def test_baseline_shows_a_timing_shortage_not_a_volume_shortage():
    c = ctx()
    before = baseline_projection(c)
    assert before.total_unmet_units == 400
    assert before.first_stockout_date == START + timedelta(days=10)
    # Total supply exceeds total demand: the problem is when it lands, not how much.
    assert c.inventory.usable + 2000 > before.total_demand_units


def test_recommended_800_units_is_rejected_on_budget():
    results = simulate_all(ctx(), recommended_qty=800)
    eight = next(r for r in results
                 if r.candidate.action_type == ActionType.CREATE_PO and r.candidate.qty == 800)
    assert eight.feasible is False
    assert "budget" in eight.binding_constraints


def test_expedite_is_ranked_above_buying_more():
    ranked = rank(simulate_all(ctx(), recommended_qty=800))
    winner = ranked[0]
    assert winner.candidate.action_type == ActionType.EXPEDITE_PO
    assert winner.after.total_unmet_units == 0
    assert winner.incremental_cost_minor == 45_000


def test_expedite_moves_supply_instead_of_duplicating_it():
    """The most dangerous bug in this domain: an expedite that adds a second
    receipt makes the plan look twice as good as it is."""
    c = ctx()
    expedite = next(x for x in generate_candidates(c) if x.action_type == ActionType.EXPEDITE_PO)
    sim = simulate(c, expedite)
    incoming = sum(d.receipts for d in sim.after.days)
    assert incoming == 2000                      # not 4000

    # Expediting adds no units, it only moves them earlier. The stock that now
    # serves the previously-lost 400 units comes out of closing inventory, so the
    # books balance exactly: what gets served is what stops being left over.
    assert sim.unmet_reduction == 400
    assert sim.after.closing_inventory == sim.before.closing_inventory - 400


def test_keep_plan_is_always_offered_so_doing_nothing_is_scored():
    cands = generate_candidates(ctx())
    assert any(x.action_type == ActionType.KEEP_PLAN for x in cands)


def test_required_quantity_covers_shortfall_and_safety_gap():
    assert required_quantity(ctx()) == 400


# --- constraint behaviour --------------------------------------------------- #

def test_capacity_blocks_an_order_that_cannot_physically_fit():
    tight = [CapacityDay(day=START + timedelta(days=i), capacity_m3=12.0, occupied_m3=0.0)
             for i in range(28)]
    results = simulate_all(ctx(capacity=tight, open_orders=[]), recommended_qty=800)
    big = next(r for r in results if r.candidate.qty == 800)
    assert big.feasible is False
    assert "capacity" in big.binding_constraints


def test_expired_quote_blocks_the_order():
    stale = [SupplierQuote("SUP-A", "SKU-1001", 1500, 500, 50, 7, 5000,
                           quote_expires_at=START - timedelta(days=1))]
    results = simulate_all(ctx(quotes=stale), recommended_qty=800)
    orders = [r for r in results if r.candidate.action_type == ActionType.CREATE_PO]
    assert orders and all(not r.feasible for r in orders)
    assert all("quote_validity" in r.binding_constraints for r in orders)


def test_ineligible_supplier_is_never_offered():
    blocked = [SupplierQuote("SUP-C", "SKU-1001", 900, 100, 10, 2, 5000,
                             START + timedelta(days=20), eligible=False)]
    cands = generate_candidates(ctx(quotes=blocked))
    assert not any(x.action_type == ActionType.CREATE_PO for x in cands)


def test_supplier_availability_caps_the_order():
    scarce = [SupplierQuote("SUP-A", "SKU-1001", 1500, 100, 50, 7, available_units=200,
                            quote_expires_at=START + timedelta(days=20))]
    results = simulate_all(ctx(quotes=scarce, open_orders=[]), recommended_qty=800)
    big = next(r for r in results if r.candidate.qty == 800)
    assert big.feasible is False
    assert "availability" in big.binding_constraints


def test_excess_stock_uses_a_unit_cap_when_demand_is_zero():
    """Days-of-cover is undefined at zero demand, so a flat cap applies instead."""
    from app.domain.projection import build_projection

    flat = build_projection(
        opening_units=500,
        demand=[DemandDay(day=START + timedelta(days=i), forecast_units=0) for i in range(28)],
        receipts=[], start=START, horizon_days=28,
    )
    check = check_excess_stock(flat, PolicyConfig(zero_demand_unit_cap=100))
    assert check.passed is False
    assert "Zero forecast demand" in check.binding_reason


def test_infeasible_options_are_kept_for_explanation_not_discarded():
    ranked = rank(simulate_all(ctx(), recommended_qty=800))
    assert any(not r.feasible for r in ranked)
    # Infeasible options sort last so they never win, but remain inspectable.
    assert ranked[-1].feasible is False
