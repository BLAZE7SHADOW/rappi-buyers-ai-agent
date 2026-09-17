"""The bounded agent loop.

Every iteration is persisted before the next begins, so a run that crashes or is
interrupted leaves a complete, inspectable history rather than a gap.

Three bounds keep the loop honest:

* a tool-call budget, after which the run stops with findings rather than a
  guess;
* duplicate-call suppression, so a model that asks the same question twice gets
  told rather than looping;
* a replan budget per case, after which the situation escalates to a human.

Running out of budget produces a pending investigation. It never produces a
fabricated recommendation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select

from app.agent.prompts import SYSTEM_PROMPT, replan_prompt
from app.agent.providers import Message, get_provider
from app.agent.schemas import TOOL_SCHEMAS
from app.agent.tools import HANDLERS, TERMINAL_TOOLS, ToolError
from app.config import get_settings
from app.db import schema as s
from app.db.engine import transaction
from app.db.repo import append_event, load_case, set_case_state
from app.domain.types import EventKind


class RunConflict(Exception):
    """A run is already active for this case."""


class InvalidCaseState(Exception):
    """The workflow is waiting on another actor or has already finished."""


RUNNABLE_STATES = {"investigating", "pending_investigation", "reopened"}


def _opening_message(case: dict) -> str:
    trigger = case["trigger_payload"]
    lines = [
        f"Purchasing case {case['case_id']} for {case['sku']} at {case['node_id']}.",
        f"Trigger: {case['trigger_type']}.",
    ]
    if trigger.get("recommended_qty"):
        lines.append(
            f"The purchasing system recommends buying {trigger['recommended_qty']} units. "
            f"Treat this as a claim to be checked, not an instruction."
        )
    if trigger.get("note"):
        lines.append(f"Note on the trigger: {trigger['note']}")
    lines.append("Investigate the situation and record a proposal.")
    return "\n".join(lines)


def _latest_verdict(conn, case_id: str) -> dict | None:
    row = conn.execute(
        select(s.case_events)
        .where(s.case_events.c.case_id == case_id, s.case_events.c.kind == "verdict")
        .order_by(s.case_events.c.seq.desc())
    ).mappings().first()
    return json.loads(row["payload_json"]) if row else None


def run_case(
    case_id: str,
    max_tool_calls: int | None = None,
    provider=None,
) -> dict:
    """Run or resume investigation for one case.

    ``provider`` may be injected so evaluations can record a live run and replay
    it deterministically afterwards. Everything else -- tools, gate, executor,
    validator -- is identical between the two, so a replayed run exercises the
    real system rather than a mock of it.
    """
    settings = get_settings()
    budget = settings.max_tool_calls if max_tool_calls is None else max_tool_calls

    with transaction() as conn:
        case = load_case(conn, case_id)
        if case is None:
            raise ValueError(f"Unknown case {case_id}")
        if case["state"] not in RUNNABLE_STATES:
            raise InvalidCaseState(
                f"Case {case_id} is '{case['state']}' and cannot run the agent now."
            )
        active = conn.execute(
            select(s.agent_runs).where(s.agent_runs.c.case_id == case_id,
                                       s.agent_runs.c.status == "running")
        ).mappings().first()
        if active:
            raise RunConflict(f"Run {active['run_id']} is already active for {case_id}.")

        provider = provider or get_provider()

        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(s.agent_runs.insert().values(
            run_id=run_id, case_id=case_id,
            mode="replay" if provider.name.startswith("replay:") else "live",
            provider=provider.name, model=provider.model, status="running",
        ))

        messages = [Message(role="user", text=_opening_message(case))]

        # A reopened case must see why it reopened, or it will re-propose the plan
        # that already failed.
        if case["state"] == "reopened":
            verdict = _latest_verdict(conn, case_id)
            if verdict:
                messages.append(Message(role="user", text=replan_prompt(verdict)))

        # A buyer's answer is durable case context, not a transient chat message.
        answered = conn.execute(
            select(s.interactions).where(s.interactions.c.case_id == case_id,
                                         s.interactions.c.answer.isnot(None))
        ).mappings().all()
        for a in answered:
            messages.append(Message(
                role="user",
                text=f"Buyer answered your question '{a['question']}': {a['answer']}",
            ))

        set_case_state(conn, case_id, "investigating")
        append_event(conn, case_id, EventKind.STATE, "Agent run started",
                     {"run_id": run_id, "provider": provider.name, "model": provider.model})

    calls_made = 0
    seen: set[str] = set()
    outcome = "budget_exhausted"
    final_text = ""
    no_tool_turns = 0

    try:
        while calls_made < budget:
            turn = provider.generate(SYSTEM_PROMPT, messages, TOOL_SCHEMAS)

            if not turn.wants_tools:
                final_text = turn.text
                no_tool_turns += 1
                if no_tool_turns >= 2:
                    outcome = "stopped_without_proposal"
                    break
                messages.append(Message(role="model", text=turn.text, raw=turn.raw))
                messages.append(Message(
                    role="user",
                    text=(
                        "The investigation is not complete until you use a terminal "
                        "tool. If evidence is sufficient, call propose_plan now. If a "
                        "business answer is still required, call ask_buyer. Do not "
                        "finish with plain text."
                    ),
                ))
                continue

            no_tool_turns = 0

            messages.append(Message(role="model", text=turn.text, tool_calls=turn.tool_calls,
                                    raw=turn.raw))

            terminal_hit = False
            budget_hit = False
            for call in turn.tool_calls:
                if terminal_hit:
                    messages.append(Message(
                        role="tool", tool_name=call.name,
                        tool_result={
                            "error": "SKIPPED_AFTER_TERMINAL",
                            "message": "A terminal case action already completed in this turn.",
                        },
                    ))
                    continue
                if calls_made >= budget:
                    budget_hit = True
                    messages.append(Message(
                        role="tool", tool_name=call.name,
                        tool_result={
                            "error": "TOOL_BUDGET_EXHAUSTED",
                            "message": f"The strict tool-call budget of {budget} is exhausted.",
                        },
                    ))
                    continue
                calls_made += 1
                signature = f"{call.name}:{json.dumps(call.args, sort_keys=True)}"

                if signature in seen and call.name not in TERMINAL_TOOLS:
                    result = {
                        "error": "REPEATED_CALL",
                        "message": (
                            f"{call.name} was already called with these exact arguments "
                            f"and returned the same result. Use what you already have, or "
                            f"call a different tool."
                        ),
                    }
                else:
                    seen.add(signature)
                    result = _invoke(case_id, call.name, call.args, run_id)

                messages.append(Message(role="tool", tool_name=call.name, tool_result=result))

                if call.name in TERMINAL_TOOLS and "error" not in result:
                    outcome = "proposed" if call.name == "propose_plan" else "awaiting_buyer"
                    terminal_hit = True

            if terminal_hit:
                break
            if budget_hit or calls_made >= budget:
                outcome = "budget_exhausted"
                break

    except Exception as exc:
        with transaction() as conn:
            conn.execute(s.agent_runs.update().where(s.agent_runs.c.run_id == run_id)
                         .values(status="failed", error=str(exc),
                                 tool_call_count=calls_made,
                                 finished_at=datetime.utcnow()))
            append_event(conn, case_id, EventKind.ERROR, "Agent run failed",
                         {"run_id": run_id, "error": str(exc),
                          "error_type": type(exc).__name__})
        raise

    with transaction() as conn:
        conn.execute(s.agent_runs.update().where(s.agent_runs.c.run_id == run_id)
                     .values(status="completed", tool_call_count=calls_made,
                             finished_at=datetime.utcnow()))

        # A run that ran out of budget has findings, not a recommendation. Say so.
        if outcome in ("budget_exhausted", "stopped_without_proposal"):
            set_case_state(conn, case_id, "pending_investigation")
            append_event(
                conn, case_id, EventKind.STATE, "Investigation incomplete",
                {"run_id": run_id, "outcome": outcome, "tool_calls": calls_made,
                 "model_text": final_text,
                 "note": ("The run ended without a proposal. Findings so far are in "
                          "the timeline; no recommendation has been fabricated.")},
            )
        append_event(conn, case_id, EventKind.STATE, "Agent run finished",
                     {"run_id": run_id, "outcome": outcome, "tool_calls": calls_made})

    return {"run_id": run_id, "outcome": outcome, "tool_calls": calls_made,
            "provider": provider.name, "model": provider.model, "text": final_text}


def _invoke(case_id: str, name: str, args: dict, run_id: str) -> dict:
    """Run one tool, recording both the call and its result in the case history."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": "UNKNOWN_TOOL", "message": f"No tool named {name}."}

    with transaction() as conn:
        append_event(conn, case_id, EventKind.TOOL_CALL, f"{name}",
                     {"run_id": run_id, "tool": name, "args": args})

    try:
        result = handler(case_id, args or {})
    except ToolError as exc:
        result = exc.to_dict()
    except Exception as exc:  # surfaced to the model as a typed failure
        result = {"error": "TOOL_FAILED", "message": str(exc),
                  "error_type": type(exc).__name__}

    with transaction() as conn:
        append_event(conn, case_id, EventKind.OBSERVATION, f"{name} result",
                     {"run_id": run_id, "tool": name, "result": result})
    return result
