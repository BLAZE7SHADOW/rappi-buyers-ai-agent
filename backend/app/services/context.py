"""Assemble a PlanningContext from persisted state.

One place builds the evidence bundle, so the agent's tools, the simulator and the
validator all reason over exactly the same view of the world. If they diverged,
the validator could "confirm" a plan the simulator never actually evaluated.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db import repo
from app.domain.candidates import PlanningContext
from app.domain.types import PolicyConfig


def policy_from_settings() -> PolicyConfig:
    settings = get_settings()
    return PolicyConfig(
        autonomy_spend_limit_minor=settings.autonomy_spend_limit_minor,
        autonomy_fee_limit_minor=settings.autonomy_fee_limit_minor,
        max_tool_calls=settings.max_tool_calls,
        max_replans=settings.max_replans,
    )


def build_context(
    conn: Connection,
    case: dict,
    *,
    policy: PolicyConfig | None = None,
    demand_override: dict[date, int] | None = None,
) -> PlanningContext:
    policy = policy or policy_from_settings()
    sku, node_id, today = case["sku"], case["node_id"], case["as_of_date"]

    product = repo.load_product(conn, sku) or {}
    inventory = repo.load_inventory(conn, sku, node_id)
    if inventory is None:
        raise ValueError(f"No inventory snapshot for {sku} at {node_id}")

    return PlanningContext(
        sku=sku,
        node_id=node_id,
        today=today,
        inventory=inventory,
        demand=repo.load_demand(conn, sku, node_id, today, policy.horizon_days),
        open_orders=repo.load_open_orders(conn, sku, node_id),
        quotes=repo.load_quotes(conn, sku),
        budget=repo.load_budget(conn, node_id, today.strftime("%Y-%m")),
        capacity=repo.load_capacity(conn, node_id, today, policy.horizon_days),
        unit_volume_m3=product.get("unit_volume_m3", 0.0) or 0.0,
        policy=policy,
        demand_override=demand_override,
    )


def unconfirmed_signal(case: dict, ctx: PlanningContext):
    """Does this case rest on something asserted but not recorded anywhere?

    Returns a ``SensitivityResult`` when the case carries an unconfirmed signal,
    so callers can see both worlds even when the difference turns out to be
    immaterial. ``None`` when there is nothing to weigh.
    """
    from app.domain.sensitivity import UnverifiedSignal, evaluate

    payload = case.get("trigger_payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    return evaluate(ctx, UnverifiedSignal.from_payload(payload.get("unverified_demand_signal")))


def missing_evidence(ctx: PlanningContext) -> list[str]:
    """Decision-critical unknowns.

    Missing data is not zero. Anything listed here blocks automatic execution and
    should send the agent to a tool or to the buyer rather than to an assumption.
    """
    gaps: list[str] = []
    if ctx.inventory is None:
        gaps.append("inventory snapshot")
    if not ctx.demand:
        gaps.append("demand forecast for the planning horizon")
    if ctx.budget is None:
        gaps.append("budget record")
    for order in ctx.open_orders:
        if not order.is_acknowledged:
            gaps.append(
                f"supplier acknowledgement and confirmed delivery date for {order.po_id}"
            )
        elif order.is_overdue(ctx.today):
            gaps.append(f"updated delivery date for overdue order {order.po_id}")
    return gaps
