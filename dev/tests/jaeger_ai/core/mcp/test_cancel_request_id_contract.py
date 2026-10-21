"""Stop → MCP cancel contract. Isolated fixtures only (no live MCP, no ~/.jaeger).

1. The request id taken from the SDK's private ``ClientSession._request_id`` must be
   the JSON-RPC id the server actually received; an SDK change must fail here loudly.
2. If that id is unavailable (None), no cancel notice is sent and the server falls
   back to the reconciliation lock.
3. The gateway's native lead turn binds the request's Stop event, and runs unbound
   (old blocking path) when the request has no cancellation scope."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import textwrap
import threading
import time

import pytest

from jaeger_agent.core.cancellation import turn_cancellation

SERVER = textwrap.dedent('''
    import sys, anyio
    from mcp.server.fastmcp import FastMCP, Context
    marker = sys.argv[1]
    app = FastMCP("fixture")

    @app.tool()
    async def slow_echo_id(ctx: Context, seconds: float = 30) -> str:
        """Harmless slow test tool: records the request id it was called with, then sleeps."""
        open(marker, "a").write(f"id={ctx.request_id}\\n")
        try:
            await anyio.sleep(seconds)
            return "finished"
        except BaseException:
            open(marker, "a").write("cancelled\\n")
            raise

    @app.tool()
    async def fast() -> str:
        return "ok"

    app.run("stdio")
''')


@pytest.fixture
def registry(tmp_path):
    from jaeger_ai.plugins.mcp.client import MCPRegistry, server_config_from_entry
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    marker = tmp_path / "marker.txt"
    reg = MCPRegistry()
    reg.add_server(server_config_from_entry({"name": "fx", "command": sys.executable,
                                             "args": [str(script), str(marker)], "call_timeout_s": 30}),
                   connect_timeout=30)
    yield reg, marker
    reg.shutdown() if hasattr(reg, "shutdown") else None


def _wait_for(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _stop_during(reg, tool, args, delay=0.5):
    stop = threading.Event()
    timer = threading.Timer(delay, stop.set)
    timer.start()
    try:
        with turn_cancellation(stop), pytest.raises(RuntimeError, match="remote outcome unconfirmed"):
            reg.call(tool, args)
    finally:
        timer.join()


def test_captured_request_id_is_the_id_the_server_received(registry):
    reg, marker = registry
    _stop_during(reg, "mcp:fx/slow_echo_id", {"seconds": 30})
    assert _wait_for(lambda: marker.exists() and "cancelled" in marker.read_text())
    received = next(line[3:] for line in marker.read_text().splitlines() if line.startswith("id="))
    captured = reg._last_cancelled["fx"]["request_id"]
    assert captured is not None, "SDK no longer exposes ClientSession._request_id; update _MCPClient.call"
    assert str(captured) == received, (
        f"captured id {captured!r} != server-received id {received!r}: the SDK changed how ids are "
        "assigned, so notifications/cancelled would target the wrong request")


def test_no_request_id_sends_no_notice_and_falls_back_to_reconciliation_lock(registry, monkeypatch):
    from jaeger_ai.plugins.mcp import client as mcp_client
    reg, marker = registry
    original = mcp_client._MCPClient.call
    notices = []

    async def call_without_id(self, tool_name, arguments, inflight=None):
        if inflight is not None:
            inflight["request_id"] = None
        return await original(self, tool_name, arguments, None)

    async def record_cancel(self, request_id, reason):
        notices.append(request_id)

    monkeypatch.setattr(mcp_client._MCPClient, "call", call_without_id)
    monkeypatch.setattr(mcp_client._MCPClient, "cancel_request", record_cancel)
    _stop_during(reg, "mcp:fx/slow_echo_id", {"seconds": 30})
    assert notices == []
    assert "fx" not in reg._last_cancelled
    with pytest.raises(RuntimeError, match="reconciliation"):
        reg.call("mcp:fx/fast", {})


# ── gateway native lead turn ───────────────────────────────────────────────
class _ChatServer(BaseHTTPRequestHandler):
    log: list = []
    delay = 0.0

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _ChatServer.log.append(msg)
        if msg.get("method") == "notifications/cancelled":
            self.send_response(202); self.end_headers(); return
        time.sleep(_ChatServer.delay)
        payload = json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                              "result": {"content": [{"type": "text", "text": "reply"}]}}).encode()
        try:
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        except OSError:
            pass


@pytest.fixture
def lead(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway import native_mcp as nm
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    _ChatServer.log = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ChatServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    bound = []

    class FixtureClient(nm.MCPClient):
        def initialize(self):
            self._session_id = "fx-session"

        def list_tools(self):
            return [{"name": "jaeger_chat"}]

        def _execute_call(self, name, arguments, **kw):
            bound.append(nm._bound_cancellation())
            return super()._execute_call(name, arguments, **kw)

    monkeypatch.setattr(nm, "MCPClient", FixtureClient)
    monkeypatch.setattr(nm, "MCP_URL", f"http://127.0.0.1:{srv.server_port}/mcp")
    monkeypatch.setattr(nm, "mcp_api_key", lambda: "")
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "lead.sqlite3"))
    yield app, bound
    srv.shutdown()


def test_native_lead_turn_binds_the_request_stop_event(lead):
    app, bound = lead
    _ChatServer.delay = 5.0
    scope = app._cancellations.register("rq-stop")
    timer = threading.Timer(0.3, scope.cancel)
    timer.start()
    started = time.monotonic()
    result = asyncio.run(app._native_lead_turn("s", "hi", request_id="rq-stop"))
    timer.join()
    assert result is None                          # unconfirmed, not retried
    assert time.monotonic() - started < 2.5
    assert bound == [scope.event]
    call = next(m for m in _ChatServer.log if m.get("method") == "tools/call")
    note = next(m for m in _ChatServer.log if m.get("method") == "notifications/cancelled")
    assert note["params"]["requestId"] == call["id"]


@pytest.mark.parametrize("request_id", [None, "rq-unregistered"])
def test_native_lead_turn_without_a_scope_runs_unbound(lead, request_id):
    app, bound = lead
    _ChatServer.delay = 0.0
    assert asyncio.run(app._native_lead_turn("s", "hi", request_id=request_id))[0] == "reply"
    assert bound == [None]
    assert not any(m.get("method") == "notifications/cancelled" for m in _ChatServer.log)
