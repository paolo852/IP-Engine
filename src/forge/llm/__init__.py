"""Provider-agnostic LLM access.

The Engine talks to hosted LLMs only through ``LLMProvider`` so the vendor and
region are swappable (EU-hosting preferred). The default concrete provider uses
the official Anthropic SDK; tests inject a fake provider and never hit the network.
"""

from .provider import (
    AnthropicProvider,
    LLMProvider,
    LLMResponse,
    build_provider,
)

__all__ = ["LLMProvider", "LLMResponse", "AnthropicProvider", "build_provider"]
