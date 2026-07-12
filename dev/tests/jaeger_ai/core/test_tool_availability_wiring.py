"""Plugin/module readiness → tool availability wiring.

When a plugin isn't ready (missing libs, missing creds, wrong
platform), the tools backed by it must report ``is_available() ==
False`` so the model's schema view filters them out. Before this
wiring, the model could call ``send_message`` without Discord set
up and hit a mid-turn error.

This file pins:
  * the wiring populates ``check_fn`` on the declared tools
  * a tool whose plugin is "ready" stays available
  * a tool whose plugin is missing libs / creds becomes unavailable
  * MCP-prefixed dynamic tools route through the ``mcp`` plugin gate
  * ``text_to_speech``/``speak``/``warm_kokoro`` (kokoro_tts — a
    module since 0.8 M1) and ``listen`` (whisper_stt — a module
    since 0.8 M2b) are gated on module discovery instead; the
    generic plugin-mechanism tests below monkeypatch a synthetic
    entry into ``_TOOL_TO_PLUGIN`` since neither of those tools uses
    it anymore
  * ``send_message`` (0.8 M3b) is gated on the ``messaging`` SLOT —
    ANY-OF across every discovered module declaring
    ``slot: messaging`` (discord/telegram/imessage), fail-closed when
    none are ready or the slot is empty entirely
"""

from __future__ import annotations

import sys

from pydantic import BaseModel

from jaeger_os.core.tools.tool_schema import ToolDef
from jaeger_ai.agent.availability import (
    _TOOL_TO_PLUGIN,
    wire_availability_checks,
)


class _Args(BaseModel):
    x: int = 0


class _StubToolset:
    def __init__(self, tools): self.tools = tools


class _StubAgent:
    def __init__(self, tools): self._function_toolset = _StubToolset(tools)


def _td(name: str) -> ToolDef:
    return ToolDef(
        name=name, description=name, args_model=_Args, fn=lambda x=0: x,
    )


# ── wiring populates check_fn ──────────────────────────────────────


def test_wiring_attaches_check_fn_to_declared_tools():
    """Every name in ``_TOOL_TO_PLUGIN`` OR ``_TOOL_TO_MODULE`` should
    pick up a check_fn after the wiring pass. Other tools are
    untouched (default = always available)."""
    tools = {
        "text_to_speech":   _td("text_to_speech"),  # module (kokoro_tts)
        "listen":           _td("listen"),          # module (whisper_stt)
        "send_message":     _td("send_message"),    # slot (messaging)
        "unrelated_tool":   _td("unrelated_tool"),
    }
    wired = wire_availability_checks(_StubAgent(tools))
    assert wired == 3   # the 3 declared; unrelated_tool untouched
    assert tools["text_to_speech"].check_fn is not None
    assert tools["listen"].check_fn is not None
    assert tools["send_message"].check_fn is not None
    assert tools["unrelated_tool"].check_fn is None


def test_wiring_catches_mcp_prefixed_dynamic_tools():
    """MCP servers register tools as ``mcp:<server>/<tool>`` at
    runtime. The wiring should pick those up automatically via
    the ``mcp:`` prefix gate."""
    tools = {
        "mcp:weather/forecast": _td("mcp:weather/forecast"),
        "mcp:notion/search":    _td("mcp:notion/search"),
    }
    wired = wire_availability_checks(_StubAgent(tools))
    assert wired == 2
    assert tools["mcp:weather/forecast"].check_fn is not None


def test_wiring_is_idempotent():
    """Re-wiring an already-wired agent must not corrupt the
    closures — the second call overwrites with a fresh closure."""
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].check_fn is not None


# ── check_fn actually queries plugin readiness ────────────────────


def test_unavailable_plugin_makes_tool_unavailable(monkeypatch):
    """When ``list_plugins`` says the backing plugin needs setup,
    the wired tool's ``is_available()`` returns False.

    Neither remaining real plugin-backed tool (``send_message`` is
    gated on the aggregate ``messaging`` name, not a single plugin)
    exercises a plain single-plugin gate anymore — both ``listen``
    (0.8 M2b) and ``text_to_speech`` (0.8 M1) moved to module-gating.
    A synthetic ``_TOOL_TO_PLUGIN`` entry keeps this generic mechanism
    covered."""
    monkeypatch.setitem(_TOOL_TO_PLUGIN, "probe_tool", "probe_plugin")
    tools = {"probe_tool": _td("probe_tool")}
    wire_availability_checks(_StubAgent(tools))
    # Patch the plugin lister to report probe_plugin as not ready.
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "probe_plugin", "status": "needs_install"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["probe_tool"].is_available() is False


