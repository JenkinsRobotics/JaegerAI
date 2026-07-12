"""Provider adapters. One file per backend; the package re-exports the
public adapter classes so callers can ``from jaeger_os.agent.adapters
import AnthropicAdapter`` without knowing the module layout."""

from __future__ import annotations

from .anthropic import AnthropicAdapter
from .base import KNOWN_FEATURES, ProviderAdapter
from .hermes_xml import HERMES_TOOL_INSTRUCTIONS, HermesXMLAdapter
from .local_llama import LocalLlamaAdapter
from .mlx import MLXAdapter
from .openai import KNOWN_PROVIDERS, OpenAIAdapter

__all__ = [
    "AnthropicAdapter",
    "HERMES_TOOL_INSTRUCTIONS",
    "HermesXMLAdapter",
    "KNOWN_FEATURES",
    "KNOWN_PROVIDERS",
    "LocalLlamaAdapter",
    "MLXAdapter",
    "OpenAIAdapter",
    "ProviderAdapter",
]
