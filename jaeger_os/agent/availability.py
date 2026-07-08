"""Plugin/module readiness → tool availability wiring.

Each plugin-backed tool (``listen``, ``send_message``, ``browser``,
``vision_analyze``, ``image_generate``) declares which plugin it
depends on via the :data:`_TOOL_TO_PLUGIN` map below. At boot time,
after every tool has been registered, :func:`wire_availability_checks`
walks the registry and patches each declared tool's ``check_fn`` to
query that plugin's readiness.

The effect: when the model asks for its available tools, the
adapter filters through ``ToolDef.is_available()`` and hides
tools whose backing plugin is missing libraries or credentials —
no more silent failure halfway through a turn because a plugin
wasn't installed.

Since 0.8 M1, ``kokoro_tts`` graduated from a plugin to a core
engine-module (``jaeger_os/nodes/kokoro_tts/``, declared via
``module.yaml``) — it no longer shows up in ``list_plugins()``, so
its tools are gated on module *discovery* instead:
``text_to_speech`` is available iff a discovered module declares it
in its ``tools:`` list; the internal helpers ``speak`` and
``warm_kokoro`` (not agent-facing names in module.yaml, so not
listed there) are gated on the ``kokoro_tts`` module's mere presence
in :data:`_MODULE_PRESENCE_TOOLS`. :func:`_module_ready` runs first
for every check; only when no module claims the tool does the check
fall back to the plugin mechanism below — this is what closes the
fail-open regression where losing the ``kokoro_tts`` *plugin*
entry made these tools "available" for the wrong reason (unknown
plugin = fail open) rather than because the engine is actually
there.

This module deliberately stays declarative — the maps are the spec.
Adding a new plugin-backed tool means one line in
:data:`_TOOL_TO_PLUGIN`, not a sweep across the codebase.
"""

from __future__ import annotations

from typing import Any


# Tool name → plugin name. Both sides are the agent-facing names —
# the same strings the model would see in the tool registry and
# ``list_plugins()`` output.
_TOOL_TO_PLUGIN: dict[str, str] = {
    # Voice — Kokoro TTS (now module-gated, see _MODULE_PRESENCE_TOOLS
    # and _module_ready below; these plugin-name entries are the
    # fallback and stay for documentation / belt-and-suspenders) +
    # Whisper STT (still a real plugin).
    "text_to_speech": "kokoro_tts",
    "speak":          "kokoro_tts",     # legacy alias
    "warm_kokoro":    "kokoro_tts",
    "listen":         "whisper_stt",
    # Messaging — discord / telegram / imessage. ``send_message``
    # is generic; it's gated on ANY messaging plugin being ready
    # (separate from per-bridge availability which the tool checks
    # at call time).
    "send_message":   "messaging",
    # MCP — dynamically registered tools.
    # (MCP tools name themselves ``mcp:<server>/<tool>``; the
    # generic wiring below catches them automatically by prefix.)
}


# Plugin → optional env / dep override. Empty here today; the
# default behaviour just calls into ``list_plugins()`` and reads
# the ``status`` field for that plugin. Override entries let a
# specific tool widen or narrow the readiness gate (e.g. a tool
# that only needs `discord.py` regardless of token).
_PLUGIN_READY_OVERRIDES: dict[str, list[str]] = {}


# Tool name → owning module name, for tools that are internal
# helpers around a module rather than the agent-facing name declared
# in that module's ``module.yaml`` ``tools:`` list. ``speak`` and
# ``warm_kokoro`` are voice-loop internals, not something the model
# calls directly, so kokoro_tts's module.yaml only lists
# ``text_to_speech`` — keeping module.yaml honest about what it
# actually exposes to the agent. Gating these two on the module's
# mere presence in discovery is the cleaner alternative to padding
# module.yaml with names nobody calls.
_MODULE_PRESENCE_TOOLS: dict[str, str] = {
    "speak": "kokoro_tts",
    "warm_kokoro": "kokoro_tts",
}


