"""Execution, approval, idempotency and validation.

These tests exercise the properties that make the system safe to let near real
purchasing: nothing executes without authority, nothing executes twice, and
nothing is reported as successful because a request returned 200.
"""

import json

import pytest
from sqlalchemy import select

from conftest import create_po_args, expedite_args, make_case  # noqa: F401


def _case(db, case_id):
    from app.db.engine import transaction
    from app.db.repo import load_case
    with transaction() as conn:
        return load_case(conn, case_id)


def _propose(db, case_id, *, disposition, action_type, args):
    from app.db.engine import transaction
    from app.db.repo import load_case
    from app.services.proposals import create_proposal
    with transaction() as conn:
        case = load_case(conn, case_id)
        return create_proposal(
            conn, case, disposition=disposition, action_type=action_type,
            action_args=args, rationale="test", important_factors=[],
            assumptions=[], evidence_refs=[],
        )


# --------------------------------------------------------------------------- #
# Authority
# --------------------------------------------------------------------------- #


def test_expensive_expedite_requires_buyer_approval(db):
    """The $450 expedite fee is above the $250 autonomy limit."""
    case_id = make_case()
    result = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                      args=expedite_args())
    assert result["approval_required"] is True
    assert "fee_above_autonomy_limit" in result["gate"]["triggers"]
    assert _case(db, case_id)["state"] == "awaiting_approval"


def test_execution_without_approval_is_refused(db):
    """The gate is server-side, so an unapproved plan cannot execute even if
    something downstream asks it to."""
    from app.services.proposals import ApprovalRequired, authorize_and_execute

    case_id = make_case()
    result = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                      args=expedite_args())
    with pytest.raises(ApprovalRequired):
        authorize_and_execute(case_id, result["proposal_id"])


def test_hard_constraint_cannot_be_waived_by_approving(db):
    """Budget is a financial fact. Approval is not a licence to overspend."""
    from app.services.proposals import StalePlan, approve

    case_id = make_case(budget_minor=100_000)  # only $1,000 available
    result = _propose(db, case_id, disposition="accept", action_type="create_po",
                      args=create_po_args(qty=800))
    assert result["blocked"] is True
    assert "budget" in result["gate"]["triggers"]

    with pytest.raises(StalePlan):
        approve(case_id, result["proposal_id"])


def test_plan_that_becomes_infeasible_is_failed_and_returns_to_investigation(db):
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.services.proposals import StalePlan, approve

    case_id = make_case()
    result = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                      args=expedite_args())
    with transaction() as conn:
        conn.execute(sch.budgets.update().values(limit_minor=0))

    with pytest.raises(StalePlan):
        approve(case_id, result["proposal_id"])

    with transaction() as conn:
        proposal = conn.execute(sch.proposals.select().where(
            sch.proposals.c.proposal_id == result["proposal_id"]
        )).mappings().one()
    assert proposal["state"] == "failed"
    assert _case(db, case_id)["state"] == "investigating"


def test_affordable_action_is_authorized_by_the_gate(db):
    # 1,000 usable against 40/day runs out on day 26; a 500-unit order at $1.00
    # closes the gap for $500, well inside the $2,000 autonomy limit, and leaves
    # 380 units of cover -- under the 12-day excess ceiling of 480.
    case_id = make_case(budget_minor=900_000, po=None, demand_per_day=40, expedite=False,
                        unit_price=100)
    result = _propose(db, case_id, disposition="accept", action_type="create_po",
                      args=create_po_args(qty=500))
    assert result["blocked"] is False
    assert result["approval_required"] is False
    assert result["case_state"] == "authorized"


def test_agent_tool_executes_an_authorized_action_and_validates_it(db):
    from app.agent.tools import propose_plan

    case_id = make_case(budget_minor=900_000, po=None, demand_per_day=40,
                        expedite=False, unit_price=100)
    result = propose_plan(case_id, {
        "disposition": "accept",
        "action_type": "create_po",
        "action_args": create_po_args(qty=500),
        "rationale": "The simulated plan closes the gap within delegated authority.",
    })

    assert result["approval_required"] is False
    assert result["execution"]["executed"] is True
    assert result["execution"]["verdict"]["verdict"] == "PASS"
    assert _case(db, case_id)["state"] == "resolved"


