from __future__ import annotations

import json
import threading
import time
from urllib.request import Request, urlopen

from jaeger_ai.cli.entry import _route
from jaeger_ai.interfaces.web.server import JaegerWebServer


class _Bridge:
    instance = "test"

    def __init__(self):
        self.commands = []

    def health(self):
        return {"ok": True, "instance": "test"}

    def query(self, what, args=None):
        return {"identity": {"display_name": "Test"}, "list_sessions": [], "model_catalog": {"models": []}}.get(what, {})

    def command(self, command, args=None):
        self.commands.append((command, args or {}))
        return {"ok": True, "command": command}

    def turn(self, text, session, on_event=None, on_request=None):
        if on_event:
            on_event({"type": "delta", "text": "hello "})
            on_event({"type": "reasoning", "text": "checked"})
        return {"text": f"hello {text}"}


def test_cli_routes_web_surface():
    assert _route(["web", "--port", "9999"], "/python") == [
        "/python", "-m", "jaeger_ai.interfaces.web", "--port", "9999"
    ]


def test_health_endpoint_uses_bridge_contract():
    server = JaegerWebServer(("127.0.0.1", 0), "test")
    server.bridge = _Bridge()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health") as response:
            assert json.load(response) == {"ok": True, "instance": "test"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(url, body):
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request) as response:
        return json.load(response)


def test_streamed_chat_and_commands_use_versioned_bridge_contract():
    server = JaegerWebServer(("127.0.0.1", 0), "test")
    bridge = _Bridge()
    server.bridge = bridge
    server.chats.bridge = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        started = _post(f"{base}/api/chat/start", {"message": "world", "session_id": "s1"})
        with urlopen(f"{base}/api/chat/stream?id={started['stream_id']}") as response:
            stream = response.read().decode()
        assert '\"type\": \"delta\"' in stream
        assert '\"type\": \"reasoning\"' in stream
        assert '\"type\": \"reply\"' in stream
        assert "event: done" in stream

        _post(f"{base}/api/models/select", {"provider": "ollama", "model": "qwen:latest"})
        _post(f"{base}/api/schedules", {"name": "daily", "schedule": "0 9 * * *", "prompt": "brief"})
        _post(f"{base}/api/schedules/pause", {"id": "daily"})
        assert bridge.commands == [
            ("configure_model", {"provider": "ollama", "model": "qwen:latest"}),
            ("create_schedule", {"name": "daily", "schedule": "0 9 * * *", "prompt": "brief"}),
            ("pause_schedule", {"id": "daily"}),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_approval_broker_is_fail_closed_and_resolvable():
    server = JaegerWebServer(("127.0.0.1", 0), "test")
    answer = []
    waiter = threading.Thread(target=lambda: answer.append(server.approvals.request({"id": "req-1", "prompt": "Run tool?"})))
    waiter.start()
    for _ in range(20):
        if server.approvals.list():
            break
        time.sleep(0.01)
    assert server.approvals.list()[0]["id"] == "req-1"
    assert server.approvals.respond("req-1", "once") is True
    waiter.join(timeout=1)
    assert answer == ["once"]
    server.server_close()
