"""Test doubles for the LLM layer — no network, no SDK, no credentials."""

from __future__ import annotations

import json
from dataclasses import dataclass

from forge.llm.provider import LLMResponse


class FakeProvider:
    """An LLMProvider that returns canned text and records each call."""

    def __init__(self, text: str, model: str = "fake-model") -> None:
        self._text = text
        self._model = model
        self.calls: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system, user, *, json_schema=None, max_tokens=None) -> LLMResponse:
        self.calls.append(
            {"system": system, "user": user, "json_schema": json_schema, "max_tokens": max_tokens}
        )
        return LLMResponse(text=self._text, model=self._model)


# -- fake Anthropic SDK client (for AnthropicProvider wiring tests) ----------
@dataclass
class _Block:
    type: str
    text: str


@dataclass
class _Response:
    content: list
    model: str
    usage: object = None


class _FakeMessages:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class FakeAnthropicClient:
    """Mimics the slice of the anthropic SDK that AnthropicProvider touches."""

    def __init__(self, text: str, model: str = "claude-opus-4-8") -> None:
        self.messages = _FakeMessages(
            _Response(content=[_Block("text", text)], model=model)
        )


def profile_json(problem, solution, applications, query_terms) -> str:
    """Build a profiling-response JSON string from (value, quote) tuples."""
    def grounded(pair):
        return {"value": pair[0], "quote": pair[1]}

    return json.dumps(
        {
            "problem": grounded(problem),
            "solution": grounded(solution),
            "applications": [grounded(a) for a in applications],
            "query_terms": list(query_terms),
        }
    )
