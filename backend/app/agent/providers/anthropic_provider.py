"""Anthropic adapter.

Kept alongside the Gemini adapter to prove the loop is genuinely provider-neutral:
selecting it changes one environment variable and no application code.
"""

from __future__ import annotations

import anthropic

from app.agent.providers.base import Message, Provider, ToolCall, Turn


def _to_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "input_schema": s.get("parameters") or {"type": "object", "properties": {}},
        }
        for s in schemas
    ]


def _to_messages(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.tool_name,
                "content": str(m.tool_result),
            }]})
        elif m.role == "model":
            content: list[dict] = []
            if m.text:
                content.append({"type": "text", "text": m.text})
            for tc in m.tool_calls:
                content.append({"type": "tool_use", "id": tc.call_id or tc.name,
                                "name": tc.name, "input": tc.args})
            out.append({"role": "assistant", "content": content or [
                {"type": "text", "text": " "}]})
        else:
            out.append({"role": "user", "content": m.text})
    return out


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, model: str):
        self.name = "anthropic"
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, system: str, messages: list[Message], tools: list[dict]) -> Turn:
        response = self._client.messages.create(
            model=self.model, max_tokens=4096, system=system,
            messages=_to_messages(messages), tools=_to_tools(tools), temperature=0.0,
        )
        text_parts, calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(name=block.name, args=dict(block.input),
                                      call_id=block.id))
        return Turn(text="\n".join(text_parts).strip(), tool_calls=calls)
