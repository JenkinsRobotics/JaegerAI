"""Real local HTTP stream through the WebUI proxy, without a model or operator.

These transport contracts cover reconnect cursors and incremental delivery.
The upstream is a synthetic HTTP producer, not evidence of model correctness.
"""
from __future__ import annotations

import importlib.util
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[4] / "jaeger_ai/features/webui/api/jaeger_sessions.py"


def _proxy_module():
    spec = importlib.util.spec_from_file_location("_sse_transport_proxy", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("global_stream", [False, True])
def test_reconnect_forwards_browser_cursor_without_other_browser_credentials(monkeypatch, global_stream):
    module = _proxy_module()
    seen = []
    monkeypatch.setattr(module, "_add_caller_auth", lambda req: req.add_header("X-Test-Caller", "webui"))
    monkeypatch.setattr(module, "urlopen", lambda req, **kw: seen.append(req) or io.BytesIO(b""))
    handler = SimpleNamespace(
        headers={"Last-Event-ID": "42", "Authorization": "private-browser-value", "Cookie": "private-cookie"},
        wfile=io.BytesIO(), send_response=lambda _: None,
        send_header=lambda *args: None, end_headers=lambda: None,
    )
    kwargs = {"upstream_path": "/v1/events/stream"} if global_stream else {}
    assert module._proxy_stream(handler, "session", "", **kwargs)
    assert seen[0].get_header("Last-event-id") == "42"
    assert seen[0].get_header("X-test-caller") == "webui"
    assert seen[0].get_header("Authorization") is None
    assert seen[0].get_header("Cookie") is None


def test_proxy_flushes_first_event_before_upstream_finishes(monkeypatch):
    module = _proxy_module()
    first = b"id: 1\nevent: turn.delta\ndata: first\n\n"
    second = b"id: 2\nevent: turn.finish\ndata: done\n\n"
    release = threading.Event()
    received = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            if release.wait(3):
                self.wfile.write(second)
                self.wfile.flush()

        def log_message(self, *args):
            pass

    class Output(io.BytesIO):
        def flush(self):
            if first in self.getvalue():
                received.set()
            super().flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    monkeypatch.setattr(module, "gateway_base", lambda: f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(module, "_add_caller_auth", lambda req: None)
    output = Output()
    handler = SimpleNamespace(headers={}, wfile=output, send_response=lambda _: None,
                              send_header=lambda *args: None, end_headers=lambda: None)
    pumping = threading.Thread(target=module._proxy_stream, args=(handler, "session", ""), daemon=True)
    try:
        pumping.start()
        assert received.wait(2), "first event was buffered until producer completion"
        assert pumping.is_alive(), "producer should still be waiting before terminal event"
        release.set()
        pumping.join(3)
        assert not pumping.is_alive()
        assert output.getvalue() == first + second
    finally:
        release.set()
        pumping.join(3)
        server.shutdown()
        server.server_close()
        serving.join(3)
