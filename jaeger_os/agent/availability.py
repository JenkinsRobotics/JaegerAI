"""Plugin/module readiness → tool availability wiring.

Each plugin-backed tool (``send_message``, ``browser``,
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
its tools (``text_to_speech``, plus the internal helpers ``speak``
and ``warm_kokoro``) are gated on module *readiness* instead, via
:data:`_TOOL_TO_MODULE` and :func:`_module_ready`. 0.8 M2b ports
``whisper_stt`` the same way — ``listen`` moved from
:data:`_TOOL_TO_PLUGIN` to :data:`_TOOL_TO_MODULE`.

A module-owned tool is judged ready iff:

  1. the owning module is actually discovered on disk (a
     ``module.yaml`` exists and parses), AND
  2. every library it declares in its own ``requires_libraries``
     (module.yaml's analogue of a plugin's ``requires: libraries:``)
     actually imports (probed via ``importlib.util.find_spec``, not
     a bare presence check on the module directory).

Crucially, :func:`_module_ready` returning ``False`` for a
module-owned tool is FINAL — it never falls back to the plugin
mechanism. That fallback is what caused the fail-open regression:
losing the ``kokoro_tts`` *plugin* entry made ``_plugin_ready``
treat it as an "unknown plugin" (fail-open by design, for forward
compatibility) rather than "engine not there" (should fail closed).
Only tools with NO module entry in :data:`_TOOL_TO_MODULE` fall
through to :func:`_plugin_ready`.

Both the module-discovery walk and the per-library import probe are
cached with :func:`functools.lru_cache` — module.yaml files and the
Python environment don't change mid-process, so re-parsing YAML and
re-importing libraries on every single availability check (every
tool-schema build, every turn) would be wasted disk/import I/O.
:func:`clear_availability_caches` drops both caches for tests or
dev hot-reload workflows.

This module deliberately stays declarative — the maps are the spec.
Adding a new plugin-backed tool means one line in
:data:`_TOOL_TO_PLUGIN`; adding a new module-backed tool means one
line in :data:`_TOOL_TO_MODULE`.
"""

from __future__ import annotations

import functools
import importlib.util
from typing import Any


