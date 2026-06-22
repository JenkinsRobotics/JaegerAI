"""JROS MCP server — exposes the agent so MCP clients (Claude Code/Cursor)
drive it. Tests the tool logic without booting a model (the FastMCP wiring
is the SDK's responsibility)."""

from __future__ import annotations

from jaeger_os.interfaces.mcp_server import _run_chat, build_server


def test_chat_returns_reply_text():
    def fake(client, message, session_key=None):
        assert session_key == "mcp"
        return {"text": f"reply:{message}", "error": None}

    assert _run_chat(fake, object(), "hello") == "reply:hello"


def test_chat_surfaces_errors():
    def boom(client, message, session_key=None):
        return {"text": "", "error": "model exploded"}

    assert "agent error: model exploded" in _run_chat(boom, object(), "x")


def test_build_server_registers_tools():
    fake = lambda c, m, session_key=None: {"text": "ok", "error": None}  # noqa: E731
    server = build_server(object(), "jros-dev", "gemma", run_turn=fake)
    assert server.name == "jros"