def test_ready_plugin_keeps_tool_available(monkeypatch):
    monkeypatch.setitem(_TOOL_TO_PLUGIN, "probe_tool", "probe_plugin")
    tools = {"probe_tool": _td("probe_tool")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "probe_plugin", "status": "ready"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["probe_tool"].is_available() is True


def test_messaging_any_of_across_modules(monkeypatch):
    """``send_message`` is gated on the ``messaging`` SLOT (0.8 M3b) —
    True iff ANY discovered module declaring ``slot: messaging`` has
    its requires met, so the tool stays usable when at least one
    bridge's library is importable, and fails closed when none are."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    discord = ModuleSpec(
        module="discord", slot="messaging", factory="pkg.mod:make",
        tools=["send_message"], requires_libraries=["discord"],
    )
    telegram = ModuleSpec(
        module="telegram", slot="messaging", factory="pkg.mod:make",
        tools=["send_message"], requires_libraries=["telegram"],
    )
    imessage = ModuleSpec(
        module="imessage", slot="messaging", factory="pkg.mod:make",
        tools=["send_message"], requires_platform=["darwin"],
    )
    monkeypatch.setattr(
        _avail_mod, "_discovered_modules",
        lambda: [discord, telegram, imessage],
    )
    monkeypatch.setattr(_avail_mod, "_library_importable", lambda name: False)
    monkeypatch.setattr(sys, "platform", "linux")
    tools = {"send_message": _td("send_message")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["send_message"].is_available() is False  # none ready

    monkeypatch.setattr(
        _avail_mod, "_library_importable", lambda name: name == "discord",
    )
    assert tools["send_message"].is_available() is True  # discord now ready


def test_unknown_plugin_fails_open(monkeypatch):
    """A tool whose declared plugin isn't in the list_plugins
    output (e.g. someone added a tool mapping but the plugin
    isn't bundled yet) defaults to AVAILABLE — don't punish
    forward compatibility."""
    monkeypatch.setitem(_TOOL_TO_PLUGIN, "probe_tool", "probe_plugin")
    tools = {"probe_tool": _td("probe_tool")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list_empty():
        return {"plugins": []}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list_empty)
    assert tools["probe_tool"].is_available() is True


# ── module discovery gates kokoro_tts tools (0.8 M1) ──────────────


def test_text_to_speech_available_when_module_discovered():
    """``text_to_speech`` is declared in the real kokoro_tts
    module.yaml's ``tools:`` list — with that module present on
    disk (as it is in this repo), the tool must be available
    regardless of the (now nonexistent) kokoro_tts *plugin*."""
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].is_available() is True


def test_text_to_speech_unavailable_when_module_missing(monkeypatch):
    """If module discovery finds no ``kokoro_tts`` module at all,
    ``text_to_speech`` must be unavailable WITHOUT any help from the
    plugin mechanism — this is the regression 0.8 M1 closes. Unlike
    an earlier version of this test, nothing here synthesizes a fake
    ``kokoro_tts`` plugin row; ``list_plugins`` is untouched (and
    genuinely has no ``kokoro_tts`` entry in this repo, since it's
    not a plugin anymore) to prove the module-owned path never falls
    through to the plugin's unknown-plugin fail-open default."""
    from jaeger_ai.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].is_available() is False


def test_text_to_speech_available_when_module_present_and_libs_importable(
    monkeypatch,
):
    """A discovered module claiming ``text_to_speech`` with every
    declared ``requires_libraries`` entry importable is available."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="kokoro_tts", slot="tts", factory="pkg.mod:make",
        tools=["text_to_speech"], requires_libraries=["kokoro"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])
    monkeypatch.setattr(_avail_mod, "_library_importable", lambda name: True)
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].is_available() is True


def test_text_to_speech_unavailable_when_required_library_missing(monkeypatch):
    """The module is discovered and claims ``text_to_speech``, but a
    library it declares in ``requires_libraries`` doesn't import
    (``find_spec`` returns ``None``) — the old code only checked
    module *presence*, so this case used to report available; the
    fix probes each required library and fails closed if any is
    missing."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="kokoro_tts", slot="tts", factory="pkg.mod:make",
        tools=["text_to_speech"], requires_libraries=["kokoro", "sounddevice"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])

    def _fake_find_spec(name):
        return None if name == "sounddevice" else object()

    monkeypatch.setattr(
        _avail_mod.importlib.util, "find_spec", _fake_find_spec,
    )
    _avail_mod._library_importable.cache_clear()
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].is_available() is False
    _avail_mod._library_importable.cache_clear()