def test_agent_tool_routes_escalation_to_a_terminal_state(db):
    from app.agent.tools import propose_plan

    case_id = make_case(budget_minor=0, po=None, demand_per_day=100)
    result = propose_plan(case_id, {
        "disposition": "escalate",
        "action_type": "none",
        "action_args": {},
        "rationale": "No feasible paid action exists with zero budget.",
    })

    assert result["execution"]["executed"] is False
    assert result["execution"]["case_state"] == "escalated"
    assert _case(db, case_id)["state"] == "escalated"


# --------------------------------------------------------------------------- #
# Idempotency and recovery
# --------------------------------------------------------------------------- #


def test_duplicate_submission_creates_only_one_order(db):
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.services.proposals import approve

    case_id = make_case(behavior="confirm_full")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    first = approve(case_id, prop["proposal_id"])
    assert first["executed"] is True

    from app.services.proposals import InvalidTransition, authorize_and_execute
    with pytest.raises(InvalidTransition):
        authorize_and_execute(case_id, prop["proposal_id"])

    with transaction() as conn:
        rows = conn.execute(select(sch.actions)).mappings().all()
    assert len(rows) == 1


def test_lost_response_is_recovered_by_idempotency_lookup(db):
    """The supplier committed and the response was lost in transit.

    The executor must not guess. It asks the supplier what it recorded for this
    idempotency key, finds the committed action, and reconciles from that -- so the
    order completes exactly once despite the failed transport.
    """
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.db.repo import load_events
    from app.services.proposals import approve

    case_id = make_case(behavior="timeout_after_success")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    assert result["executed"] is True

    with transaction() as conn:
        ledger = conn.execute(select(sch.supplier_ledger)).mappings().all()
        pos = conn.execute(select(sch.purchase_orders)).mappings().all()
        actions = conn.execute(select(sch.actions)).mappings().all()
        labels = [e["label"] for e in load_events(conn, case_id)]

    assert len(ledger) == 1      # the supplier committed exactly once
    assert len(pos) == 1         # PO-501, expedited -- no second order invented
    assert len(actions) == 1

    # The reconciliation is visible in the case history, not silent.
    assert "Recovered lost response via idempotency key" in labels


def test_unestablished_outcome_escalates_rather_than_retrying(db, monkeypatch):
    """If the supplier has no record either, the outcome is genuinely unknown.

    Retrying here is how duplicate purchase orders get created, so the case
    escalates to a human instead.
    """
    from app.integrations import mock_supplier
    from app.services.proposals import approve

    monkeypatch.setattr(mock_supplier, "lookup", lambda key: None)

    case_id = make_case(behavior="timeout_after_success")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    assert result["executed"] is False
    assert result["error"] == "ACTION_OUTCOME_UNKNOWN"
    assert _case(db, case_id)["state"] == "escalated"


def test_definite_rejection_does_not_create_an_order(db):
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.services.proposals import approve

    case_id = make_case(behavior="reject")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    assert result["state"] == "rejected"
    assert result["verdict"]["verdict"] == "FAIL"
    with transaction() as conn:
        pos = conn.execute(select(sch.purchase_orders)).mappings().all()
    assert len(pos) == 1          # the pre-existing order, unchanged in count


# --------------------------------------------------------------------------- #
# Validation -- the feedback loop
# --------------------------------------------------------------------------- #


def test_partial_confirmation_is_not_reported_as_success(db):
    """The supplier confirms 60% and cancels the rest. The agent's intent was
    'close the gap'; the outcome does not, so the verdict is PARTIAL and the case
    reopens instead of resolving."""
    from app.services.proposals import approve

    case_id = make_case(behavior="confirm_partial")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    verdict = result["verdict"]
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["deltas"]["qty"] < 0
    assert verdict["residual_exposure"]["unmet_units"] > 0
    assert verdict["follow_up"] == "reopened_case"

    case = _case(db, case_id)
    assert case["state"] == "reopened"
    assert case["replan_count"] == 1


