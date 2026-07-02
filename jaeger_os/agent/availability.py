"""Plugin readiness → tool availability wiring.

Each plugin-backed tool (``text_to_speech``, ``listen``,
``send_message``, ``browser``, ``vision_analyze``,
``image_generate``) declares which plugin it depends on via the
:data:`_TOOL_TO_PLUGIN` map below. At boot time, after every tool
has been registered, :func:`wire_availability_checks` walks the
registry and patches each declared tool's ``check_fn`` to query
that plugin's readiness.

The effect: when the model asks for its available tools, the
adapter filters through ``ToolDef.is_available()`` and hides
tools whose backing plugin is missing libraries or credentials —
no more silent failure halfway through a turn because Kokoro
wasn't installed.

This module deliberately stays declarative — the map is the spec.
Adding a new plugin-backed tool means one line in
:data:`_TOOL_TO_PLUGIN`, not a sweep across the codebase.
"""

from __future__ import annotations

from typing import Any


# Tool name → plugin name. Both sides are the agent-facing names —
# the same strings the model would see in the tool registry and
# ``list_plugins()`` output.
_TOOL_TO_PLUGIN: dict[str, str] = {
    # Voice — Kokoro TTS + Whisper STT.
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


def _make_check_fn(plugin_name: str):
    """Closure that captures ``plugin_name`` and queries readiness
    on every call. Wrapped so the closure is cheap; the actual
    work happens inside ``_plugin_ready``."""
    def _check() -> bool:
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
            tool.check_fn = _make_check_fn(plugin_name)
            wired += 1
        except Exception:  # noqa: BLE001 — non-dataclass tools just skip
            pass
    return wired


__all__ = ["wire_availability_checks", "_TOOL_TO_PLUGIN"]