def test_speak_and_warm_kokoro_gated_on_module_presence():
    """``speak``/``warm_kokoro`` aren't in module.yaml's ``tools:``
    list (they're internal helpers) — they're gated on the
    kokoro_tts module's mere presence instead."""
    tools = {"speak": _td("speak"), "warm_kokoro": _td("warm_kokoro")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["speak"].is_available() is True
    assert tools["warm_kokoro"].is_available() is True


def test_speak_and_warm_kokoro_unavailable_when_module_missing(monkeypatch):
    from jaeger_ai.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"speak": _td("speak"), "warm_kokoro": _td("warm_kokoro")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["speak"].is_available() is False
    assert tools["warm_kokoro"].is_available() is False


# ── module discovery gates whisper_stt tools (0.8 M2b) ────────────


def test_listen_available_when_module_discovered():
    """``listen`` is declared in the real whisper_stt module.yaml's
    ``tools:`` list — with that module present on disk (as it is in
    this repo), the tool must be available regardless of the (now
    nonexistent) whisper_stt *plugin*."""
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["listen"].is_available() is True


def test_listen_unavailable_when_module_missing(monkeypatch):
    """If module discovery finds no ``whisper_stt`` module at all,
    ``listen`` must be unavailable WITHOUT any help from the plugin
    mechanism — same regression class 0.8 M1 closed for kokoro_tts.
    ``list_plugins`` is untouched (and genuinely has no ``whisper_stt``
    entry in this repo, since it's not a plugin anymore) to prove the
    module-owned path never falls through to the plugin's
    unknown-plugin fail-open default."""
    from jaeger_ai.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["listen"].is_available() is False


def test_listen_available_when_module_present_and_libs_importable(
    monkeypatch,
):
    """A discovered module claiming ``listen`` with every declared
    ``requires_libraries`` entry importable is available."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="whisper_stt", slot="stt", factory="pkg.mod:make",
        tools=["listen"],
        requires_libraries=["pywhispercpp", "webrtcvad", "sounddevice", "numpy"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])
    monkeypatch.setattr(_avail_mod, "_library_importable", lambda name: True)
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["listen"].is_available() is True


def test_listen_unavailable_when_required_library_missing(monkeypatch):
    """The module is discovered and claims ``listen``, but a library
    it declares in ``requires_libraries`` doesn't import (``find_spec``
    returns ``None``) — fails closed rather than reporting available
    on mere module presence."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="whisper_stt", slot="stt", factory="pkg.mod:make",
        tools=["listen"], requires_libraries=["pywhispercpp", "webrtcvad"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])

    def _fake_find_spec(name):
        return None if name == "webrtcvad" else object()

    monkeypatch.setattr(
        _avail_mod.importlib.util, "find_spec", _fake_find_spec,
    )
    _avail_mod._library_importable.cache_clear()
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["listen"].is_available() is False
    _avail_mod._library_importable.cache_clear()


# ── module discovery gates animation tools (0.8 M2c) ──────────────
#
# Before 0.8 M2c, set_avatar_state/play_timeline/warm_avatar were
# UNGATED entirely — no plugin entry, no module entry, so the beta
# gate was the only thing hiding them (and warm_avatar isn't even
# beta-gated, since it's not agent-facing). Same regression class
# 0.8 M1/M2b closed for kokoro_tts/whisper_stt.