def test_late_confirmation_fails_the_timing_check(db):
    """Confirmed in full, but five days late. Quantity is right and the plan still
    fails, because the plan was about timing."""
    from app.services.proposals import approve

    case_id = make_case(behavior="confirm_late")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    verdict = result["verdict"]
    date_check = next(c for c in verdict["checks"] if c["name"] == "date_matches_authorized")
    assert date_check["passed"] is False
    assert verdict["deltas"]["receipt_days_late"] == 5
    assert verdict["verdict"] in ("PARTIAL", "FAIL")


def test_full_confirmation_closing_the_gap_resolves_the_case(db):
    from app.services.proposals import approve

    case_id = make_case(behavior="confirm_full")
    prop = _propose(db, case_id, disposition="reject", action_type="expedite_po",
                    args=expedite_args())
    result = approve(case_id, prop["proposal_id"])

    assert result["verdict"]["verdict"] == "PASS"
    assert _case(db, case_id)["state"] == "resolved"


def test_validator_ignores_what_the_agent_claimed(db):
    """The verdict is computed from persisted state and the authorised plan. A
    proposal whose rationale asserts success has no influence on it."""
    from app.db.engine import transaction
    from app.db.repo import load_case
    from app.services.proposals import approve, create_proposal

    case_id = make_case(behavior="confirm_partial")
    with transaction() as conn:
        case = load_case(conn, case_id)
        prop = create_proposal(
            conn, case, disposition="reject", action_type="expedite_po",
            action_args=expedite_args(),
            rationale="This will completely resolve the shortage with no residual risk.",
            important_factors=["fully resolved"], assumptions=[], evidence_refs=[],
        )
    result = approve(case_id, prop["proposal_id"])
    assert result["verdict"]["verdict"] == "PARTIAL"


def test_keep_plan_resolves_without_ordering_anything(db):
    """Rejecting a purchase is a real outcome, not a failure to act."""
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.services.proposals import authorize_and_execute

    case_id = make_case(demand_per_day=10)
    prop = _propose(db, case_id, disposition="reject", action_type="keep_plan", args={})
    result = authorize_and_execute(case_id, prop["proposal_id"])

    assert result["executed"] is False
    assert result["case_state"] == "resolved"
    with transaction() as conn:
        actions = conn.execute(select(sch.actions)).mappings().all()
    assert actions == []


def test_spend_that_cannot_be_recorded_raises_instead_of_being_skipped(db):
    """Defence in depth for the last write in an execution.

    A missing budget is already blocking at the constraint layer, so a plan whose
    budget disappears is refused as infeasible long before the supplier is called.
    This guard covers the remaining window: the supplier has committed, and the
    commitment cannot be written locally. Returning quietly there would leave a
    real order with untracked spend, so it raises and the caller escalates for
    reconciliation rather than reporting a clean execution.
    """
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.domain.types import ActionType, Candidate
    from app.services.executor import ActionOutcomeUnknown, _commit_budget

    candidate = Candidate(action_type=ActionType.CREATE_PO, supplier_id="SUP-A",
                          qty=500, unit_price_minor=100)
    assert candidate.total_cost_minor > 0

    with transaction() as conn:
        conn.execute(sch.budgets.delete())
        with pytest.raises(ActionOutcomeUnknown):
            _commit_budget(conn, "NODE-BOG", "2026-09", candidate)


def test_a_budget_that_disappears_is_caught_before_the_supplier_is_called(db):
    from app.db import schema as sch
    from app.db.engine import transaction
    from app.services.proposals import StalePlan, approve

    # 2,500 units at $1.00 is $2,500, above the $2,000 autonomy limit, so the
    # buyer decides -- and the revalidation happens on their approval.
    case_id = make_case(budget_minor=900_000, po=None, demand_per_day=100,
                        expedite=False, unit_price=100)
    result = _propose(db, case_id, disposition="accept", action_type="create_po",
                      args=create_po_args(qty=2500))
    assert result["approval_required"] is True
    with transaction() as conn:
        conn.execute(sch.budgets.delete())

    with pytest.raises(StalePlan):
        approve(case_id, result["proposal_id"])

    with transaction() as conn:
        assert conn.execute(select(sch.actions)).mappings().all() == []
        assert conn.execute(select(sch.supplier_ledger)).mappings().all() == []
