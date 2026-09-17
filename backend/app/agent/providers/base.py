"""Provider-neutral shapes for the agent loop.

The loop is written against these types only, so swapping Gemini for Anthropic is
an adapter change rather than a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict
    call_id: str = ""


@dataclass
class Turn:
    """One model response: free text, tool calls, or both.

    ``raw`` carries the provider's own response object. Some providers attach
    opaque state to function-call parts -- Gemini's thought signatures, for
    instance -- which must be echoed back verbatim on the next request. Rebuilding
    the content from the neutral fields alone would silently drop it.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class Message:
    """A provider-neutral conversation entry.

    ``role`` is one of ``user``, ``model`` or ``tool``. Tool messages carry the
    tool name and its JSON result.
    """

    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_name: str = ""
    tool_result: dict | None = None
    # Provider-native content to replay verbatim, when the provider requires it.
    raw: Any = None


class Provider(Protocol):
    name: str
    model: str

    def generate(self, system: str, messages: list[Message], tools: list[dict]) -> Turn:
        ...
