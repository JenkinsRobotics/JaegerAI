"""The brain — how JaegerAI uses the agent module.

    slot: mind               jaeger-agent fills it today
    consumes  /act/chat, /sense/stt/transcript, /act/response
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

import os

from typing import Any

from jaeger_ai.modules import installed

SLOT = "mind"

#: The exact import package integrated by this module file.
PACKAGE = "jaeger_agent"

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


#: The module's own opt-out, read at import time. Set it BEFORE anything
#: imports jaeger_agent — module discovery imports every installed
#: package to read its manifest, so a node booting is already too late.
NO_TOOLS_ENV = "JAEGER_AGENT_NO_TOOLS"


def chat_only(enabled: bool = True) -> None:
    """Ask for the bare loop, before anything imports the package.

    ``setdefault``, not assignment — an operator who exported the
    variable themselves outranks this app.

    A SWITCH, NOT A WALL. ``enabled=False`` leaves the full agent
    installed: ~96 tools. JaegerAI's default is the full surface, which
    is the opposite of Mochi's default and for the opposite reason — a
    desk character wants conversation, an assistant wants capability.
    Either way it is a CHOICE this app makes, not a limit built into
    the module.
    """
    if enabled:
        os.environ.setdefault(NO_TOOLS_ENV, "1")


def set_persona(prompt: str) -> bool:
    """Re-voice the running mind. True if it took.

    Changing character has to change what the mind SOUNDS like, and it
    must not cost a model reload. It does not: the agent reads
    ``system_prompt`` per turn rather than baking it in, so both halves
    of this are assignments.

        _pipeline["system_prompt"]     seeds agents built later
        each live agent                the conversations already open

    0.11.0. The APP pushes its persona into the mind; the mind does not
    reach back for it. That direction is the whole point — embedded in
    Mochi it is Mochi's character that applies, and jaeger-agent must
    not name either app to serve both. Mirrors
    ``Mochi/modules/jaeger_agent.py``'s ``set_persona``.

    Reaching into the running objects rather than going over a topic,
    because jaeger-agent exposes no topic for it. Allowed HERE and
    nowhere else: this file is the single named place JaegerAI touches
    this provider.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return False
    try:
        from jaeger_ai import main as _app
        _app._pipeline["system_prompt"] = prompt
        live = getattr(_app, "_jaeger_agents_by_session", None) or {}
        for agent in list(live.values()):
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
    except Exception:  # noqa: BLE001 — a voice change never kills a turn
        return False
    return True


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
    "RUNTIME_FACTORY",
    "WATCH",
    "available",
    "ask",
    "version",
]
