"""HTTP API for the purchasing workbench.

Failures return typed codes rather than prose, so both the UI and the agent can
decide what to do next from the response alone.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.agent.loop import InvalidCaseState, RunConflict, run_case
from app.agent.providers import NoProviderKey
from app.config import get_settings
from app.db import schema as s
from app.db.engine import transaction
from app.db.repo import append_event, load_case, load_events
from app.domain.candidates import baseline_projection, rank, simulate_all, simulation_to_dict
from app.domain.projection import projection_rows, summarize
from app.domain.types import EventKind
from app.services.context import build_context, missing_evidence, unconfirmed_signal
from app.services.proposals import (
    ApprovalRequired, InvalidTransition, StalePlan, approve, decline, validate_and_route,
)

router = APIRouter(prefix="/api")


def _fail(status: int, code: str, message: str, **extra):
    raise HTTPException(status_code=status, detail={"error": code, "message": message, **extra})


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #

NEXT_ACTOR = {
    "investigating": "agent",
    "pending_investigation": "agent",
    "reopened": "agent",
    "awaiting_buyer": "buyer",
    "awaiting_approval": "buyer",
    "authorized": "system",
    "executing": "system",
    "awaiting_confirmation": "supplier",
    "validating": "system",
    "resolved": "none",
    "escalated": "human escalation",
}


@router.get("/cases")
def list_cases():
    with transaction() as conn:
        rows = conn.execute(select(s.cases).order_by(s.cases.c.case_id)).mappings().all()
        out = []
        for r in rows:
            trigger = json.loads(r["trigger_payload"])
            case = load_case(conn, r["case_id"])
            projection = baseline_projection(build_context(conn, case))
            verdict = conn.execute(
                select(s.case_events)
                .where(s.case_events.c.case_id == r["case_id"],
                       s.case_events.c.kind == "verdict")
                .order_by(s.case_events.c.seq.desc())
            ).mappings().first()
            latest_run = conn.execute(
                select(s.agent_runs).where(s.agent_runs.c.case_id == r["case_id"])
                .order_by(s.agent_runs.c.started_at.desc())
            ).mappings().first()
            latest_proposal = conn.execute(
                select(s.proposals).where(s.proposals.c.case_id == r["case_id"])
                .order_by(s.proposals.c.version.desc())
            ).mappings().first()
            signal_source = {
                "buyer": "Buyer-created",
                "replenishment_system": "Replenishment system",
                "demand_monitor": "Demand monitor",
                "supplier_update": "Supplier update",
                "operational_system": "Operational system",
            }.get(r["signal_source"], r["signal_source"])
            out.append({
                "case_id": r["case_id"], "fixture_id": r["fixture_id"],
                "sku": r["sku"], "node_id": r["node_id"], "title": r["title"],
                "trigger_type": r["trigger_type"], "recommended_qty": trigger.get("recommended_qty"),
                "signal_source": signal_source,
                "data_as_of": r["as_of_date"].isoformat(),
                "last_activity_at": r["updated_at"].isoformat(),
                "state": r["state"], "replan_count": r["replan_count"],
                "next_actor": NEXT_ACTOR.get(r["state"], "agent"),
                "latest_verdict": json.loads(verdict["payload_json"])["verdict"] if verdict else None,
                "latest_run_mode": latest_run["mode"] if latest_run else None,
                "projected_unmet_units": projection.total_unmet_units,
                "first_stockout_date": (
                    projection.first_stockout_date.isoformat()
                    if projection.first_stockout_date else None
                ),
                "latest_disposition": latest_proposal["disposition"] if latest_proposal else None,
                "latest_action_type": latest_proposal["action_type"] if latest_proposal else None,
            })
    return {"cases": out}


@router.get("/catalog/case-options")
def case_options():
    """SKU/node combinations backed by enough operational data to open a case."""
    with transaction() as conn:
        rows = conn.execute(
            select(
                s.inventory_snapshots.c.sku,
                s.inventory_snapshots.c.node_id,
                s.inventory_snapshots.c.effective_at,
                s.products.c.name.label("product_name"),
                s.nodes.c.name.label("node_name"),
            )
            .join(s.products, s.products.c.sku == s.inventory_snapshots.c.sku)
            .join(s.nodes, s.nodes.c.node_id == s.inventory_snapshots.c.node_id)
            .order_by(s.products.c.name)
        ).mappings().all()
        options = []
        for row in rows:
            reference_case = conn.execute(
                select(s.cases).where(
                    s.cases.c.sku == row["sku"],
                    s.cases.c.node_id == row["node_id"],
                ).order_by(s.cases.c.case_id)
            ).mappings().first()
            if reference_case is None:
                continue
            ctx = build_context(conn, load_case(conn, reference_case["case_id"]))
            projection = baseline_projection(ctx)
            options.append({
                "sku": row["sku"], "node_id": row["node_id"],
                "product_name": row["product_name"], "node_name": row["node_name"],
                "as_of_date": row["effective_at"].isoformat(),
                "usable_inventory": ctx.inventory.usable,
                "forecast_units": sum(d.forecast_units for d in ctx.demand),
                "available_budget_minor": ctx.budget.available_minor if ctx.budget else None,
                "storage_headroom_m3": round(
                    min((c.headroom_m3 for c in ctx.capacity), default=0), 2
                ),
                "eligible_suppliers": sum(1 for q in ctx.quotes if q.eligible),
                "projected_unmet_units": projection.total_unmet_units,
            })
    return {"options": options}


class CreateCaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    node_id: str
    recommended_qty: int
    reason: str


@router.post("/cases", status_code=201)
def create_case(body: CreateCaseIn):
    if body.recommended_qty <= 0:
        _fail(400, "INVALID_QUANTITY", "Recommended quantity must be greater than zero.")
    reason = body.reason.strip()
    if not reason:
        _fail(400, "MISSING_REASON", "Explain why this purchasing case was opened.")

    with transaction() as conn:
        inventory = conn.execute(
            select(s.inventory_snapshots).where(
                s.inventory_snapshots.c.sku == body.sku,
                s.inventory_snapshots.c.node_id == body.node_id,
            )
        ).mappings().first()
        product = conn.execute(
            select(s.products).where(s.products.c.sku == body.sku)
        ).mappings().first()
        if inventory is None or product is None:
            _fail(400, "UNKNOWN_SKU_NODE", "No operational data exists for this SKU and node.")

        case_id = f"CASE-USER-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(s.cases.insert().values(
            case_id=case_id,
            fixture_id=None,
            sku=body.sku,
            node_id=body.node_id,
            trigger_type="buyer_recommendation",
            signal_source="buyer",
            trigger_payload=json.dumps({
                "recommended_qty": body.recommended_qty,
                "reason": reason,
                "source": "buyer_created",
            }),
            title=f"{product['name']} @ {body.node_id}: review {body.recommended_qty} units",
            state="investigating",
            replan_count=0,
            as_of_date=inventory["effective_at"],
            supplier_behavior="confirm_full",
        ))
        append_event(
            conn, case_id, EventKind.STATE, "Buyer opened purchasing case",
            {"recommended_qty": body.recommended_qty, "reason": reason},
        )
    return {"case_id": case_id, "state": "investigating"}


@router.get("/cases/{case_id}")
def get_case(case_id: str):
    with transaction() as conn:
        case = load_case(conn, case_id)
        if case is None:
            _fail(404, "CASE_NOT_FOUND", f"No case {case_id}")

        ctx = build_context(conn, case)
        before = baseline_projection(ctx)
        ranked = rank(simulate_all(ctx, recommended_qty=case["trigger_payload"].get("recommended_qty")))

        proposals = conn.execute(
            select(s.proposals).where(s.proposals.c.case_id == case_id)
            .order_by(s.proposals.c.version)
        ).mappings().all()
        interactions = conn.execute(
            select(s.interactions).where(s.interactions.c.case_id == case_id)
        ).mappings().all()
        actions = conn.execute(
            select(s.actions).where(s.actions.c.case_id == case_id)
        ).mappings().all()
        events = load_events(conn, case_id)
        latest_run = conn.execute(
            select(s.agent_runs).where(s.agent_runs.c.case_id == case_id)
            .order_by(s.agent_runs.c.started_at.desc())
        ).mappings().first()

        inv = ctx.inventory
        product = conn.execute(
            select(s.products).where(s.products.c.sku == case["sku"])
        ).mappings().first()
        evidence = {
            "product": {
                "sku": case["sku"], "name": product["name"] if product else case["sku"],
                "node_id": case["node_id"],
            },
            "inventory": {
                "on_hand": inv.on_hand, "reserved": inv.reserved,
                "quarantine": inv.quarantine, "damaged": inv.damaged,
                "usable": inv.usable,
                "snapshot_age_days": (ctx.today - inv.effective_at).days,
                "effective_at": inv.effective_at.isoformat(),
            },
            "demand": {
                "horizon_days": ctx.policy.horizon_days,
                "forecast_total_units": sum(d.forecast_units for d in ctx.demand),
                "average_daily_units": round(
                    sum(d.forecast_units for d in ctx.demand) / len(ctx.demand), 1
                ) if ctx.demand else 0,
                "safety_stock_units": ctx.policy.safety_stock_units,
            },
            "open_orders": [
                {"po_id": o.po_id, "supplier_id": o.supplier_id,
                 "requested_qty": o.requested_qty, "confirmed_qty": o.confirmed_qty,
                 "received_qty": o.received_qty, "cancelled_qty": o.cancelled_qty,
                 "outstanding_qty": o.outstanding_qty,
                 "requested_date": o.requested_date.isoformat(),
                 "confirmed_date": o.confirmed_date.isoformat() if o.confirmed_date else None,
                 "status": o.status.value, "overdue": o.is_overdue(ctx.today),
                 "acknowledged": o.is_acknowledged}
                for o in ctx.open_orders
            ],
            "budget": {
                "limit_minor": ctx.budget.limit_minor if ctx.budget else None,
                "committed_minor": ctx.budget.committed_minor if ctx.budget else None,
                "reserved_minor": ctx.budget.reserved_minor if ctx.budget else None,
                "available_minor": ctx.budget.available_minor if ctx.budget else None,
            },
            "capacity": {
                "min_headroom_m3": round(min((c.headroom_m3 for c in ctx.capacity), default=0), 2),
                "unit_volume_m3": ctx.unit_volume_m3,
            },
            "suppliers": [
                {
                    "supplier_id": q.supplier_id,
                    "unit_price_minor": q.unit_price_minor,
                    "moq": q.moq,
                    "pack_size": q.pack_size,
                    "lead_time_days": q.lead_time_days,
                    "available_units": q.available_units,
                    "quote_expires_at": q.quote_expires_at.isoformat(),
                    "eligible": q.eligible,
                    "expedite_available": q.expedite_available,
                    "expedite_fee_minor": q.expedite_fee_minor,
                    "expedite_days_saved": q.expedite_days_saved,
                }
                for q in ctx.quotes
            ],
            "unknowns": missing_evidence(ctx),
            "unconfirmed_input": (
                unconfirmed_signal(case, ctx).to_dict()
                if unconfirmed_signal(case, ctx) else None
            ),
        }

    return {
        "case": {
            "case_id": case["case_id"], "fixture_id": case["fixture_id"],
            "sku": case["sku"], "node_id": case["node_id"], "title": case["title"],
            "signal_source": {
                "buyer": "Buyer-created",
                "replenishment_system": "Replenishment system",
                "demand_monitor": "Demand monitor",
                "supplier_update": "Supplier update",
                "operational_system": "Operational system",
            }.get(case["signal_source"], case["signal_source"]),
            "state": case["state"], "replan_count": case["replan_count"],
            "as_of_date": case["as_of_date"].isoformat(),
            "trigger": {"type": case["trigger_type"], **case["trigger_payload"]},
            "next_actor": NEXT_ACTOR.get(case["state"], "agent"),
            "supplier_behavior": case["supplier_behavior"],
            "latest_run_mode": latest_run["mode"] if latest_run else None,
        },
        "evidence": evidence,
        "projection": {"summary": summarize(before), "daily": projection_rows(before)},
        "candidates": [simulation_to_dict(r) for r in ranked],
        "proposals": [
            {"proposal_id": p["proposal_id"], "version": p["version"],
             "disposition": p["disposition"], "action_type": p["action_type"],
             "action_args": json.loads(p["action_args_json"]),
             "rationale": p["rationale"],
             "important_factors": json.loads(p["important_factors_json"]),
             "assumptions": json.loads(p["assumptions_json"]),
             "residual_exposure": json.loads(p["residual_exposure_json"]),
             "simulation": json.loads(p["simulation_json"]),
             "approval_required": bool(p["approval_required"]),
             "approval_reason": p["approval_reason"], "state": p["state"],
             "decline_reason": p["decline_reason"]}
            for p in proposals
        ],
        "interactions": [
            {"interaction_id": i["interaction_id"], "kind": i["kind"],
             "question": i["question"], "options": json.loads(i["options_json"]),
             "recommendation": i["recommendation"], "answer": i["answer"]}
            for i in interactions
        ],
        "actions": [
            {"action_id": a["action_id"], "action_type": a["action_type"],
             "state": a["state"], "po_id": a["po_id"],
             "idempotency_key": a["idempotency_key"], "attempts": a["attempts"],
             "request": json.loads(a["request_json"]),
             "response": json.loads(a["response_json"]) if a["response_json"] else None,
             "verdict": json.loads(a["verdict_json"]) if a["verdict_json"] else None}
            for a in actions
        ],
        "events": events,
    }


class RunIn(BaseModel):
    mode: str = "live"


@router.post("/cases/{case_id}/run")
def run(case_id: str, body: RunIn | None = None):
    mode = (body or RunIn()).mode
    if mode not in ("live", "replay"):
        _fail(400, "INVALID_RUN_MODE", "Run mode must be 'live' or 'replay'.")
    try:
        if mode == "replay":
            from evals.replay import ReplayProvider, has_recording, recording_path

            with transaction() as conn:
                case = load_case(conn, case_id)
                if case is None:
                    _fail(404, "CASE_NOT_FOUND", f"No case {case_id}")
                fixture_id = case.get("fixture_id")
            if not fixture_id or not has_recording(fixture_id):
                _fail(404, "REPLAY_NOT_AVAILABLE", "No recorded run exists for this case.")
            provider = ReplayProvider(recording_path(fixture_id), segment=case["replan_count"])
            return run_case(case_id, provider=provider)
        return run_case(case_id)
    except NoProviderKey as exc:
        # Never silently downgrade to a non-AI path: a run that could not use the
        # model must not be presented as an agent run.
        _fail(503, "NO_PROVIDER_KEY", str(exc),
              hint="Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in .env and restart.")
    except RunConflict as exc:
        _fail(409, "RUN_IN_PROGRESS", str(exc))
    except InvalidCaseState as exc:
        _fail(409, "INVALID_CASE_STATE", str(exc))
    except HTTPException:
        # Preserve typed 404s raised by replay lookup instead of wrapping them
        # as a generic agent failure in the catch-all below.
        raise
    except Exception as exc:
        _fail(500, "AGENT_RUN_FAILED", str(exc))


class MessageIn(BaseModel):
    text: str


@router.post("/cases/{case_id}/messages")
def post_message(case_id: str, body: MessageIn):
    with transaction() as conn:
        if load_case(conn, case_id) is None:
            _fail(404, "CASE_NOT_FOUND", f"No case {case_id}")
        append_event(conn, case_id, EventKind.ANSWER, "Buyer note", {"text": body.text})
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Buyer decisions
# --------------------------------------------------------------------------- #


class AnswerIn(BaseModel):
    answer: str


@router.post("/interactions/{interaction_id}/respond")
def respond(interaction_id: str, body: AnswerIn):
    from datetime import datetime

    with transaction() as conn:
        row = conn.execute(
            select(s.interactions).where(s.interactions.c.interaction_id == interaction_id)
        ).mappings().first()
        if row is None:
            _fail(404, "INTERACTION_NOT_FOUND", f"No interaction {interaction_id}")
        conn.execute(s.interactions.update()
                     .where(s.interactions.c.interaction_id == interaction_id)
                     .values(answer=body.answer, answered_at=datetime.utcnow()))
        append_event(conn, row["case_id"], EventKind.ANSWER, "Buyer answered",
                     {"interaction_id": interaction_id, "question": row["question"],
                      "answer": body.answer})
        from app.db.repo import set_case_state
        set_case_state(conn, row["case_id"], "investigating")
    return {"ok": True, "case_id": row["case_id"]}


class ApproveIn(BaseModel):
    approver: str = "buyer"


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, body: ApproveIn):
    with transaction() as conn:
        row = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if row is None:
            _fail(404, "PROPOSAL_NOT_FOUND", f"No proposal {proposal_id}")
        case_id = row["case_id"]
    try:
        return approve(case_id, proposal_id, body.approver)
    except StalePlan as exc:
        _fail(409, "STALE_PLAN", str(exc))
    except ApprovalRequired as exc:
        _fail(403, "APPROVAL_REQUIRED", str(exc))
    except InvalidTransition as exc:
        _fail(409, "INVALID_PROPOSAL_STATE", str(exc))


class DeclineIn(BaseModel):
    reason: str = ""


@router.post("/proposals/{proposal_id}/decline")
def decline_proposal(proposal_id: str, body: DeclineIn):
    with transaction() as conn:
        row = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if row is None:
            _fail(404, "PROPOSAL_NOT_FOUND", f"No proposal {proposal_id}")
        case_id = row["case_id"]
    try:
        return decline(case_id, proposal_id, body.reason)
    except InvalidTransition as exc:
        _fail(409, "INVALID_PROPOSAL_STATE", str(exc))


# --------------------------------------------------------------------------- #
# Demo controls (clearly labelled simulation)
# --------------------------------------------------------------------------- #


class DemoEventIn(BaseModel):
    case_id: str
    behavior: str


@router.post("/demo/events")
def inject_event(body: DemoEventIn):
    """Set how the supplier will respond to this case's next action."""
    from app.integrations.mock_supplier import BEHAVIORS

    if body.behavior not in BEHAVIORS:
        _fail(400, "UNKNOWN_BEHAVIOR",
              f"'{body.behavior}' is not a supported supplier behaviour.",
              supported=list(BEHAVIORS))
    with transaction() as conn:
        conn.execute(s.cases.update().where(s.cases.c.case_id == body.case_id)
                     .values(supplier_behavior=body.behavior))
        append_event(conn, body.case_id, EventKind.STATE,
                     f"[simulation] Supplier behaviour set to {body.behavior}",
                     {"behavior": body.behavior, "simulated": True})
    return {"ok": True, "behavior": body.behavior}


@router.post("/demo/reset")
def reset_demo():
    from app.db.seed import seed_all

    seed_all(reset=True)
    return {"ok": True, "note": "Demo data reset and reseeded."}


@router.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
        "llm_key_present": settings.has_llm_key,
        "live_agent_available": settings.has_llm_key,
        "replay_available": True,
    }
