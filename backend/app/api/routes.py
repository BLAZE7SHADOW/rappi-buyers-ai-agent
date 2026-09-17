"""HTTP API for the purchasing workbench.

Failures return typed codes rather than prose, so both the UI and the agent can
decide what to do next from the response alone.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agent.loop import RunConflict, run_case
from app.agent.providers import NoProviderKey
from app.config import get_settings
from app.db import schema as s
from app.db.engine import transaction
from app.db.repo import append_event, load_case, load_events
from app.domain.candidates import baseline_projection, rank, simulate_all, simulation_to_dict
from app.domain.projection import projection_rows, summarize
from app.domain.types import EventKind
from app.services.context import build_context, missing_evidence
from app.services.proposals import (
    ApprovalRequired, StalePlan, approve, decline, validate_and_route,
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
            verdict = conn.execute(
                select(s.case_events)
                .where(s.case_events.c.case_id == r["case_id"],
                       s.case_events.c.kind == "verdict")
                .order_by(s.case_events.c.seq.desc())
            ).mappings().first()
            out.append({
                "case_id": r["case_id"], "fixture_id": r["fixture_id"],
                "sku": r["sku"], "node_id": r["node_id"], "title": r["title"],
                "trigger_type": r["trigger_type"], "recommended_qty": trigger.get("recommended_qty"),
                "state": r["state"], "replan_count": r["replan_count"],
                "next_actor": NEXT_ACTOR.get(r["state"], "agent"),
                "latest_verdict": json.loads(verdict["payload_json"])["verdict"] if verdict else None,
            })
    return {"cases": out}


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

        inv = ctx.inventory
        evidence = {
            "inventory": {
                "on_hand": inv.on_hand, "reserved": inv.reserved,
                "quarantine": inv.quarantine, "damaged": inv.damaged,
                "usable": inv.usable,
                "snapshot_age_days": (ctx.today - inv.effective_at).days,
            },
            "open_orders": [
                {"po_id": o.po_id, "supplier_id": o.supplier_id,
                 "outstanding_qty": o.outstanding_qty,
                 "confirmed_date": o.confirmed_date.isoformat() if o.confirmed_date else None,
                 "status": o.status.value, "overdue": o.is_overdue(ctx.today),
                 "acknowledged": o.is_acknowledged}
                for o in ctx.open_orders
            ],
            "budget": {
                "limit_minor": ctx.budget.limit_minor if ctx.budget else None,
                "committed_minor": ctx.budget.committed_minor if ctx.budget else None,
                "available_minor": ctx.budget.available_minor if ctx.budget else None,
            },
            "capacity": {
                "min_headroom_m3": round(min((c.headroom_m3 for c in ctx.capacity), default=0), 2),
                "unit_volume_m3": ctx.unit_volume_m3,
            },
            "unknowns": missing_evidence(ctx),
        }

    return {
        "case": {
            "case_id": case["case_id"], "fixture_id": case["fixture_id"],
            "sku": case["sku"], "node_id": case["node_id"], "title": case["title"],
            "state": case["state"], "replan_count": case["replan_count"],
            "as_of_date": case["as_of_date"].isoformat(),
            "trigger": {"type": case["trigger_type"], **case["trigger_payload"]},
            "next_actor": NEXT_ACTOR.get(case["state"], "agent"),
            "supplier_behavior": case["supplier_behavior"],
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


@router.post("/cases/{case_id}/run")
def run(case_id: str):
    try:
        return run_case(case_id)
    except NoProviderKey as exc:
        # Never silently downgrade to a non-AI path: a run that could not use the
        # model must not be presented as an agent run.
        _fail(503, "NO_PROVIDER_KEY", str(exc),
              hint="Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in .env and restart.")
    except RunConflict as exc:
        _fail(409, "RUN_IN_PROGRESS", str(exc))
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
    return decline(case_id, proposal_id, body.reason)


@router.post("/proposals/{proposal_id}/execute")
def execute_proposal(proposal_id: str):
    """Execute a proposal already within delegated authority."""
    from app.services.proposals import authorize_and_execute

    with transaction() as conn:
        row = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if row is None:
            _fail(404, "PROPOSAL_NOT_FOUND", f"No proposal {proposal_id}")
        case_id = row["case_id"]
    try:
        return authorize_and_execute(case_id, proposal_id)
    except ApprovalRequired as exc:
        _fail(403, "APPROVAL_REQUIRED", str(exc))
    except StalePlan as exc:
        _fail(409, "STALE_PLAN", str(exc))


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
    }
