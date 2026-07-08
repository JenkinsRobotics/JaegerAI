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
    module since 0.8 M1, not a plugin) are gated on module
    discovery instead, and the plugin path stays exercised via a
    real remaining plugin-backed tool (``listen`` / ``whisper_stt``)
"""

from __future__ import annotations

from pydantic import BaseModel

from jaeger_os.agent.schemas.tool_schema import ToolDef
from jaeger_os.agent.availability import (
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
    """Every name in ``_TOOL_TO_PLUGIN`` should pick up a check_fn
    after the wiring pass. Other tools are untouched (default = always
    available)."""
    tools = {
        "text_to_speech":   _td("text_to_speech"),
        "listen":           _td("listen"),
        "send_message":     _td("send_message"),
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

    Uses ``listen``/``whisper_stt`` (a real remaining plugin) —
    ``text_to_speech`` moved to module-gating in 0.8 M1 (see the
    module-discovery tests below) so it no longer exercises this
    path against the real repo."""
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    # Patch the plugin lister to report whisper_stt as not ready.
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "whisper_stt", "status": "needs_install"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["listen"].is_available() is False


def test_ready_plugin_keeps_tool_available(monkeypatch):
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "whisper_stt", "status": "ready"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["listen"].is_available() is True


def test_messaging_aggregates_across_bridges(monkeypatch):
    """``send_message`` is gated on the synthetic ``messaging``
    plugin name — True iff ANY of discord/telegram/imessage is
    ready, so the tool stays usable when at least one bridge is
    configured."""
    tools = {"send_message": _td("send_message")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list_no_bridge():
        return {"plugins": [
            {"name": "discord", "status": "needs_credentials"},
            {"name": "telegram", "status": "needs_install"},
            {"name": "imessage", "status": "needs_install"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list_no_bridge)
    assert tools["send_message"].is_available() is False

    def _fake_list_one_ready():
        return {"plugins": [
            {"name": "discord", "status": "ready"},
            {"name": "telegram", "status": "needs_install"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list_one_ready)
    assert tools["send_message"].is_available() is True


def test_unknown_plugin_fails_open(monkeypatch):
    """A tool whose declared plugin isn't in the list_plugins
    output (e.g. someone added a tool mapping but the plugin
    isn't bundled yet) defaults to AVAILABLE — don't punish
    forward compatibility."""
    tools = {"listen": _td("listen")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list_empty():
        return {"plugins": []}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list_empty)
    assert tools["listen"].is_available() is True


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
    from jaeger_os.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["text_to_speech"].is_available() is False


def test_text_to_speech_available_when_module_present_and_libs_importable(
    monkeypatch,
):
    """A discovered module claiming ``text_to_speech`` with every
    declared ``requires_libraries`` entry importable is available."""
    from jaeger_os.agent import availability as _avail_mod
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
    from jaeger_os.agent import availability as _avail_mod
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
    from jaeger_os.agent import availability as _avail_mod

    monkeypatch.setattr(_avail_mod, "_discovered_modules", lambda: [])
    tools = {"speak": _td("speak"), "warm_kokoro": _td("warm_kokoro")}
    wire_availability_checks(_StubAgent(tools))
    assert tools["speak"].is_available() is False
    assert tools["warm_kokoro"].is_available() is False
