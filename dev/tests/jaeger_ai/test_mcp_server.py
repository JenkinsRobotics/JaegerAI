"""JaegerAI MCP server — exposes the agent so MCP clients (Claude Code/Cursor)
drive it. Tests the tool logic without booting a model (the FastMCP wiring
is the SDK's responsibility)."""

from __future__ import annotations

import asyncio

from starlette.testclient import TestClient

from jaeger_ai.interfaces.mcp_server import (
    RequireBearer,
    _bridge_chat,
    _run_chat,
    build_server,
    http_app,
    parse_args,
)


def test_chat_returns_reply_text():
    def fake(client, message, session_key=None):
        assert session_key == "mcp"
        return {"text": f"reply:{message}", "error": None}

    assert _run_chat(fake, object(), "hello") == "reply:hello"


def test_chat_surfaces_errors():
    def boom(client, message, session_key=None):
        return {"text": "", "error": "model exploded"}

    assert "agent error: model exploded" in _run_chat(boom, object(), "x")


def test_chat_uses_explicit_session():
    def fake(client, message, session_key=None):
        assert session_key == "roundtable-jaeger"
        return {"text": f"reply:{message}", "error": None}

    assert _run_chat(fake, object(), "hello", session_key="roundtable-jaeger") == "reply:hello"


def test_build_server_registers_tools():
    fake = lambda c, m, session_key=None: {"text": "ok", "error": None}  # noqa: E731
    server = build_server(object(), "jaeger-dev", "gemma", run_turn=fake)
    assert server.name == "jaeger"
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"chat", "agent_info"} <= names
    assert "bridge_health" not in names


class _FakeBridge:
    def health(self):
        return {"ok": True, "instance": "jaeger-dev"}

    def query(self, what, args=None):
        if what == "list_tools":
            return {"tools": [{"name": "delegate_task"}, {"name": "chat"}]}
        if what == "identity":
            return {"instance": "jaeger-dev", "model": "gemma"}
        return {"what": what, "args": args or {}}

    def command(self, command, args=None):
        return {"command": command, "args": args or {}}

    def turn(self, text, session):
        return {"text": f"bridge:{text}:{session}", "error": None}


def test_bridge_chat_uses_session():
    assert _bridge_chat(_FakeBridge(), "hi", session="table-1") == "bridge:hi:table-1"


def test_chat_tool_declares_session_id():
    server = build_server(None, "jaeger-dev", "gemma", bridge=_FakeBridge())
    tools = asyncio.run(server.list_tools())
    chat = next(tool for tool in tools if tool.name == "chat")
    schema = getattr(chat, "inputSchema", None) or getattr(chat, "input_schema", None)
    assert schema is not None
    properties = schema.get("properties") or {}
    assert "message" in properties
    assert "session_id" in properties


def test_http_tool_list_includes_bridge_tools():
    server = build_server(None, "jaeger-dev", "gemma", bridge=_FakeBridge())
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {
        "chat",
        "agent_info",
        "bridge_health",
        "bridge_query",
        "bridge_command",
        "list_delegates",
    } <= names
    paths = [getattr(route, "path", None) for route in server.streamable_http_app().routes]
    assert "/mcp" in paths


def test_http_rejects_without_token_when_required():
    async def dummy(scope, receive, send):
        body = b"ok"
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": body})

    app = RequireBearer(dummy, "secret-token")
    client = TestClient(app)
    denied = client.post("/mcp")
    assert denied.status_code == 401
    wrong = client.post("/mcp", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    allowed = client.post("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert allowed.status_code == 200
    assert allowed.text == "ok"


def test_http_app_wraps_fastmcp_with_bearer():
    server = build_server(None, "jaeger-dev", "gemma", bridge=_FakeBridge())
    app = http_app(server, token="secret-token")
    client = TestClient(app)
    denied = client.post("/mcp")
    assert denied.status_code == 401


def test_parse_args_http_flag():
    args = parse_args(["--http", "--instance", "jaeger-dev"])
    assert args.http is True
    assert args.instance == "jaeger-dev"
    assert args.port == 8792
    stdio = parse_args(["jaeger-dev"])
    assert stdio.http is False
    assert stdio.instance_name == "jaeger-dev"
