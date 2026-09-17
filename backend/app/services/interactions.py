"""Opening a question to the buyer, and pausing the case until it is answered.

Two things reach this module, and that is deliberate. The agent calls it through
`ask_buyer` when it notices during investigation that it needs a human. The policy
gate calls it when the agent did **not** notice but the plan demonstrably rests on
an unconfirmed input that would change the order.

Both produce the same artefact and the same case state, so downstream -- the UI,
the audit trail, the evaluation -- does not care which path found the problem. The
agent asking earlier is better, but nothing depends on it doing so.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.engine import Connection

from app.db import schema as s
from app.db.repo import append_event, set_case_state
from app.domain.types import EventKind


def open_question(
    conn: Connection,
    case_id: str,
    *,
    question: str,
    kind: str = "clarification",
    options: list[str] | None = None,
    context: dict | None = None,
    recommendation: str = "",
    raised_by: str = "agent",
) -> str:
    """Record a question and move the case to ``awaiting_buyer``.

    Runs inside the caller's transaction so the question and the state change
    commit together; a question the buyer can see but the workflow has not
    stopped for would be worse than no question at all.
    """
    interaction_id = f"INT-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(s.interactions.insert().values(
        interaction_id=interaction_id, case_id=case_id,
        kind=kind,
        question=question,
        context_json=json.dumps({**(context or {}), "raised_by": raised_by}, default=str),
        options_json=json.dumps(options or []),
        recommendation=recommendation,
    ))
    append_event(
        conn, case_id, EventKind.QUESTION,
        "Question for the buyer" if raised_by == "agent" else "Policy requires a buyer decision",
        {"interaction_id": interaction_id, "question": question,
         "options": options or [], "recommendation": recommendation,
         "raised_by": raised_by},
    )
    set_case_state(conn, case_id, "awaiting_buyer")
    return interaction_id
