"""AnthropicProvider request mapping (via an injected fake client) + factory."""

from __future__ import annotations

import pytest

from forge.config import LLMConfig
from forge.llm import AnthropicProvider, build_provider

from .fakes import FakeAnthropicClient


def config(**over) -> LLMConfig:
    base = dict(
        provider="anthropic", model="claude-opus-4-8", base_url=None,
        max_tokens=4096, adaptive_thinking=True,
    )
    base.update(over)
    return LLMConfig(**base)


def test_complete_maps_request_and_extracts_text():
    client = FakeAnthropicClient(text='{"ok": true}', model="claude-opus-4-8")
    provider = AnthropicProvider(config(), client=client)

    resp = provider.complete("SYS", "USER", json_schema={"type": "object"}, max_tokens=999)

    assert resp.text == '{"ok": true}'
    assert resp.model == "claude-opus-4-8"
    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["max_tokens"] == 999
    assert kwargs["system"] == "SYS"
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_thinking_omitted_when_disabled_and_default_max_tokens():
    client = FakeAnthropicClient(text="hi")
    provider = AnthropicProvider(config(adaptive_thinking=False), client=client)

    provider.complete("s", "u")
    kwargs = client.messages.last_kwargs
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs  # no schema passed
    assert kwargs["max_tokens"] == 4096   # falls back to config


def test_build_provider_returns_anthropic_provider():
    provider = build_provider(config(), client=FakeAnthropicClient("x"))
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-opus-4-8"


def test_build_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown LLM provider"):
        build_provider(config(provider="totally-made-up"))
