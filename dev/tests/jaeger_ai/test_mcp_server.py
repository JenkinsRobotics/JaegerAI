"""JaegerAI MCP server — exposes the agent so MCP clients (Claude Code/Cursor)
drive it. Tests the tool logic without booting a model (the FastMCP wiring
is the SDK's responsibility)."""

from __future__ import annotations

import asyncio
import pytest

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

    with pytest.raises(RuntimeError, match="model exploded"):
        _run_chat(boom, object(), "x")


@pytest.mark.parametrize("result", [{"error": "model unavailable"}, {"execution_unknown": True}])
def test_bridge_failure_cannot_become_successful_reply(result):
    class Bridge:
        def turn(self, *args, **kwargs):
            return result
    with pytest.raises(RuntimeError, match="no confirmed result"):
        _bridge_chat(Bridge(), "hello")


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


def test_bridge_chat_does_not_report_halted_turn_as_success():
    class Halted(_FakeBridge):
        def turn(self, *args, **kwargs):
            return {"text": "stopped", "error": None, "halt_reason": "repeated_tool_failure"}
    with pytest.raises(RuntimeError, match="repeated_tool_failure"):
        _bridge_chat(Halted(), "research")


def test_bridge_chat_passes_request_id_as_native_turn_id():
    seen = {}

    class Bridge(_FakeBridge):
        def turn(self, text, session, **kwargs):
            seen.update(kwargs)
            return {"text": "ok", "error": None}

    assert _bridge_chat(Bridge(), "hi", session="dispatcher", request_id="ab" * 16) == "ok"
    assert seen["turn_id"] == "ab" * 16
    assert callable(seen["on_request"])


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
        "capability_inventory_tool",
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


def test_mcp_passes_explicit_tool_grant_to_bridge():
    class Bridge:
        def turn(self, message, session, **kwargs):
            assert session == 'specialist:test'
            assert kwargs['allowed_tools'] == []
            assert kwargs['turn_id'] == 'identity'
            return {'text': 'done'}
    assert _bridge_chat(Bridge(), 'task', 'specialist:test', 'identity', []) == 'done'


def test_main_stdio_attaches_to_live_bridge(monkeypatch):
    from jaeger_ai.interfaces import mcp_server

    class DummyBridge:
        def health(self):
            return {"ok": True, "instance": "jaeger-test"}

        def query(self, what, args=None):
            return {"model": "test-model"}

    ran = []

    class DummyServer:
        def run(self):
            ran.append("run")

    monkeypatch.setattr("jaeger_ai.features.webui.adapter.bridge_client.BridgeClient", lambda instance: DummyBridge())
    monkeypatch.setattr(mcp_server, "build_server", lambda client, inst, model, bridge: DummyServer())

    ret = mcp_server.main(["jaeger-test"])
    assert ret == 0
    assert ran == ["run"]


def test_main_stdio_attaches_to_gateway_when_bridge_unavailable(monkeypatch):
    from jaeger_ai.interfaces import mcp_server

    class DeadBridge:
        def health(self):
            return {"ok": False, "error": "dead socket"}

    class LiveGateway:
        def probe(self):
            return {"service": "jaeger-gateway", "all_green": True}

    ran = []

    class DummyServer:
        def run(self):
            ran.append("gw_run")

    monkeypatch.setattr("jaeger_ai.features.webui.adapter.bridge_client.BridgeClient", lambda instance: DeadBridge())
    monkeypatch.setattr("jaeger_ai.core.gateway.client.GatewayTurnClient", lambda: LiveGateway())
    monkeypatch.setattr(mcp_server, "build_server", lambda client, inst, model, gateway: DummyServer())

    ret = mcp_server.main(["jaeger-test"])
    assert ret == 0
    assert ran == ["gw_run"]


def test_main_stdio_truthful_error_when_gateway_unavailable(monkeypatch, capsys):
    from jaeger_ai.interfaces import mcp_server

    class DeadBridge:
        def health(self):
            return {"ok": False, "error": "dead socket"}

    class DeadGateway:
        def probe(self):
            raise RuntimeError("no gateway")

    monkeypatch.setattr("jaeger_ai.features.webui.adapter.bridge_client.BridgeClient", lambda instance: DeadBridge())
    monkeypatch.setattr("jaeger_ai.core.gateway.client.GatewayTurnClient", lambda: DeadGateway())

    ret = mcp_server.main(["jaeger-test"])
    assert ret == 1
    stderr = capsys.readouterr().err
    assert "Neither live bridge nor canonical Jaeger Gateway (127.0.0.1:8810) is running" in stderr
    assert "kimi-k2.7-code:cloud" not in stderr
    assert "11434" not in stderr


def test_build_server_routes_chat_through_gateway():
    from jaeger_ai.core.gateway.client import TurnResult
    from jaeger_ai.interfaces.mcp_server import build_server

    class DummyGW:
        base_url = "http://127.0.0.1:8810"
        def turn(self, session, message):
            assert session == "test_session"
            assert message == "hello gateway"
            return TurnResult(request_id="rid_1", status="completed", text="reply from gateway")

    server = build_server(None, "jaeger-test", "gateway", gateway=DummyGW())
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "chat" in tools
    assert "cancel_turn" in tools

    # Call chat
    chat_fn = server._tool_manager.get_tool("chat").fn
    out = asyncio.run(chat_fn("hello gateway", session_id="test_session"))
    assert out == "reply from gateway"