def _discovered_modules() -> list[Any]:
    """Every :class:`~jaeger_os.core.modules.ModuleSpec` found under
    the default modules root. Never raises — discovery must never
    crash the availability gate; a broken module just falls back to
    the plugin mechanism (or the schema default) for its tools."""
    try:
        from jaeger_os.core.modules import discover_modules
        modules = discover_modules()
    except Exception:  # noqa: BLE001 — discovery must never crash the gate
        return []
    return [spec for specs in modules.values() for spec in specs]


def _module_ready(tool_name: str) -> bool | None:
    """True/False if a discovered module accounts for ``tool_name``;
    ``None`` if no module claims it, meaning the caller should fall
    back to the plugin mechanism.

    A tool is claimed by a module either because the module declares
    it in its own ``tools:`` list (the agent-facing case, e.g.
    ``text_to_speech`` via kokoro_tts's module.yaml), or — for
    internal helpers in :data:`_MODULE_PRESENCE_TOOLS` — because the
    owning module was discovered at all."""
    modules = _discovered_modules()
    for spec in modules:
        if tool_name in spec.tools:
            return True
    owning_module = _MODULE_PRESENCE_TOOLS.get(tool_name)
    if owning_module is not None:
        return any(spec.module == owning_module for spec in modules)
    return None


def _plugin_ready(plugin_name: str) -> bool:
    """Query ``list_plugins()`` and return True iff the named
    plugin is ``status == "ready"`` AND the platform supports it.

    The synthetic ``"messaging"`` plugin name resolves to
    "any of discord / telegram / imessage is ready" — that's the
    correct gate for the generic ``send_message`` tool."""
    try:
        from jaeger_os.agent.tools.plugins import list_plugins
        report = list_plugins() or {}
    except Exception:  # noqa: BLE001 — listing must never crash the gate
        return True   # fail-open: don't hide tools because the gate broke
    rows = report.get("plugins") or []
    if plugin_name == "messaging":
        for row in rows:
            if (row.get("name") in ("discord", "telegram", "imessage")
                    and row.get("status") == "ready"):
                return True
        return False
    for row in rows:
        if row.get("name") == plugin_name:
            return row.get("status") == "ready"
    # Plugin not in the list = unknown plugin. Fail-open — don't
    # hide a tool because we don't know about its backing plugin.
    return True


def _make_check_fn(tool_name: str, plugin_name: str):
    """Closure that captures ``tool_name`` + ``plugin_name`` and
    queries readiness on every call. Module discovery is consulted
    first (:func:`_module_ready`) since it's authoritative for
    module-owned tools like ``text_to_speech``; only when no module
    claims the tool does this fall back to the plugin mechanism."""
    def _check() -> bool:
        module_result = _module_ready(tool_name)
        if module_result is not None:
            return module_result
        return _plugin_ready(plugin_name)
    return _check


def wire_availability_checks(agent: Any) -> int:
    """Walk ``agent``'s tool registry and patch ``check_fn`` on
    every declared plugin-backed tool. Returns the number of tools
    actually wired (others fall through to the schema's default —
    "always available").

    Called once at boot, after every tool is registered. Safe to
    call multiple times — re-wiring just overwrites the same
    closure."""
    wired = 0
    try:
        tools = getattr(agent, "_function_toolset", None)
        if tools is None:
            return 0
        registered = tools.tools if hasattr(tools, "tools") else {}
    except Exception:  # noqa: BLE001
        return 0
    for name, tool in list(registered.items()):
        plugin_name = _TOOL_TO_PLUGIN.get(name)
        # MCP prefix — every ``mcp:server/tool`` is gated on the
        # MCP plugin being ready (the user's MCP servers may have
        # their own readiness; that gets checked at call time).
        if plugin_name is None and name.startswith("mcp:"):
            plugin_name = "mcp"
        if plugin_name is None:
            continue
        try:
            tool.check_fn = _make_check_fn(name, plugin_name)
            wired += 1
        except Exception:  # noqa: BLE001 — non-dataclass tools just skip
            pass
    return wired


__all__ = ["wire_availability_checks", "_TOOL_TO_PLUGIN"]
