"""The agent's tool surface.

Nine tools, deliberately. Six read evidence, one computes, two write to the case.
There is no tool that executes a purchase: execution happens server-side once a
proposal is authorised, so the agent physically cannot authorise its own spending.

Every tool returns JSON-safe structured data. Arguments are schema-validated, and
results carry enough context for the agent to choose a next step from a failure
rather than guessing.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from app.db.engine import transaction
from app.db.repo import (
    append_event, load_case, load_promotions, load_sales_history,
)
from app.domain import demand as demand_mod
from app.domain.candidates import (
    baseline_projection, rank, required_quantity, simulate, simulate_all,
    simulation_to_dict,
)
from app.domain.projection import projection_rows, summarize
from app.domain.types import EventKind
from app.services.context import build_context, missing_evidence, unconfirmed_signal
from app.services.proposals import _resolve_candidate, create_proposal


class ToolError(Exception):
    """A typed failure the agent is expected to read and act on."""

    def __init__(self, code: str, message: str, **context):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, **self.context}


def _money(minor: int) -> str:
    return f"${minor / 100:,.2f}"


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #


def get_case_context(case_id: str, args: dict) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        if case is None:
            raise ToolError("CASE_NOT_FOUND", f"No case {case_id}")
        ctx = build_context(conn, case)
        sensitivity = unconfirmed_signal(case, ctx)
        from sqlalchemy import select
        from app.db import schema as s
        priors = conn.execute(
            select(s.proposals).where(s.proposals.c.case_id == case_id)
        ).mappings().all()
        answers = conn.execute(
            select(s.interactions).where(s.interactions.c.case_id == case_id)
        ).mappings().all()

    return {
        "case_id": case_id,
        "sku": case["sku"],
        "node_id": case["node_id"],
        "today": case["as_of_date"].isoformat(),
        "trigger": {"type": case["trigger_type"], **case["trigger_payload"]},
        "state": case["state"],
        "replan_count": case["replan_count"],
        "policy": {
            "planning_horizon_days": ctx.policy.horizon_days,
            "safety_stock_units": ctx.policy.safety_stock_units,
            "max_days_cover": ctx.policy.max_days_cover,
            "autonomy_spend_limit": _money(ctx.policy.autonomy_spend_limit_minor),
            "autonomy_expedite_fee_limit": _money(ctx.policy.autonomy_fee_limit_minor),
        },
        "prior_proposals": [
            {"proposal_id": p["proposal_id"], "version": p["version"],
             "disposition": p["disposition"], "action_type": p["action_type"],
             "state": p["state"], "approval_reason": p["approval_reason"]}
            for p in priors
        ],
        "buyer_answers": [
            {"question": a["question"], "answer": a["answer"]}
            for a in answers if a["answer"]
        ],
        "known_unknowns": missing_evidence(ctx),
        # Stated as data, with both worlds already costed, so this is a fact to
        # act on rather than a hint buried in the trigger prose. Policy already
        # routes a material one to the buyer; asking earlier yourself is better.
        "unconfirmed_input": sensitivity.to_dict() if sensitivity else None,
    }


def get_inventory(case_id: str, args: dict) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)
    inv = ctx.inventory
    return {
        "sku": inv.sku, "node_id": inv.node_id,
        "on_hand": inv.on_hand, "reserved": inv.reserved,
        "quarantine": inv.quarantine, "damaged": inv.damaged,
        "usable": inv.usable,
        "effective_at": inv.effective_at.isoformat(),
        "snapshot_age_days": (ctx.today - inv.effective_at).days,
        "note": ("Usable stock excludes reserved, quarantined and damaged units. "
                 "Only usable stock can serve future demand."),
    }


def get_demand_evidence(case_id: str, args: dict) -> dict:
    lookback = int(args.get("lookback_days") or 14)
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)
        history = load_sales_history(conn, case["sku"], case["node_id"], ctx.today, lookback)
        promos = load_promotions(conn, case["sku"])

    analysis = demand_mod.analyze(history=history, forecast=ctx.demand,
                                  promotions=promos, today=ctx.today, policy=ctx.policy)
    return {
        "forecast_horizon_days": ctx.policy.horizon_days,
        "forecast_total_units": sum(d.forecast_units for d in ctx.demand),
        "recent_sales": [
            {"day": d.day.isoformat(), "sales": d.actual_sales_units,
             "in_stock_pct": d.in_stock_pct, "censored": d.is_censored}
            for d in history
        ],
        "promotions": [
            {"promotion_id": p.promotion_id, "label": p.label,
             "start_date": p.start_date.isoformat(), "end_date": p.end_date.isoformat(),
             "uplift_factor": p.uplift_factor}
            for p in promos
        ],
        **analysis,
        "guidance": ("Stockout-censored days measure availability, not demand. A "
                     "promotional uplift ends when the promotion ends; do not "
                     "extrapolate it across the whole horizon."),
    }


def get_open_orders(case_id: str, args: dict) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)
    orders = []
    for o in ctx.open_orders:
        orders.append({
            "po_id": o.po_id, "supplier_id": o.supplier_id,
            "requested_qty": o.requested_qty, "confirmed_qty": o.confirmed_qty,
            "received_qty": o.received_qty, "cancelled_qty": o.cancelled_qty,
            "outstanding_qty": o.outstanding_qty,
            "requested_date": o.requested_date.isoformat(),
            "confirmed_date": o.confirmed_date.isoformat() if o.confirmed_date else None,
            "status": o.status.value,
            "acknowledged": o.is_acknowledged,
            "overdue": o.is_overdue(ctx.today),
            "counts_as_confirmed_supply": o.is_acknowledged,
        })
    return {
        "open_orders": orders,
        "total_outstanding_units": sum(o["outstanding_qty"] for o in orders),
        "note": ("Only acknowledged orders with a confirmed date count as supply in "
                 "the baseline projection. An overdue or unacknowledged order is "
                 "uncertainty, not incoming stock."),
    }


def get_supplier_options(case_id: str, args: dict) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)

    options = []
    for q in ctx.quotes:
        arrival = ctx.today + timedelta(days=q.lead_time_days)
        options.append({
            "supplier_id": q.supplier_id,
            "eligible": q.eligible,
            "unit_price": _money(q.unit_price_minor),
            "unit_price_minor": q.unit_price_minor,
            "moq": q.moq, "pack_size": q.pack_size,
            "lead_time_days": q.lead_time_days,
            "earliest_arrival": arrival.isoformat(),
            "available_units": q.available_units,
            "quote_expires_at": q.quote_expires_at.isoformat(),
            "quote_expired": q.is_expired(ctx.today),
            "expedite_available": q.expedite_available,
            "expedite_fee": _money(q.expedite_fee_minor) if q.expedite_available else None,
            "expedite_fee_minor": q.expedite_fee_minor,
            "expedite_days_saved": q.expedite_days_saved,
        })

    expeditable = [
        {"po_id": o.po_id, "supplier_id": o.supplier_id,
         "current_date": (o.confirmed_date or o.requested_date).isoformat(),
         "outstanding_qty": o.outstanding_qty}
        for o in ctx.open_orders
        if (ctx.quote_for(o.supplier_id) or None) and ctx.quote_for(o.supplier_id).expedite_available
    ]
    return {"supplier_options": options, "expeditable_orders": expeditable}


def get_constraints(case_id: str, args: dict) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)

    budget = ctx.budget
    headroom = min((c.headroom_m3 for c in ctx.capacity), default=0.0)
    max_units = int(headroom / ctx.unit_volume_m3) if ctx.unit_volume_m3 else None
    return {
        "budget": {
            "limit": _money(budget.limit_minor) if budget else None,
            "committed": _money(budget.committed_minor) if budget else None,
            "available": _money(budget.available_minor) if budget else None,
            "available_minor": budget.available_minor if budget else None,
        } if budget else {"error": "No budget record found"},
        "capacity": {
            "min_headroom_m3": round(headroom, 2),
            "unit_volume_m3": ctx.unit_volume_m3,
            "max_units_that_fit": max_units,
        },
        "autonomy_limits": {
            "spend": _money(ctx.policy.autonomy_spend_limit_minor),
            "expedite_fee": _money(ctx.policy.autonomy_fee_limit_minor),
            "note": "Actions above these limits need buyer approval, but are not blocked.",
        },
        "hard_constraints_note": ("Budget and capacity cannot be waived by buyer "
                                  "approval. They require new budget or new space."),
    }


# --------------------------------------------------------------------------- #
# Compute tool
# --------------------------------------------------------------------------- #


def simulate_plan(case_id: str, args: dict) -> dict:
    """Score one candidate, or every candidate, against current state.

    This is the only source of numbers. Any quantity, cost, date or shortage the
    agent states in a proposal must come from here.
    """
    with transaction() as conn:
        case = load_case(conn, case_id)
        ctx = build_context(conn, case)

        recommended = case["trigger_payload"].get("recommended_qty")
        action_type = args.get("action_type")

        before = baseline_projection(ctx)
        payload = {
            "baseline": summarize(before),
            "baseline_daily": projection_rows(before),
            "units_needed_to_close_gap": required_quantity(ctx),
        }

        if action_type:
            candidate = _resolve_candidate(ctx, action_type, args)
            result = simulate(ctx, candidate)
            payload["candidate"] = simulation_to_dict(result)
        else:
            ranked = rank(simulate_all(ctx, recommended_qty=recommended))
            payload["all_candidates"] = [simulation_to_dict(r) for r in ranked]
            payload["note"] = ("Candidates are ordered by unmet demand, then excess "
                               "stock, then cost. Infeasible options are retained so "
                               "the blocking constraint can be explained.")
    return payload


# --------------------------------------------------------------------------- #
# Case-write tools
# --------------------------------------------------------------------------- #


def propose_plan(case_id: str, args: dict) -> dict:
    """Persist an evidence-backed proposal.

    Whether the plan needs buyer approval is decided by the server gate from the
    simulation, not by anything stated here.
    """
    required = ("disposition", "action_type", "rationale")
    for field in required:
        if not args.get(field):
            raise ToolError("MISSING_FIELD", f"propose_plan requires '{field}'.")

    with transaction() as conn:
        case = load_case(conn, case_id)
        try:
            result = create_proposal(
                conn, case,
                disposition=args["disposition"],
                action_type=args["action_type"],
                action_args=args.get("action_args") or {},
                rationale=args["rationale"],
                important_factors=args.get("important_factors") or [],
                assumptions=args.get("assumptions") or [],
                evidence_refs=args.get("evidence_refs") or [],
            )
        except Exception as exc:
            raise ToolError("PROPOSAL_REJECTED", str(exc))

    if result["blocked"]:
        return {
            "error": "HARD_CONSTRAINT",
            "message": result["gate"]["reason"],
            **result,
        }

    # The gate, not the model, grants delegated authority. Once granted, the
    # server completes execution and validation as part of the same workflow.
    if not result["approval_required"]:
        from app.services.proposals import authorize_and_execute

        result["execution"] = authorize_and_execute(case_id, result["proposal_id"])
    return result


def ask_buyer(case_id: str, args: dict) -> dict:
    """Ask the buyer for context or a judgement call, and pause the run.

    Only for things tools cannot answer: business context, or a genuine tradeoff.
    Retrieving a fact the system already holds is the agent's job, not the buyer's.
    """
    if not args.get("question"):
        raise ToolError("MISSING_FIELD", "ask_buyer requires 'question'.")

    from app.services.interactions import open_question

    with transaction() as conn:
        interaction_id = open_question(
            conn, case_id,
            question=args["question"],
            kind=args.get("kind", "clarification"),
            options=args.get("options") or [],
            context=args.get("context") or {},
            recommendation=args.get("recommendation", ""),
            raised_by="agent",
        )

    return {"interaction_id": interaction_id, "state": "awaiting_buyer",
            "note": "The run pauses here until the buyer answers."}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

HANDLERS = {
    "get_case_context": get_case_context,
    "get_inventory": get_inventory,
    "get_demand_evidence": get_demand_evidence,
    "get_open_orders": get_open_orders,
    "get_supplier_options": get_supplier_options,
    "get_constraints": get_constraints,
    "simulate_plan": simulate_plan,
    "propose_plan": propose_plan,
    "ask_buyer": ask_buyer,
}

TERMINAL_TOOLS = {"propose_plan", "ask_buyer"}
