"""JaegerAgent public API.

Applications import this package to add a headless agent brain.  Product
surfaces, model bundles, and robot-specific policy remain outside it.
"""

import os

from .bridge import AgentBridge
from .config import AgentConfig
from .contracts import AgentRuntime, RuntimeEvents, TurnResult
from .adapters.anthropic import AnthropicAdapter
from .adapters.base import KNOWN_FEATURES, ProviderAdapter
from .adapters.hermes_xml import HermesXMLAdapter
from .adapters.local_llama import LocalLlamaAdapter
from .adapters.mlx import MLXAdapter
from .adapters.openai import OpenAIAdapter
from .loop.callbacks import AgentCallbacks
from .loop.interrupt import AgentInterrupted, StaleCallTimeout, interruptible_call
from .loop.jaeger_agent import JaegerAgent, SkipFinalFinalizer
from .messages import (
    AgentActivity,
    AgentRequest,
    AgentResponse,
    AgentState,
    ChatMessage,
    ChatReply,
    ModeState,
    ToolEvent,
)
from .node import MindNode, make_mind_node
from .parsing import schema_sanitizer
from .schemas.message_types import Message, Role, ToolCall
from .tool_executor import DirectToolExecutor, ToolExecutor
from .util.retry_utils import jittered_backoff, retry_with_backoff
from jaeger_os.core.tools.arg_coercion import coerce_args
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

__version__ = "1.0.0"


# ── lazy exports (PEP 562) ───────────────────────────────────────────
#
# Toolsets and prompt assembly arrived with the 0.11 move and are part
# of the public surface, but importing them HERE would be a cycle:
# tool_bundles → skill_registry.toolset_scoping, prompts → workspace →
# tools, and every one of those imports this package. Resolving on first
# attribute access keeps the graph acyclic and keeps `import
# jaeger_agent` cheap for an embedder that only wants the loop.
_LAZY = {
    "JAEGER_TOOLSETS":  ("jaeger_agent.schemas.tool_bundles", "JAEGER_TOOLSETS"),
    "list_toolsets":    ("jaeger_agent.schemas.tool_bundles", "list_toolsets"),
    "resolve_toolsets": ("jaeger_agent.schemas.tool_bundles", "resolve_toolsets"),
    "toolset_for_tool": ("jaeger_agent.schemas.tool_bundles", "toolset_for_tool"),
    "tool_visible":     ("jaeger_agent.skill_registry.toolset_scoping", "tool_visible"),
    "build_system_prompt": ("jaeger_agent.prompts.prompts", "build_system_prompt"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value  # resolved once; plain attribute after that
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    "JAEGER_TOOLSETS",
    "build_system_prompt",
    "list_toolsets",
    "resolve_toolsets",
    "tool_visible",
    "toolset_for_tool",
    "AgentActivity",
    "AgentBridge",
    "AgentCallbacks",
    "AgentInterrupted",
    "AgentRequest",
    "AgentResponse",
    "AgentRuntime",
    "AgentState",
    "AnthropicAdapter",
    "ChatMessage",
    "ChatReply",
    "DirectToolExecutor",
    "HermesXMLAdapter",
    "JaegerAgent",
    "KNOWN_FEATURES",
    "LocalLlamaAdapter",
    "MLXAdapter",
    "Message",
    "MindNode",
    "ModeState",
    "OpenAIAdapter",
    "ProviderAdapter",
    "Role",
    "RuntimeEvents",
    "SkipFinalFinalizer",
    "StaleCallTimeout",
    "ToolEvent",
    "ToolCall",
    "ToolDef",
    "ToolExecutor",
    "TurnResult",
    "clear_registry",
    "coerce_args",
    "dev_mode_enabled",
    "get_tool",
    "get_tools",
    "has_tool",
    "interruptible_call",
    "jittered_backoff",
    "make_mind_node",
    "register_tool",
    "register_tool_from_function",
    "register_tool_instance",
    "retry_with_backoff",
    "schema_sanitizer",
    "unregister_tool",
]


# ── batteries, attached ──────────────────────────────────────────────
#
# Importing this package registers its ~94 tools. That is the whole
# point of the module: `pip install jaeger-agent` should hand a project
# a working agent — files, web, code, memory, scheduling, skills, the
# lot — not a turn machine and an empty registry it has to furnish
# before anything works.
#
# It is done here, at the END of __init__, rather than lazily from
# somewhere inside the loop. A registration that happens as a SIDE
# EFFECT of some unrelated import is how you get a chat app that never
# asked for tools quietly paying 15,000 tokens of schema on every turn
# — which is exactly what an earlier cut of the turn-start hook did.
# Explicit and at import time is predictable; implicit and deferred is
# not.
#
# THE CONTEXT COST IS REAL and an embedder has to plan for it: ~94 tool
# schemas are ~15,000 tokens on every turn, so a 4096- or 8192-token
# window cannot hold the catalogue at all, let alone a conversation.
# Two ways out, and they compose:
#
#   JAEGER_TOOLSET_SCOPING=1   show a ~17-tool core set (~3,600 tokens)
#                              and let the model widen on demand —
#                              list_tools/describe_tool/load_tools are
#                              in the core set precisely so it can.
#   ctx = 16384 or more        just hold the whole catalogue.
#
# JAEGER_AGENT_NO_TOOLS=1 skips this entirely, for an embedder that
# wants the bare loop and its own tools — `jaeger_agent.tools` is still
# importable by hand afterwards.
if not os.environ.get("JAEGER_AGENT_NO_TOOLS"):
    from . import tools as _tools  # noqa: F401,E402
