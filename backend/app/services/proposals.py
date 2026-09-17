"""Proposal lifecycle: create, authorise, execute, validate.

This is the pipeline the whole system exists to run. The agent can reach only the
first step; everything after it is server-side. That is the structural reason the
agent cannot authorise its own spending.

    propose  ->  gate  ->  [buyer approval]  ->  execute  ->  validate  ->  resolve | reopen
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db import schema as s
from app.db.engine import transaction
from app.db.repo import append_event, load_case, set_case_state
from app.domain.candidates import simulate, simulation_to_dict
from app.domain.types import ActionType, Candidate, EventKind, Verdict
from app.services import gate as gate_mod
from app.services.interactions import open_question
from app.services import validator as validator_mod
from app.services.context import build_context, missing_evidence, unconfirmed_signal
from app.services.executor import ActionOutcomeUnknown, execute


class StalePlan(Exception):
    """State changed materially since the proposal was simulated."""


class ApprovalRequired(Exception):
    """Execution attempted without the approval the gate demanded."""


class InvalidTransition(Exception):
    """A proposal or case action is not valid from its current state."""


def candidate_from_args(action_type: str, args: dict) -> Candidate:
    def as_date(v):
        return date.fromisoformat(v) if isinstance(v, str) and v else None

    return Candidate(
        action_type=ActionType(action_type),
        supplier_id=args.get("supplier_id"),
        qty=int(args.get("qty") or 0),
        expected_receipt_date=as_date(args.get("expected_receipt_date")),
        po_id=args.get("po_id"),
        new_date=as_date(args.get("new_date")),
        unit_price_minor=int(args.get("unit_price_minor") or 0),
        fee_minor=int(args.get("fee_minor") or 0),
        label=args.get("label", ""),
    )


def _resolve_candidate(ctx, action_type: str, args: dict) -> Candidate:
    """Turn the agent's arguments into a candidate grounded in system-of-record data.

    Two facts are deliberately taken from our records rather than from the model:

    * **Unit price** comes from the live quote, so a hallucinated price cannot
      reach a purchase order.
    * **Expedite quantity** comes from the existing order's outstanding units. An
      expedite moves supply that already exists; letting the model state that
      quantity would allow it to silently resize a supplier obligation.
    """
    candidate = candidate_from_args(action_type, args)

    if candidate.action_type is ActionType.CREATE_PO and candidate.supplier_id:
        quote = ctx.quote_for(candidate.supplier_id)
        if quote:
            candidate = Candidate(
                **{**candidate.__dict__, "unit_price_minor": quote.unit_price_minor}
            )

    elif candidate.action_type is ActionType.EXPEDITE_PO and candidate.po_id:
        order = ctx.order_for(candidate.po_id)
        if order is None:
            raise StalePlan(
                f"Purchase order {candidate.po_id} is no longer open; it cannot be expedited."
            )
        quote = ctx.quote_for(order.supplier_id)
        candidate = Candidate(**{
            **candidate.__dict__,
            "qty": order.outstanding_qty,
            "supplier_id": order.supplier_id,
            "fee_minor": quote.expedite_fee_minor if quote else candidate.fee_minor,
            "expected_receipt_date": candidate.new_date or candidate.expected_receipt_date,
        })

    return candidate


def create_proposal(
    conn: Connection,
    case: dict,
    *,
    disposition: str,
    action_type: str,
    action_args: dict,
    rationale: str,
    important_factors: list[str],
    assumptions: list[str],
    evidence_refs: list[str],
) -> dict:
    """Persist a proposal and let the gate decide who may authorise it.

    ``approval_required`` is computed here, server-side, from the simulation. A
    model claiming its plan is pre-approved has no effect.
    """
    ctx = build_context(conn, case)
    candidate = _resolve_candidate(ctx, action_type, action_args)

    simulation = simulate(ctx, candidate)
    gaps = missing_evidence(ctx)
    sensitivity = unconfirmed_signal(case, ctx)
    decision = gate_mod.evaluate(simulation, missing_evidence=gaps, sensitivity=sensitivity)

    proposal_id = f"PROP-{uuid.uuid4().hex[:8].upper()}"
    prior = conn.execute(
        select(s.proposals).where(s.proposals.c.case_id == case["case_id"])
    ).mappings().all()
    version = len(prior) + 1

    # A replan replaces any proposal that was still waiting for a decision.
    conn.execute(
        s.proposals.update()
        .where(
            s.proposals.c.case_id == case["case_id"],
            s.proposals.c.state.in_(["proposed", "approved"]),
        )
        .values(state="superseded")
    )

    sim_dict = simulation_to_dict(simulation)
    residual = {
        "unmet_units": simulation.residual_unmet,
        "note": (
            "This action does not close the whole gap; the remainder stays exposed."
            if simulation.residual_unmet > 0 else "No residual shortage projected."
        ),
    }

    conn.execute(s.proposals.insert().values(
        proposal_id=proposal_id, case_id=case["case_id"], version=version,
        disposition=disposition, action_type=action_type,
        action_args_json=json.dumps(action_args, default=str),
        evidence_refs_json=json.dumps(evidence_refs),
        simulation_json=json.dumps(sim_dict, default=str),
        rationale=rationale,
        important_factors_json=json.dumps(important_factors),
        assumptions_json=json.dumps(assumptions),
        residual_exposure_json=json.dumps(residual),
        approval_required=decision.approval_required or decision.blocked,
        approval_reason=decision.reason,
        state="blocked" if decision.blocked else "proposed",
    ))

    append_event(conn, case["case_id"], EventKind.PROPOSAL,
                 f"Proposal {proposal_id}: {disposition} / {action_type}",
                 {"proposal_id": proposal_id, "version": version,
                  "disposition": disposition, "action_type": action_type,
                  "gate": decision.to_dict(), "simulation": sim_dict,
                  "missing_evidence": gaps,
                  "sensitivity": sensitivity.to_dict() if sensitivity else None})

    new_state = ("investigating" if decision.blocked
                 else "awaiting_approval" if decision.approval_required
                 else "authorized")
    set_case_state(conn, case["case_id"], new_state)

    # An approval button cannot answer "is this order real?", so when the gate
    # finds the plan turns on an unconfirmed input, the case asks the actual
    # question instead. The agent may already have asked during investigation; if
    # it did, the case is not left waiting on a second, duplicate question.
    if "decision_sensitive_to_unconfirmed_input" in decision.triggers:
        already_open = conn.execute(
            select(s.interactions).where(
                s.interactions.c.case_id == case["case_id"],
                s.interactions.c.answer.is_(None),
            )
        ).mappings().first()
        answered = conn.execute(
            select(s.interactions).where(
                s.interactions.c.case_id == case["case_id"],
                s.interactions.c.answer.is_not(None),
            )
        ).mappings().first()
        if already_open is None and answered is None:
            open_question(
                conn, case["case_id"],
                question=sensitivity.question(),
                kind="clarification",
                options=sensitivity.options(),
                context=sensitivity.to_dict(),
                recommendation=(
                    f"Default to {sensitivity.quantity_without} units unless the signal "
                    f"is confirmed; unconfirmed demand is not demand."
                ),
                raised_by="policy_gate",
            )
            new_state = "awaiting_buyer"

    return {
        "proposal_id": proposal_id,
        "version": version,
        "gate": decision.to_dict(),
        "approval_required": decision.approval_required,
        "blocked": decision.blocked,
        "simulation": sim_dict,
        "missing_evidence": gaps,
        "sensitivity": sensitivity.to_dict() if sensitivity else None,
        "case_state": new_state,
    }


def _revalidate(conn: Connection, case: dict, proposal: dict) -> dict:
    """Re-run the simulation immediately before committing.

    A proposal approved ten minutes ago may no longer be feasible: budget can be
    consumed by another case, a quote can expire. Executing on stale numbers is
    how systems overspend.
    """
    ctx = build_context(conn, case)
    candidate = _resolve_candidate(ctx, proposal["action_type"],
                                   json.loads(proposal["action_args_json"]))
    return {"ctx": ctx, "candidate": candidate, "simulation": simulate(ctx, candidate)}


def authorize_and_execute(case_id: str, proposal_id: str) -> dict:
    """Execute an authorised proposal, then validate what actually happened."""
    stale_reason: str | None = None
    with transaction() as conn:
        case = load_case(conn, case_id)
        proposal = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if case is None or proposal is None:
            raise ValueError("Unknown case or proposal")

        if proposal["state"] == "blocked":
            raise StalePlan("Proposal is blocked by a hard constraint and cannot be executed.")
        if proposal["approval_required"] and proposal["state"] == "proposed":
            raise ApprovalRequired(
                f"Proposal {proposal_id} requires buyer approval: {proposal['approval_reason']}"
            )
        allowed_state = "approved" if proposal["approval_required"] else "proposed"
        if proposal["state"] != allowed_state:
            raise InvalidTransition(
                f"Proposal {proposal_id} is '{proposal['state']}' and cannot execute; "
                f"expected '{allowed_state}'."
            )
        if proposal["action_type"] in (ActionType.KEEP_PLAN.value, ActionType.NONE.value):
            escalated = proposal["disposition"] == "escalate"
            next_state = "escalated" if escalated else "resolved"
            note = (
                "No feasible action exists; the case requires human intervention."
                if escalated
                else "Existing plan is sufficient; no purchase made."
            )
            conn.execute(
                s.proposals.update().where(s.proposals.c.proposal_id == proposal_id)
                .values(state="executed")
            )
            append_event(conn, case_id, EventKind.ACTION,
                         "Escalated without purchasing" if escalated else "No action required",
                         {"proposal_id": proposal_id, "note": note})
            set_case_state(conn, case_id, next_state)
            return {"executed": False, "case_state": next_state, "note": note}

        # Fresh feasibility check against current state, not the state at proposal time.
        fresh = _revalidate(conn, case, dict(proposal))
        if not fresh["simulation"].feasible:
            reasons = "; ".join(c.binding_reason for c in fresh["simulation"].checks
                                if not c.passed)
            append_event(conn, case_id, EventKind.ERROR, "Plan became infeasible before execution",
                         {"proposal_id": proposal_id, "reasons": reasons})
            set_case_state(conn, case_id, "investigating")
            conn.execute(
                s.proposals.update().where(s.proposals.c.proposal_id == proposal_id)
                .values(state="failed")
            )
            stale_reason = reasons
        else:
            candidate = fresh["candidate"]
            behavior = case["supplier_behavior"]
            conn.execute(
                s.proposals.update().where(s.proposals.c.proposal_id == proposal_id)
                .values(state="executing")
            )
            set_case_state(conn, case_id, "executing")

    if stale_reason is not None:
        raise StalePlan(f"Plan is no longer feasible: {stale_reason}")

    # Outside the transaction: the supplier is an external system.
    try:
        result = execute(
            case_id=case_id, proposal_id=proposal_id, version=proposal["version"],
            candidate=candidate, behavior=behavior,
            node_id=case["node_id"], sku=case["sku"],
            budget_period=case["as_of_date"].strftime("%Y-%m"),
        )
    except ActionOutcomeUnknown:
        with transaction() as conn:
            conn.execute(
                s.proposals.update().where(s.proposals.c.proposal_id == proposal_id)
                .values(state="failed")
            )
            conn.execute(
                s.actions.update().where(
                    s.actions.c.proposal_id == proposal_id,
                    s.actions.c.state == "submitted",
                ).values(state="reconciliation_required")
            )
            append_event(
                conn, case_id, EventKind.ERROR, "Execution requires reconciliation",
                {"proposal_id": proposal_id,
                 "note": "The supplier may have committed, but local state could not be applied safely."},
            )
            conn.execute(
                s.cases.update().where(s.cases.c.case_id == case_id)
                .values(supplier_behavior="confirm_full")
            )
            set_case_state(conn, case_id, "escalated")
        return {"executed": False, "case_state": "escalated",
                "error": "ACTION_OUTCOME_UNKNOWN",
                "note": "Supplier outcome could not be established. Escalated rather than "
                        "retried, because a blind retry could duplicate a real order."}

    with transaction() as conn:
        # Supplier behaviour is a one-shot demo event describing the next call.
        conn.execute(
            s.cases.update().where(s.cases.c.case_id == case_id)
            .values(supplier_behavior="confirm_full")
        )
    verdict = validate_and_route(case_id, result["action_id"])
    with transaction() as conn:
        conn.execute(
            s.proposals.update().where(s.proposals.c.proposal_id == proposal_id)
            .values(state="executed" if result["state"] == "completed" else "failed")
        )
    return {"executed": True, **result, "verdict": verdict.to_dict()}


def validate_and_route(case_id: str, action_id: str) -> Verdict:
    """Validate an executed action and move the case accordingly."""
    with transaction() as conn:
        case = load_case(conn, case_id)
        action_row = conn.execute(
            select(s.actions).where(s.actions.c.action_id == action_id)
        ).mappings().first()

        verdict = validator_mod.validate_action(conn, case, dict(action_row))

        conn.execute(s.actions.update()
                     .where(s.actions.c.action_id == action_id)
                     .values(verdict_json=json.dumps(verdict.to_dict())))

        next_state = validator_mod.next_case_state(
            verdict, case["replan_count"], get_settings().max_replans
        )
        append_event(conn, case_id, EventKind.VERDICT,
                     f"Validation: {verdict.verdict.value}", verdict.to_dict())

        values = {"state": next_state}
        if next_state == "reopened":
            values["replan_count"] = case["replan_count"] + 1
        conn.execute(s.cases.update().where(s.cases.c.case_id == case_id).values(**values))

    return verdict


def approve(case_id: str, proposal_id: str, approver: str = "buyer") -> dict:
    with transaction() as conn:
        proposal = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if proposal is None:
            raise ValueError("Unknown proposal")
        if proposal["state"] == "blocked":
            raise StalePlan(
                "This proposal is blocked by a hard constraint. Approval cannot waive "
                "budget or capacity; the underlying constraint must change first."
            )
        if proposal["state"] != "proposed":
            raise InvalidTransition(
                f"Proposal {proposal_id} is '{proposal['state']}' and cannot be approved."
            )
        if not proposal["approval_required"]:
            raise InvalidTransition(
                f"Proposal {proposal_id} is within delegated authority and does not need approval."
            )
        conn.execute(s.proposals.update()
                     .where(s.proposals.c.proposal_id == proposal_id)
                     .values(state="approved", decided_by=approver,
                             decided_at=datetime.utcnow()))
        append_event(conn, case_id, EventKind.APPROVAL, "Buyer approved the plan",
                     {"proposal_id": proposal_id, "version": proposal["version"],
                      "approver": approver,
                      "authorized_terms": json.loads(proposal["action_args_json"])})
        set_case_state(conn, case_id, "authorized")
    return authorize_and_execute(case_id, proposal_id)


def decline(case_id: str, proposal_id: str, reason: str = "") -> dict:
    with transaction() as conn:
        proposal = conn.execute(
            select(s.proposals).where(s.proposals.c.proposal_id == proposal_id)
        ).mappings().first()
        if proposal is None:
            raise ValueError("Unknown proposal")
        if proposal["state"] != "proposed" or not proposal["approval_required"]:
            raise InvalidTransition(
                f"Proposal {proposal_id} is '{proposal['state']}' and cannot be declined."
            )
        conn.execute(s.proposals.update()
                     .where(s.proposals.c.proposal_id == proposal_id)
                     .values(state="declined", decided_by="buyer",
                             decided_at=datetime.utcnow(), decline_reason=reason))
        append_event(conn, case_id, EventKind.APPROVAL, "Buyer declined the plan",
                     {"proposal_id": proposal_id, "reason": reason})
        set_case_state(conn, case_id, "investigating")
    return {"declined": True, "case_state": "investigating"}
