"""Gemini adapter.

Automatic function calling is switched off deliberately. Letting the SDK execute
tools would hide every call from the case history and bypass the server-side gate,
which are the two things this system most needs to keep visible and enforced.

The AFC configuration is known to persist across requests within a client session,
so a fresh config object is constructed for every call.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from app.agent.providers.base import Message, Provider, ToolCall, Turn


def _to_declaration(schema: dict) -> types.FunctionDeclaration:
    params = schema.get("parameters") or {"type": "object", "properties": {}}
    return types.FunctionDeclaration(
        name=schema["name"],
        description=schema["description"],
        parameters=params,
    )


def _to_contents(messages: list[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    for m in messages:
        if m.role == "tool":
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(
                    name=m.tool_name, response=m.tool_result or {}
                )
            ]))
        elif m.role == "model":
            parts: list[types.Part] = []
            if m.text:
                parts.append(types.Part.from_text(text=m.text))
            for tc in m.tool_calls:
                parts.append(types.Part.from_function_call(name=tc.name, args=tc.args))
            contents.append(types.Content(role="model", parts=parts or [
                types.Part.from_text(text=" ")
            ]))
        else:
            contents.append(types.Content(role="user", parts=[
                types.Part.from_text(text=m.text)
            ]))
    return contents


class GeminiProvider(Provider):
    def __init__(self, api_key: str, model: str):
        self.name = "gemini"
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def generate(self, system: str, messages: list[Message], tools: list[dict]) -> Turn:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[_to_declaration(t) for t in tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.0,
        )
        response = self._client.models.generate_content(
            model=self.model, contents=_to_contents(messages), config=config
        )

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        candidates = getattr(response, "candidates", None) or []
        if candidates and candidates[0].content and candidates[0].content.parts:
            for part in candidates[0].content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    calls.append(ToolCall(name=fc.name, args=dict(fc.args or {})))
                elif getattr(part, "text", None):
                    text_parts.append(part.text)

        return Turn(text="\n".join(text_parts).strip(), tool_calls=calls)
