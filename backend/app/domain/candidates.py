"""Candidate generation, simulation, and ranking.

Three levers exist and no more: keep the current plan, create a purchase order,
or expedite an existing one. Keeping the action set this small is deliberate --
every action the agent can take is one a human can audit.

Ranking applies hard constraints first, then an explicit ordering: meet the
service target, avoid excess exposure, minimise incremental cost. There is no
hidden weighted score; the simulator returns metrics and feasibility, and the
ordering is stated in code so it can be argued with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain import constraints as C
from app.domain.projection import build_projection, orders_to_receipts
from app.domain.types import (
    ActionType,
    Budget,
    CapacityDay,
    Candidate,
    ConstraintCheck,
    DemandDay,
    InventoryPosition,
    OpenOrder,
    PolicyConfig,
    Projection,
    Receipt,
    SimulationResult,
    SupplierQuote,
)


@dataclass
class PlanningContext:
    """Everything the engine needs to evaluate a purchasing situation.

    Assembled once from the repository, then passed to pure functions. Holding it
    in one object keeps the simulation reproducible: the same context always
    yields the same numbers.
    """

    sku: str
    node_id: str
    today: date
    inventory: InventoryPosition
    demand: list[DemandDay]
    open_orders: list[OpenOrder]
    quotes: list[SupplierQuote]
    budget: Budget | None
    capacity: list[CapacityDay]
    unit_volume_m3: float
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    demand_override: dict[date, int] | None = None

    def quote_for(self, supplier_id: str) -> SupplierQuote | None:
        return next((q for q in self.quotes if q.supplier_id == supplier_id), None)

    def order_for(self, po_id: str) -> OpenOrder | None:
        return next((o for o in self.open_orders if o.po_id == po_id), None)


# --------------------------------------------------------------------------- #
# Quantity shaping
# --------------------------------------------------------------------------- #


def round_to_pack(qty: int, quote: SupplierQuote) -> int:
    """Round a desired quantity up to something the supplier will actually accept.

    Rounding happens *before* feasibility is checked, never after: an order pushed
    up to the MOQ may no longer fit the budget or the warehouse, and that has to be
    caught rather than assumed away.
    """
    if qty <= 0:
        return 0
    qty = max(qty, quote.moq)
    if quote.pack_size > 1:
        remainder = qty % quote.pack_size
        if remainder:
            qty += quote.pack_size - remainder
    return qty


def affordable_quantity(ctx: PlanningContext, quote: SupplierQuote) -> int:
    """The largest pack-aligned quantity this supplier could sell within budget.

    Rounds *down* to the pack size, unlike :func:`round_to_pack`, because the
    point is to stay under a ceiling rather than to reach a minimum. Returns 0 if
    even the supplier's minimum order is unaffordable -- in which case this
    supplier genuinely offers no option and the situation needs escalation.
    """
    if ctx.budget is None or quote.unit_price_minor <= 0:
        return 0

    max_units = ctx.budget.available_minor // quote.unit_price_minor
    max_units = min(max_units, quote.available_units)

    if quote.pack_size > 1:
        max_units -= max_units % quote.pack_size
    if max_units < quote.moq:
        return 0
    return int(max_units)


def baseline_projection(ctx: PlanningContext, confirmed_only: bool = True) -> Projection:
    """The do-nothing case: current usable stock plus already-confirmed receipts."""
    return build_projection(
        opening_units=ctx.inventory.usable,
        demand=ctx.demand,
        receipts=orders_to_receipts(ctx.open_orders, confirmed_only=confirmed_only),
        start=ctx.today,
        horizon_days=ctx.policy.horizon_days,
        safety_stock_units=ctx.policy.safety_stock_units,
        unit_volume_m3=ctx.unit_volume_m3,
        capacity=ctx.capacity,
        confirmed_only=confirmed_only,
        demand_override=ctx.demand_override,
    )


def required_quantity(ctx: PlanningContext) -> int:
    """Units needed to clear the projected shortage and restore the safety buffer."""
    before = baseline_projection(ctx)
    shortfall = before.total_unmet_units
    buffer_gap = max(0, ctx.policy.safety_stock_units - before.closing_inventory)
    return shortfall + buffer_gap


# --------------------------------------------------------------------------- #
# Candidate generation
# --------------------------------------------------------------------------- #


def generate_candidates(
    ctx: PlanningContext, recommended_qty: int | None = None
) -> list[Candidate]:
    """Enumerate every supported intervention worth simulating.

    Always includes ``keep_plan`` so "do nothing" is scored on the same footing as
    spending money -- that is what lets the agent reject a purchase rather than
    treating buying as the default.
    """
    out: list[Candidate] = [Candidate(ActionType.KEEP_PLAN, label="Keep the existing plan")]

    need = required_quantity(ctx)

    # Expedite any eligible open order. This is the timing lever: it moves supply
    # that already exists rather than buying more of it.
    for order in ctx.open_orders:
        quote = ctx.quote_for(order.supplier_id)
        if quote is None or not quote.expedite_available or quote.expedite_days_saved <= 0:
            continue
        current = order.confirmed_date or order.requested_date
        new_date = current - timedelta(days=quote.expedite_days_saved)
        if new_date < ctx.today:
            continue
        out.append(
            Candidate(
                action_type=ActionType.EXPEDITE_PO,
                po_id=order.po_id,
                supplier_id=order.supplier_id,
                new_date=new_date,
                expected_receipt_date=new_date,
                qty=order.outstanding_qty,
                fee_minor=quote.expedite_fee_minor,
                label=(
                    f"Expedite {order.po_id} by {quote.expedite_days_saved} days "
                    f"to {new_date.isoformat()}"
                ),
            )
        )

    # New purchase orders, one per eligible supplier. Three sizes are offered where
    # they differ: the quantity that covers the need, the recommendation under
    # review (so it is always scored rather than assumed), and -- when the full
    # need is unaffordable -- the largest quantity the budget actually permits.
    #
    # That last one matters: without it, a budget ceiling makes the agent look at
    # an all-or-nothing choice and conclude nothing can be done, when buying what
    # is affordable would still prevent most of the shortage. A partial mitigation
    # is a legitimate answer, provided its residual gap is reported honestly.
    for quote in ctx.quotes:
        if not quote.eligible:
            continue
        arrival = ctx.today + timedelta(days=quote.lead_time_days)
        wanted = {round_to_pack(need, quote)}
        if recommended_qty:
            wanted.add(round_to_pack(recommended_qty, quote))

        affordable = affordable_quantity(ctx, quote)
        if affordable > 0:
            wanted.add(affordable)

        for qty in sorted(q for q in wanted if q > 0):
            out.append(
                Candidate(
                    action_type=ActionType.CREATE_PO,
                    supplier_id=quote.supplier_id,
                    qty=qty,
                    expected_receipt_date=arrival,
                    unit_price_minor=quote.unit_price_minor,
                    label=f"Order {qty} units from {quote.supplier_id}, arriving {arrival.isoformat()}",
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #


def _receipts_for(ctx: PlanningContext, candidate: Candidate) -> list[Receipt]:
    """Build the receipt series implied by a candidate.

    The expedite branch *replaces* the existing receipt's date. Appending a new
    receipt instead would silently double the incoming quantity -- the single
    easiest way to make an expedite look better than it is.
    """
    receipts = orders_to_receipts(ctx.open_orders, confirmed_only=True)

    if candidate.action_type == ActionType.EXPEDITE_PO:
        moved: list[Receipt] = []
        for r in receipts:
            if r.po_id == candidate.po_id and candidate.new_date is not None:
                moved.append(Receipt(day=candidate.new_date, qty=r.qty, po_id=r.po_id, confirmed=True))
            else:
                moved.append(r)
        return moved

    if candidate.action_type == ActionType.CREATE_PO and candidate.expected_receipt_date:
        receipts = receipts + [
            Receipt(day=candidate.expected_receipt_date, qty=candidate.qty, po_id="(proposed)", confirmed=True)
        ]
    return receipts


def simulate(ctx: PlanningContext, candidate: Candidate) -> SimulationResult:
    """Evaluate one candidate: projection before, projection after, feasibility.

    This function is the only source of numbers the agent is permitted to quote.
    """
    before = baseline_projection(ctx)
    after = build_projection(
        opening_units=ctx.inventory.usable,
        demand=ctx.demand,
        receipts=_receipts_for(ctx, candidate),
        start=ctx.today,
        horizon_days=ctx.policy.horizon_days,
        safety_stock_units=ctx.policy.safety_stock_units,
        unit_volume_m3=ctx.unit_volume_m3,
        capacity=ctx.capacity,
        demand_override=ctx.demand_override,
    )

    quote = ctx.quote_for(candidate.supplier_id) if candidate.supplier_id else None
    checks: list[ConstraintCheck] = []

    if candidate.action_type == ActionType.KEEP_PLAN:
        # Doing nothing spends nothing and moves nothing; there is no constraint
        # to violate. Its merit is judged purely on the resulting projection.
        checks.append(ConstraintCheck("no_action", True, "Keeping the existing plan."))
    else:
        checks.append(C.check_supplier_eligibility(quote))
        checks.append(C.check_quote_validity(quote, ctx.today))
        checks.append(C.check_budget(candidate, ctx.budget))
        checks.append(C.check_capacity(candidate, after, ctx.capacity, ctx.unit_volume_m3))
        checks.append(C.check_lead_time(candidate, before, ctx.today))
        if candidate.action_type == ActionType.CREATE_PO:
            checks.append(C.check_moq_pack(candidate, quote))
            checks.append(C.check_availability(candidate, quote))
            checks.append(C.check_excess_stock(after, ctx.policy))

    return SimulationResult(
        candidate=candidate,
        before=before,
        after=after,
        checks=checks,
        incremental_cost_minor=candidate.total_cost_minor,
    )


def simulate_all(
    ctx: PlanningContext, recommended_qty: int | None = None
) -> list[SimulationResult]:
    return [simulate(ctx, c) for c in generate_candidates(ctx, recommended_qty)]


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def rank(results: list[SimulationResult]) -> list[SimulationResult]:
    """Order feasible plans by the stated policy, infeasible ones last.

    Ordering: fewest unmet units, then least excess closing stock, then lowest
    incremental cost. Infeasible options are kept rather than dropped so the agent
    can explain *why* the obvious choice was unavailable.
    """
    def key(r: SimulationResult):
        return (
            0 if r.feasible else 1,
            r.after.total_unmet_units,
            r.after.closing_inventory,
            r.incremental_cost_minor,
        )

    return sorted(results, key=key)


def best(results: list[SimulationResult]) -> SimulationResult | None:
    ranked = [r for r in rank(results) if r.feasible]
    return ranked[0] if ranked else None


def simulation_to_dict(r: SimulationResult) -> dict:
    from app.domain.projection import summarize

    return {
        "action_type": r.candidate.action_type.value,
        "label": r.candidate.label,
        "supplier_id": r.candidate.supplier_id,
        "po_id": r.candidate.po_id,
        "qty": r.candidate.qty,
        "expected_receipt_date": (
            r.candidate.expected_receipt_date.isoformat()
            if r.candidate.expected_receipt_date else None
        ),
        "incremental_cost_minor": r.incremental_cost_minor,
        "feasible": r.feasible,
        "binding_constraints": r.binding_constraints,
        "checks": C.checks_to_dicts(r.checks),
        "before": summarize(r.before),
        "after": summarize(r.after),
        "unmet_reduction": r.unmet_reduction,
        "residual_unmet": r.residual_unmet,
    }
