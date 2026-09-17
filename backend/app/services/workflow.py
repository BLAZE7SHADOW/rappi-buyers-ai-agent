"""Durable-step helper.

A purchasing case is a long-running workflow: it spans multiple LLM turns, waits
on a human, calls an external system that can fail, and must survive a process
restart with its history intact.

In production this belongs on a durable execution engine such as Temporal -- the
case is the workflow, buyer approval is a signal, and supplier calls are
activities with idempotency keys and retry policies. For a demo that has to run
from a clean checkout with no infrastructure, the same properties are implemented
directly here:

| Temporal concept        | Implementation                                    |
|-------------------------|---------------------------------------------------|
| Workflow state          | ``cases.state``, persisted after every step        |
| Event history           | ``case_events``, append-only                       |
| Activity idempotency    | ``actions.idempotency_key`` UNIQUE + lookup        |
| Signals                 | run/resume, approval, supplier event injection     |
| Retry policy            | bounded attempts, then escalate                    |

``step`` is the seam: it records the transition, runs the work, and records the
outcome, so a case's history is complete even when a step raises.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, TypeVar

from app.db.engine import transaction
from app.db.repo import append_event, set_case_state
from app.domain.types import EventKind

T = TypeVar("T")


def transition(case_id: str, state: str, label: str = "", payload: dict | None = None) -> None:
    """Persist a state change and record it in the case history."""
    with transaction() as conn:
        set_case_state(conn, case_id, state)
        append_event(conn, case_id, EventKind.STATE, label or f"State → {state}",
                     {"state": state, **(payload or {})})


def step(case_id: str, name: str, fn: Callable[[], T], *, state: str | None = None) -> T:
    """Run one unit of work with its boundaries recorded.

    If ``fn`` raises, the failure is written to the case history before the
    exception propagates, so a crashed run leaves an explainable trail rather than
    a silent gap.
    """
    if state:
        transition(case_id, state, f"{name} started")
    try:
        result = fn()
    except Exception as exc:
        with transaction() as conn:
            append_event(conn, case_id, EventKind.ERROR, f"{name} failed",
                         {"error": str(exc), "error_type": type(exc).__name__})
        raise
    return result


@contextmanager
def guarded(case_id: str, name: str):
    """Context-manager form of :func:`step` for multi-statement blocks."""
    try:
        yield
    except Exception as exc:
        with transaction() as conn:
            append_event(conn, case_id, EventKind.ERROR, f"{name} failed",
                         {"error": str(exc), "error_type": type(exc).__name__})
        raise
