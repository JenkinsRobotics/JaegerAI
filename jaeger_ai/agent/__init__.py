"""JROS agent layer — framework-free replacement for pydantic-ai.

Phase-1 surface: the public types are pinned here so downstream
modules can import from one place and Phase 2-6 internal moves don't
ripple through the codebase.

  • Message / ToolCall      — the internal OpenAI-shaped TypedDicts
  • ToolDef                  — one tool, three renderers, validated dispatch
  • register_tool            — decorator for built-in tools
  • register_tool_instance   — runtime registration (skills, MCP)
  • get_tool / get_tools     — registry lookup
  • ProviderAdapter          — backend ABC (Anthropic / OpenAI / Hermes-XML / in-process)
  • AgentCallbacks           — observability hooks
  • AgentInterrupted         — raised when an interrupt fires mid-call
  • interruptible_call       — the cancel-aware call wrapper
  • JaegerAgent              — the loop itself
"""

from __future__ import annotations

from jaeger_ai.agent.parsing import schema_sanitizer
from .adapters.anthropic import AnthropicAdapter
from jaeger_os.core.tools.arg_coercion import coerce_args
from .adapters.base import KNOWN_FEATURES, ProviderAdapter
from .adapters.hermes_xml import HermesXMLAdapter
from .adapters.local_llama import LocalLlamaAdapter
from .adapters.mlx import MLXAdapter
from .adapters.openai import OpenAIAdapter
from jaeger_ai.agent.loop.callbacks import AgentCallbacks
from jaeger_ai.agent.loop.interrupt import AgentInterrupted, StaleCallTimeout, interruptible_call
from jaeger_ai.agent.util.retry_utils import jittered_backoff, retry_with_backoff
from jaeger_ai.agent.loop.jaeger_agent import JaegerAgent, SkipFinalFinalizer
from jaeger_ai.agent.schemas.message_types import Message, Role, ToolCall
from jaeger_ai.agent.prompts.prompts import build_system_prompt
from jaeger_os.core.tools.tool_registry import (
    clear_registry,
    get_tool,
    get_tools,
    has_tool,
    register_tool,
    register_tool_from_function,
    register_tool_instance,
    unregister_tool,
)
from jaeger_os.core.tools.tool_schema import ToolDef, dev_mode_enabled
from jaeger_ai.agent.schemas.tool_bundles import (
    JAEGER_TOOLSETS,
    list_toolsets,
    resolve_toolsets,
    toolset_for_tool,
)

__all__ = [
    # message types
    "Message", "Role", "ToolCall",
    # tools
    "ToolDef", "dev_mode_enabled",
    "register_tool", "register_tool_from_function", "register_tool_instance",
    "unregister_tool", "get_tool", "get_tools", "has_tool", "clear_registry",
    # adapters
    "ProviderAdapter", "KNOWN_FEATURES",
    "AnthropicAdapter", "OpenAIAdapter", "HermesXMLAdapter",
    "LocalLlamaAdapter", "MLXAdapter",
    # observability + control
    "AgentCallbacks", "AgentInterrupted", "StaleCallTimeout",
    "interruptible_call",
    # the loop
    "JaegerAgent", "SkipFinalFinalizer",
    # prompt assembly
    "build_system_prompt",
    # phase-7 toolsets
    "JAEGER_TOOLSETS", "list_toolsets", "resolve_toolsets", "toolset_for_tool",
    # phase-8 resilience
    "coerce_args", "schema_sanitizer",
    "jittered_backoff", "retry_with_backoff",
]