def test_avatar_tools_available_when_module_discovered():
    """The 3 avatar tools are declared in the real animation
    module.yaml's ``tools:`` list (or, for ``warm_avatar``, an
    internal helper gated the same way ``speak``/``warm_kokoro``
    are) — with that module present on disk (as it is in this
    repo), all 3 must be available."""
    tools = {
        "set_avatar_state": _td("set_avatar_state"),
        "play_timeline": _td("play_timeline"),
        "warm_avatar": _td("warm_avatar"),
    }
    wire_availability_checks(_StubAgent(tools))
    assert tools["set_avatar_state"].is_available() is True
    assert tools["play_timeline"].is_available() is True
    assert tools["warm_avatar"].is_available() is True


def test_avatar_tools_unavailable_when_module_missing(monkeypatch):
    """If module discovery finds no ``animation`` module at all, all
    3 avatar tools must be unavailable WITHOUT any help from the
    plugin mechanism — these tools have no plugin entry at all, so
    before 0.8 M2c a missing/broken module wouldn't hide them."""
    from jaeger_ai.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {
        "set_avatar_state": _td("set_avatar_state"),
        "play_timeline": _td("play_timeline"),
        "warm_avatar": _td("warm_avatar"),
    }
    wire_availability_checks(_StubAgent(tools))
    assert tools["set_avatar_state"].is_available() is False
    assert tools["play_timeline"].is_available() is False
    assert tools["warm_avatar"].is_available() is False


