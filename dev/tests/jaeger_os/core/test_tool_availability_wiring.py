"""Plugin readiness → tool availability wiring.

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
    the wired tool's ``is_available()`` returns False."""
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    # Patch the plugin lister to report kokoro_tts as not ready.
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "kokoro_tts", "status": "needs_install"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["text_to_speech"].is_available() is False


def test_ready_plugin_keeps_tool_available(monkeypatch):
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list():
        return {"plugins": [
            {"name": "kokoro_tts", "status": "ready"},
        ]}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list)
    assert tools["text_to_speech"].is_available() is True


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
    tools = {"text_to_speech": _td("text_to_speech")}
    wire_availability_checks(_StubAgent(tools))
    from jaeger_os.agent.tools import plugins as _plugins_mod

    def _fake_list_empty():
        return {"plugins": []}
    monkeypatch.setattr(_plugins_mod, "list_plugins", _fake_list_empty)
    assert tools["text_to_speech"].is_available() is True