# Tool name → plugin name. Both sides are the agent-facing names —
# the same strings the model would see in the tool registry and
# ``list_plugins()`` output. Module-owned tools (kokoro_tts,
# whisper_stt) are NOT listed here — see :data:`_TOOL_TO_MODULE`
# instead; a tool should be gated by exactly one mechanism.
_TOOL_TO_PLUGIN: dict[str, str] = {
    # Messaging — discord / telegram / imessage. ``send_message``
    # is generic; it's gated on ANY messaging plugin being ready
    # (separate from per-bridge availability which the tool checks
    # at call time).
    "send_message":   "messaging",
    # Home Assistant — pure agent-tool bundle (plugins/homeassistant).
    # 0.8 M3a: was absent here entirely, so wiring never touched these
    # tools and they defaulted to "always available" regardless of
    # HASS_TOKEN/requests being present — closing that fail-open hole.
    "ha_list_entities":   "homeassistant",
    "ha_get_state":       "homeassistant",
    "ha_list_services":   "homeassistant",
    "ha_call_service":    "homeassistant",
    # ai_gen — fal.ai image/video generation (plugins/ai_gen). Same
    # 0.8 M3a fix: FAL_KEY missing used to be invisible to the model.
    "generate_image_fal": "ai_gen",
    "generate_video_fal": "ai_gen",
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


# Tool name → owning module name. Covers both the agent-facing tool
# a module declares in its own ``tools:`` list (``text_to_speech``,
# ``listen``) and internal helpers around it that aren't agent-facing
# names in module.yaml (``speak``, ``warm_kokoro`` — voice-loop
# internals, not something the model calls directly). This mapping is
# what lets :func:`_module_ready` answer "unavailable" for a tool
# whose module has been removed entirely, instead of falling back to
# the plugin mechanism's fail-open default.
_TOOL_TO_MODULE: dict[str, str] = {
    "text_to_speech":   "kokoro_tts",
    "speak":            "kokoro_tts",    # legacy alias
    "warm_kokoro":      "kokoro_tts",
    "listen":           "whisper_stt",   # 0.8 M2b: plugin -> module
    "set_avatar_state": "animation",     # 0.8 M2c: was UNGATED entirely
    "play_timeline":    "animation",
    "warm_avatar":      "animation",
}


@functools.lru_cache(maxsize=1)
def _discover_modules_cached() -> tuple[Any, ...]:
    """The real discovery walk, cached for the process lifetime —
    module.yaml files don't change mid-process, so there's no need
    to re-walk ``nodes/`` and re-parse YAML on every availability
    check. Call :func:`clear_availability_caches` to force a
    re-scan (tests, dev hot-reload)."""
    try:
        from jaeger_os.core.modules import discover_modules
        modules = discover_modules()
    except Exception:  # noqa: BLE001 — discovery must never crash the gate
        return ()
    return tuple(spec for specs in modules.values() for spec in specs)


def _discovered_modules() -> list[Any]:
    """Every :class:`~jaeger_os.core.modules.ModuleSpec` found under
    the default modules root. Never raises — discovery must never
    crash the availability gate; a broken module just falls back to
    the plugin mechanism (or the schema default) for its tools."""
    return list(_discover_modules_cached())


@functools.lru_cache(maxsize=None)
def _library_importable(name: str) -> bool:
    """True iff ``name`` resolves to an importable module, probed
    via ``importlib.util.find_spec`` (no actual import — cheaper,
    and avoids running a heavy package's module-level side effects
    just to answer an availability question). Cached per name since
    this runs on every availability check."""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001 — a broken finder must not crash the gate
        return False


def clear_availability_caches() -> None:
    """Drop both the module-discovery and library-probe caches.
    Call this after monkeypatching discovery or ``find_spec`` in
    tests, or in dev workflows where modules/libraries change
    without restarting the process."""
    _discover_modules_cached.cache_clear()
    _library_importable.cache_clear()


def _requires_satisfied(spec: Any) -> bool:
    """True iff every library ``spec`` declares in its
    ``requires_libraries`` actually imports. A module with no
    declared requirements is trivially satisfied (present == ready)."""
    libraries = getattr(spec, "requires_libraries", None) or []
    return all(_library_importable(lib) for lib in libraries)


def _module_ready(tool_name: str) -> bool | None:
    """True/False if ``tool_name`` is owned by a module (per
    :data:`_TOOL_TO_MODULE`); ``None`` if it isn't, meaning the
    caller should fall back to the plugin mechanism.

    For a module-owned tool this is authoritative and FINAL — the
    caller must not fall back to :func:`_plugin_ready` regardless of
    the result. That's what keeps a removed/broken module fail-closed
    instead of degrading to the plugin mechanism's fail-open default
    for unknown plugins."""
    owning_module = _TOOL_TO_MODULE.get(tool_name)
    if owning_module is None:
        return None
    for spec in _discovered_modules():
        if spec.module == owning_module:
            return _requires_satisfied(spec)
    return False  # module-owned tool, but the module isn't discovered


def _plugin_ready(plugin_name: str) -> bool:
    """Query ``list_plugins()`` and return True iff the named
    plugin is ``status == "ready"`` AND the platform supports it.

    The synthetic ``"messaging"`` plugin name resolves to
    "any of discord / telegram / imessage is ready" — that's the
    correct gate for the generic ``send_message`` tool."""
    try:
        from jaeger_os.agent.tools.plugins import list_plugins
        report = list_plugins() or {}
    except Exception:  # noqa: BLE001
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
    queries readiness on every call. Module ownership is consulted
    first (:func:`_module_ready`) since it's authoritative and FINAL
    for module-owned tools like ``text_to_speech`` — only when the
    tool isn't module-owned at all does this fall back to the plugin
    mechanism."""
    def _check() -> bool:
        module_result = _module_ready(tool_name)
        if module_result is not None:
            return module_result
        return _plugin_ready(plugin_name)
    return _check


def wire_availability_checks(agent: Any) -> int:
    """Walk ``agent``'s tool registry and patch ``check_fn`` on
    every declared plugin- or module-backed tool. Returns the number
    of tools actually wired (others fall through to the schema's
    default — "always available").

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
        module_owned = name in _TOOL_TO_MODULE
        # MCP prefix — every ``mcp:server/tool`` is gated on the
        # MCP plugin being ready (the user's MCP servers may have
        # their own readiness; that gets checked at call time).
        if plugin_name is None and not module_owned and name.startswith("mcp:"):
            plugin_name = "mcp"
        if plugin_name is None and not module_owned:
            continue
        try:
            tool.check_fn = _make_check_fn(name, plugin_name)
            wired += 1
        except Exception:  # noqa: BLE001 — non-dataclass tools just skip
            pass
    return wired


__all__ = [
    "wire_availability_checks",
    "clear_availability_caches",
    "_TOOL_TO_PLUGIN",
    "_TOOL_TO_MODULE",
]
