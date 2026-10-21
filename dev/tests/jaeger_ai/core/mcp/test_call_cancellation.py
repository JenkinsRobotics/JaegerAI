"""Stop reaches an in-flight MCP tools/call: fast return, notifications/cancelled,
client still usable; timeouts unchanged without a cancel. Isolated fixtures only."""
from __future__ import annotations

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
    from mcp.server.fastmcp import FastMCP
    marker = sys.argv[1]
    app = FastMCP("fixture")

    @app.tool()
    async def slow(seconds: float = 30) -> str:
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
def stdio_registry(tmp_path):
    from jaeger_ai.plugins.mcp.client import MCPRegistry, server_config_from_entry
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    marker = tmp_path / "marker.txt"
    reg = MCPRegistry()
    cfg = server_config_from_entry({"name": "fx", "command": sys.executable, "args": [str(script), str(marker)],
                                    "call_timeout_s": 30, "tool_timeouts_s": {"sl*": 45}})
    reg.add_server(cfg, connect_timeout=30)
    yield reg, marker, cfg
    reg.shutdown() if hasattr(reg, "shutdown") else None


def _cancel_after(event, delay):
    t = threading.Timer(delay, event.set)
    t.start()
    return t


def test_stdio_stop_returns_fast_sends_cancel_and_server_stays_usable(stdio_registry):
    reg, marker, _ = stdio_registry
    stop = threading.Event()
    t = _cancel_after(stop, 0.5)
    started = time.monotonic()
    with turn_cancellation(stop), pytest.raises(RuntimeError, match="remote outcome unconfirmed"):
        reg.call("mcp:fx/slow", {"seconds": 30})
    elapsed = time.monotonic() - started
    t.join()
    assert elapsed < 3.5, elapsed
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.read_text().strip() == "cancelled"   # server received notifications/cancelled
    assert reg._last_cancelled["fx"]["tool"] == "slow"
    out = reg.call("mcp:fx/fast", {})                    # same client, same process
    assert "ok" in json.dumps(out)


def test_stdio_timeout_unchanged_without_cancel(stdio_registry):
    reg, marker, cfg = stdio_registry
    assert cfg.timeout_for("slow") == 45 and cfg.timeout_for("fast") == 30
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        reg.call("mcp:fx/slow", {"seconds": 30}, timeout=1)
    assert 0.9 < time.monotonic() - started < 3
    with pytest.raises(RuntimeError, match="reconciliation"):   # existing lock after a timeout
        reg.call("mcp:fx/fast", {})


# ── native_mcp (gateway → Jaeger MCP HTTP) ─────────────────────────────────
class _Fake(BaseHTTPRequestHandler):
    log = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.log.append(msg)
        if msg.get("method") == "notifications/cancelled":
            self.send_response(202); self.end_headers(); return
        if msg["params"]["name"] == "slow":
            time.sleep(float(msg["params"]["arguments"].get("seconds", 5)))
        payload = json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                              "result": {"content": [{"type": "text", "text": msg["params"]["name"]}]}}).encode()
        try:
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        except OSError:
            pass


@pytest.fixture
def http_client():
    from jaeger_ai.core.gateway import native_mcp as nm
    _Fake.log = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = nm.MCPClient(f"http://127.0.0.1:{srv.server_port}/mcp", "", f"127.0.0.1:{srv.server_port}")
    c._session_id = "fx-session"
    yield nm, c
    srv.shutdown()


def test_native_stop_returns_fast_and_sends_cancelled(http_client):
    nm, c = http_client
    stop = threading.Event()
    t = _cancel_after(stop, 0.3)
    started = time.monotonic()
    with pytest.raises(nm.MCPCallCancelled) as exc:
        c.call_tool("slow", {"seconds": 4}, cancel=stop)
    t.join()
    assert time.monotonic() - started < 2.5 and exc.value.notice_sent
    call = next(m for m in _Fake.log if m.get("method") == "tools/call")
    note = next(m for m in _Fake.log if m.get("method") == "notifications/cancelled")
    assert note["params"]["requestId"] == call["id"] and "id" not in note
    assert c.call_tool("fast", {})["content"][0]["text"] == "fast"   # same client still works


def test_native_bound_turn_cancellation_is_honoured(http_client):
    nm, c = http_client
    stop = threading.Event()
    t = _cancel_after(stop, 0.3)
    with turn_cancellation(stop), pytest.raises(nm.MCPCallCancelled):
        c._execute_call("slow", {"seconds": 4})
    t.join()


def test_native_no_cancel_keeps_blocking_path_and_timeout(http_client, monkeypatch):
    nm, c = http_client
    assert c.call_tool("slow", {"seconds": 0.2})["content"][0]["text"] == "slow"
    monkeypatch.setattr(nm, "REQUEST_TIMEOUT", 0.5)
    started = time.monotonic()
    with pytest.raises(Exception) as exc:
        c.call_tool("slow", {"seconds": 3})
    assert nm._is_transient_http(exc.value) or "timed out" in str(exc.value).lower()
    assert 0.4 < time.monotonic() - started < 2
    assert not any(m.get("method") == "notifications/cancelled" for m in _Fake.log)
