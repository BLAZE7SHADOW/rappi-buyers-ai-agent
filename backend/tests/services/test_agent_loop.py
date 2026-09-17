from __future__ import annotations

import json

import pytest

from conftest import make_case  # noqa: F401


class FakeProvider:
    name = "fake"
    model = "deterministic-test"

    def __init__(self, turns):
        self.turns = iter(turns)

    def generate(self, system, messages, tools):
        return next(self.turns)


def test_tool_budget_is_strict_for_parallel_calls(db):
    from app.agent.loop import run_case
    from app.agent.providers import ToolCall, Turn
    from app.db import schema as s
    from app.db.engine import transaction
    from sqlalchemy import select

    case_id = make_case()
    provider = FakeProvider([Turn(tool_calls=[
        ToolCall("get_case_context", {}),
        ToolCall("get_inventory", {}),
        ToolCall("get_constraints", {}),
    ])])

    result = run_case(case_id, max_tool_calls=2, provider=provider)
    assert result["outcome"] == "budget_exhausted"
    assert result["tool_calls"] == 2
    with transaction() as conn:
        calls = conn.execute(select(s.case_events).where(
            s.case_events.c.case_id == case_id,
            s.case_events.c.kind == "tool_call",
        )).mappings().all()
    assert len(calls) == 2


def test_calls_after_a_terminal_tool_are_not_invoked(db):
    from app.agent.loop import run_case
    from app.agent.providers import ToolCall, Turn
    from app.db import schema as s
    from app.db.engine import transaction
    from sqlalchemy import select

    case_id = make_case(demand_per_day=10)
    provider = FakeProvider([Turn(tool_calls=[
        ToolCall("propose_plan", {
            "disposition": "reject",
            "action_type": "keep_plan",
            "action_args": {},
            "rationale": "Existing supply is sufficient.",
        }),
        ToolCall("get_inventory", {}),
    ])])

    result = run_case(case_id, provider=provider)
    assert result["outcome"] == "proposed"
    assert result["tool_calls"] == 1
    with transaction() as conn:
        calls = conn.execute(select(s.case_events).where(
            s.case_events.c.case_id == case_id,
            s.case_events.c.kind == "tool_call",
        )).mappings().all()
    assert [c["label"] for c in calls] == ["propose_plan"]


def test_terminal_case_cannot_run_again(db):
    from app.agent.loop import InvalidCaseState, run_case
    from app.agent.providers import ToolCall, Turn

    case_id = make_case(demand_per_day=10)
    provider = FakeProvider([Turn(tool_calls=[ToolCall("propose_plan", {
        "disposition": "reject", "action_type": "keep_plan",
        "action_args": {}, "rationale": "No purchase is needed.",
    })])])
    run_case(case_id, provider=provider)

    with pytest.raises(InvalidCaseState):
        run_case(case_id, provider=FakeProvider([]))


def test_plain_text_turn_gets_one_bounded_chance_to_finish(db):
    from app.agent.loop import run_case
    from app.agent.providers import ToolCall, Turn

    case_id = make_case(demand_per_day=10)
    provider = FakeProvider([
        Turn(text="The evidence is sufficient.", tool_calls=[]),
        Turn(tool_calls=[ToolCall("propose_plan", {
            "disposition": "reject",
            "action_type": "keep_plan",
            "action_args": {},
            "rationale": "Existing supply is sufficient.",
        })]),
    ])

    result = run_case(case_id, provider=provider)

    assert result["outcome"] == "proposed"
    assert result["tool_calls"] == 1


def test_evidence_without_a_stated_reason_is_refused(db):
    from app.agent.loop import run_case
    from app.agent.providers import ToolCall, Turn
    from app.db import schema as s
    from app.db.engine import transaction
    from sqlalchemy import select

    case_id = make_case()
    provider = FakeProvider([
        Turn(tool_calls=[ToolCall("get_inventory", {})]),
        Turn(tool_calls=[ToolCall("get_inventory", {"reason": "Confirm how much stock is sellable."})]),
        Turn(tool_calls=[ToolCall("propose_plan", {
            "disposition": "reject", "action_type": "keep_plan",
            "action_args": {}, "rationale": "Existing supply is sufficient.",
        })]),
    ])

    run_case(case_id, provider=provider)

    with transaction() as conn:
        results = conn.execute(select(s.case_events).where(
            s.case_events.c.case_id == case_id,
            s.case_events.c.kind == "observation",
        ).order_by(s.case_events.c.seq)).mappings().all()

    first = json.loads(results[0]["payload_json"])["result"]
    assert first["error"] == "MISSING_REASON"
    # The refusal is total: no evidence is returned without a stated purpose.
    assert "usable" not in first
    assert json.loads(results[1]["payload_json"])["result"]["usable"] == 1000
