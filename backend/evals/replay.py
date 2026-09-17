"""Record and replay model turns.

An agent evaluation that calls a live model is not reproducible: the same fixture
can take a different investigation path on each run. Recording the model's turns
once and replaying them afterwards makes the evaluation deterministic while still
exercising the real tools, gate, executor and validator -- only the model's
responses come from disk.

This is also what lets the evaluation suite run without an API key, which is why
there is no separate non-LLM agent implementation to drift out of sync.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.providers.base import Message, Provider, ToolCall, Turn

RECORDINGS = Path(__file__).resolve().parent / "recordings"


def _turn_to_dict(turn: Turn) -> dict:
    return {
        "text": turn.text,
        "tool_calls": [{"name": c.name, "args": c.args} for c in turn.tool_calls],
    }


def _turn_from_dict(d: dict) -> Turn:
    return Turn(
        text=d.get("text", ""),
        tool_calls=[ToolCall(name=c["name"], args=c.get("args") or {})
                    for c in d.get("tool_calls", [])],
    )


class RecordingProvider(Provider):
    """Passes calls through to a real provider and saves each turn."""

    def __init__(self, inner: Provider, path: Path):
        self.name = inner.name
        self.model = inner.model
        self._inner = inner
        self._path = path
        self._turns: list[dict] = []

    def generate(self, system: str, messages: list[Message], tools: list[dict]) -> Turn:
        turn = self._inner.generate(system, messages, tools)
        self._turns.append(_turn_to_dict(turn))
        return turn

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"provider": self.name, "model": self.model, "turns": self._turns},
            indent=2,
        ))


class ReplayProvider(Provider):
    """Replays recorded turns in order.

    Running past the end of a recording raises rather than inventing a turn: a
    replay that diverges from what was recorded is a broken evaluation, not a
    result worth reporting.
    """

    def __init__(self, path: Path, *, segment: int | None = None):
        data = json.loads(path.read_text())
        self.name = f"replay:{data.get('provider', 'unknown')}"
        self.model = data.get("model", "unknown")
        turns = data["turns"]
        if segment is not None:
            segments: list[list[dict]] = []
            current: list[dict] = []
            for turn in turns:
                current.append(turn)
                names = {c.get("name") for c in turn.get("tool_calls", [])}
                if names.intersection({"propose_plan", "ask_buyer"}):
                    segments.append(current)
                    current = []
            if current:
                segments.append(current)
            if segment >= len(segments):
                raise RuntimeError(
                    f"Recording {path.name} has {len(segments)} run segment(s); "
                    f"segment {segment} does not exist."
                )
            turns = segments[segment]
        self._turns = [_turn_from_dict(t) for t in turns]
        self._index = 0

    def generate(self, system: str, messages: list[Message], tools: list[dict]) -> Turn:
        if self._index >= len(self._turns):
            raise RuntimeError(
                f"Replay exhausted after {len(self._turns)} turns. The recording no "
                f"longer matches this code path; re-record with --record."
            )
        turn = self._turns[self._index]
        self._index += 1
        return turn


def recording_path(fixture_id: str) -> Path:
    return RECORDINGS / f"{fixture_id}.json"


def has_recording(fixture_id: str) -> bool:
    return recording_path(fixture_id).exists()