def test_avatar_tools_available_when_module_present_and_libs_importable(
    monkeypatch,
):
    """A discovered module claiming the avatar tools with every
    declared ``requires_libraries`` entry importable is available."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="animation", slot="animation", factory="pkg.mod:make",
        tools=["set_avatar_state", "play_timeline", "warm_avatar"],
        requires_libraries=["websockets", "PIL", "numpy"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])
    monkeypatch.setattr(_avail_mod, "_library_importable", lambda name: True)
    tools = {"set_avatar_state": _td("set_avatar_state")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["set_avatar_state"].is_available() is True



# ── plugin discovery gates homeassistant / ai_gen tools (0.8 M3a) ──
#
# Before 0.8 M3a, ha_list_entities/ha_get_state/ha_list_services/
# ha_call_service (homeassistant) and generate_image_fal/
# generate_video_fal (ai_gen) had NO entry in ``_TOOL_TO_PLUGIN`` at
# all — ``wire_availability_checks`` skipped them entirely, so they
# defaulted to "always available" regardless of HASS_TOKEN/FAL_KEY.
# Both plugins keep their real ``plugin.yaml`` (correct shape for a
# tool bundle); the fix is just the missing map entries — the actual
# readiness logic (``_plugin_ready`` → ``list_plugins()`` → real
# env/library probing) was already fail-closed for a *listed* plugin,
# it just never got consulted for these tool names.


def test_homeassistant_tools_available_when_ready(monkeypatch):
    tools = {name: _td(name) for name in (
        "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
    )}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [{"name": "homeassistant", "status": "ready"}]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    for name in tools:
        assert tools[name].is_available() is True


def test_homeassistant_tools_unavailable_when_requirements_unmet(monkeypatch):
    """Missing ``HASS_TOKEN`` (or the ``requests`` library) makes
    ``list_plugins()`` report a non-``ready`` status — the wired tools
    must fail closed rather than defaulting to available."""
    tools = {name: _td(name) for name in (
        "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
    )}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "homeassistant", "status": "needs_credentials"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    for name in tools:
        assert tools[name].is_available() is False


def test_ai_gen_tools_available_when_ready(monkeypatch):
    tools = {name: _td(name) for name in (
        "generate_image_fal", "generate_video_fal",
    )}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [{"name": "ai_gen", "status": "ready"}]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    for name in tools:
        assert tools[name].is_available() is True


def test_ai_gen_tools_unavailable_when_fal_key_missing(monkeypatch):
    """Missing ``FAL_KEY`` makes ``list_plugins()`` report
    ``needs_credentials`` — the wired tools must fail closed."""
    tools = {name: _td(name) for name in (
        "generate_image_fal", "generate_video_fal",
    )}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [{"name": "ai_gen", "status": "needs_credentials"}]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    for name in tools:
        assert tools[name].is_available() is False


def test_homeassistant_and_ai_gen_real_list_plugins_env_roundtrip(monkeypatch):
    """End-to-end through the *real* ``list_plugins()`` (no stub) —
    env present makes both plugins report ready, env absent makes
    them report a non-ready status, and the wired tool availability
    tracks that in both directions."""
    from jaeger_ai.agent.tools import plugins as _plugins_mod

    monkeypatch.delenv("HASS_TOKEN", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    # No credential store configured in this process either — patch
    # the credentials lookup out so it can't accidentally satisfy env.
    monkeypatch.setattr(
        _plugins_mod, "_credential_status", lambda names: {n: False for n in names},
    )
    tools = {
        "ha_list_entities": _td("ha_list_entities"),
        "generate_image_fal": _td("generate_image_fal"),
    }
    wire_availability_checks(_StubAgent(tools))
    assert tools["ha_list_entities"].is_available() is False
    assert tools["generate_image_fal"].is_available() is False

    monkeypatch.setenv("HASS_TOKEN", "test-token")
    monkeypatch.setenv("FAL_KEY", "test-key")
    assert tools["ha_list_entities"].is_available() is True
    assert tools["generate_image_fal"].is_available() is True


def test_avatar_tools_unavailable_when_required_library_missing(monkeypatch):
    """The module is discovered and claims the avatar tools, but a
    library it declares in ``requires_libraries`` doesn't import —
    fails closed rather than reporting available on mere module
    presence."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    spec = ModuleSpec(
        module="animation", slot="animation", factory="pkg.mod:make",
        tools=["set_avatar_state", "play_timeline", "warm_avatar"],
        requires_libraries=["websockets", "PIL", "numpy"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [spec])

    def _fake_find_spec(name):
        return None if name == "websockets" else object()

    monkeypatch.setattr(
        _avail_mod.importlib.util, "find_spec", _fake_find_spec,
    )
    _avail_mod._library_importable.cache_clear()
    tools = {"play_timeline": _td("play_timeline")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["play_timeline"].is_available() is False
    _avail_mod._library_importable.cache_clear()


# ── module discovery gates send_message via the messaging SLOT ────
# (0.8 M3b — discord/telegram/imessage graduated from plugin.yaml to
# module.yaml as the first multi-module slot; the tests above already
# cover the ANY-OF-across-real-modules shape via
# ``test_messaging_any_of_across_modules``. These pin the fail-closed
# empty-slot case and imessage's platform gate specifically.)


def test_send_message_unavailable_when_messaging_slot_empty(monkeypatch):
    """No modules discovered AT ALL (not even unready ones) — the
    ``messaging`` slot is empty, so ``send_message`` must fail
    closed, mirroring a vanished module for a single-module tool."""
    from jaeger_ai.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"send_message": _td("send_message")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["send_message"].is_available() is False


def test_imessage_module_unready_on_non_darwin_platform(monkeypatch):
    """imessage declares ``requires_platform: [darwin]`` and no
    ``requires_libraries`` at all (trivially lib-satisfied) — on a
    non-darwin host it must NOT count toward the messaging ANY-OF."""
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    imessage = ModuleSpec(
        module="imessage", slot="messaging", factory="pkg.mod:make",
        tools=["send_message"], requires_platform=["darwin"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [imessage])
    monkeypatch.setattr(sys, "platform", "linux")
    tools = {"send_message": _td("send_message")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["send_message"].is_available() is False


def test_imessage_module_ready_on_darwin_platform(monkeypatch):
    from jaeger_ai.agent import availability as _avail_mod
    from jaeger_os.core.modules import ModuleSpec

    imessage = ModuleSpec(
        module="imessage", slot="messaging", factory="pkg.mod:make",
        tools=["send_message"], requires_platform=["darwin"],
    )
    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [imessage])
    monkeypatch.setattr(sys, "platform", "darwin")
    tools = {"send_message": _td("send_message")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["send_message"].is_available() is True


def test_send_message_real_discovery_finds_three_messaging_modules():
    """No monkeypatching: the REAL ``discover_modules()`` walking the
    REAL ``jaeger_os/plugins/`` tree finds all 3 graduated messaging
    modules under the ``messaging`` slot (sanity check that the
    multi-root discovery wiring in ``core/modules.py`` actually
    reaches the wired availability gate, not just the test doubles
    above)."""
    from jaeger_ai.agent import availability as _avail_mod

    names = {
        spec.module for spec in _avail_mod._discovered_modules()
        if spec.slot == "messaging"
    }
    assert names == {"discord", "telegram", "imessage"}
