from __future__ import annotations

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
