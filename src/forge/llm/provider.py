"""Provider-agnostic LLM wrapper + the default Anthropic implementation.

The ``LLMProvider`` protocol is text-in / text-out so any hosted LLM can sit
behind it. ``json_schema`` is an optional hint a provider may use to constrain
output; providers that can't honour it still return text the caller validates.

The concrete ``AnthropicProvider`` calls Claude through the official Anthropic
SDK (imported lazily so the package isn't needed for tests). The API key comes
from the environment, never source; the region/base URL is config-driven so an
EU-hosted endpoint can be swapped in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import LLMConfig

# Env var checked first for the key; the Anthropic SDK falls back to ANTHROPIC_API_KEY.
API_KEY_ENV = "FORGE_LLM_API_KEY"


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: dict | None = None


class LLMProvider(Protocol):
    @property
    def model(self) -> str: ...

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class AnthropicProvider:
    """Default provider — calls Claude via the official Anthropic SDK."""

    def __init__(self, config: LLMConfig, *, client: Any | None = None) -> None:
        self._config = config
        self._client = client  # injectable for tests; lazily built otherwise

    @property
    def model(self) -> str:
        return self._config.model

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy: not required unless the real provider runs

            api_key = os.environ.get(API_KEY_ENV)  # None -> SDK uses ANTHROPIC_API_KEY
            self._client = anthropic.Anthropic(
                api_key=api_key, base_url=self._config.base_url
            )
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens or self._config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self._config.adaptive_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        if json_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": json_schema}
            }

        response = client.messages.create(**kwargs)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            model=getattr(response, "model", self._config.model),
            usage=usage.to_dict() if hasattr(usage, "to_dict") else None,
        )


def build_provider(config: LLMConfig, **kwargs: Any) -> LLMProvider:
    """Construct the provider named in config. Extend here for new vendors."""
    if config.provider == "anthropic":
        return AnthropicProvider(config, **kwargs)
    raise ValueError(f"unknown LLM provider {config.provider!r}")
