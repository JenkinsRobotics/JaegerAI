"""The brain — how JaegerAI uses the agent module.

    slot: mind               jaeger-agent fills it today
    consumes  /act/chat, /sense/transcript, /act/response
    produces  /sense/chat, /sense/agent_state, /sense/tool,
              /sense/activity, /sense/request

NOT OPTIONAL, unlike its siblings. JaegerAI without a voice is a chat
app; JaegerAI without a mind is nothing. ``available()`` exists for
symmetry and for a legible failure at boot — not so a surface can
gracefully offer less.

THE RUNTIME SEAM. jaeger-agent ships a config-built runtime that gives
any application a brain from a provider name and a model id. JaegerAI
does not use it: it owns instances, memory, personas, skills, and
in-process weights, so it supplies its own runtime through
``jaeger_ai.core.mind_runtime:create_runtime`` instead. Both satisfy the
same ``AgentRuntime`` protocol, which is what lets the same module serve
a 30-line robot script and this application without knowing the
difference.

So the module provides the LOOP — adapters, dialects, tool dispatch,
context guard, retries, the interrupt path. JaegerAI provides what the
loop reasons WITH: the tools in the registry, the prompt, the persona,
the memory. Neither half is useful alone, and the line between them is
the reason a robot can embed the first without inheriting the second.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.modules import installed

SLOT = "mind"

#: The exact import package integrated by this module file.
PACKAGE = "jaeger_agent"

#: JaegerAI owns the discoverable mind binding; jaeger-agent is the reusable
#: loop used behind that binding and does not register itself as an OS module.
DISCOVERY_PACKAGE = "jaeger_ai"

#: The runtime JaegerAI hands the module — its product pipeline, not
#: the module's config-built default. See the docstring above.
RUNTIME_FACTORY = "jaeger_ai.core.mind_runtime:create_runtime"

#: Topics a surface watches to follow a turn. These are owned by
#: jaeger_agent.messages rather than jaeger_os.topics — the mind's
#: contract ships with the mind.
WATCH = (
    "/act/chat",           # what was asked
    "/sense/chat",         # the reply
    "/sense/agent_state",  # idle / thinking / speaking
    "/sense/tool",         # per-tool start and finish
    "/sense/activity",     # the running commentary
)


def available() -> bool:
    return installed(PACKAGE)


def version() -> str:
    """Installed module version, or "" when absent."""
    if not available():
        return ""
    import jaeger_agent

    return str(getattr(jaeger_agent, "__version__", ""))


def ask(bus: Any, text: str, *, session: str = "") -> None:
    """Put a turn to the mind over its bus contract.

    The reply arrives on /sense/chat rather than being returned — a turn
    can take a minute and run twenty tools, so the caller subscribes
    instead of blocking.
    """
    text = (text or "").strip()
    if not text:
        return
    from jaeger_agent.messages import ChatMessage

    bus.publish(ChatMessage(text=text, source="app", session=session))


__all__ = [
    "SLOT",
    "PACKAGE",
    "DISCOVERY_PACKAGE",
    "RUNTIME_FACTORY",
    "WATCH",
    "available",
    "ask",
    "version",
]
