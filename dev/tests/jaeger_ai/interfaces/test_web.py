from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.cli.entry import _route
from jaeger_ai.interfaces.web.server import JaegerWebServer


REPO_ROOT = Path(__file__).resolve().parents[4]


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


def test_webui_branding_extension_reuses_mac_app_icons():
    assets = REPO_ROOT / "jaeger_ai" / "assets"
    script = (assets / "jaeger_webui_branding.js").read_text(encoding="utf-8")

    for name in (
        "jaeger_app_icon_16.png",
        "jaeger_app_icon_32.png",
        "jaeger_app_icon_256.png",
    ):
        assert name in script
        assert (assets / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "apple-touch-icon" in script


def test_health_endpoint_uses_bridge_contract(tmp_path):
    server = JaegerWebServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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


def test_runner_contract_translates_streamed_chat_to_hermes_events(tmp_path):
    server = JaegerWebServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
    bridge = _Bridge()
    server.bridge = bridge
    server.chats.bridge = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        started = _post(f"{base}/v1/runs", {
            "message": "world",
            "session_id": "s1",
            "provider": "ollama",
            "model": "qwen:latest",
        })
        run_id = started["run_id"]
        deadline = time.time() + 2
        observed = {"events": []}
        while time.time() < deadline:
            with urlopen(f"{base}/v1/runs/{run_id}/events") as response:
                observed = json.load(response)
            if any(row["event"] == "done" for row in observed["events"]):
                break
            time.sleep(0.01)

        assert [row["event"] for row in observed["events"]] == [
            "token", "reasoning", "done",
        ]
        assert observed["events"][0]["payload"] == {"text": "hello "}
        assert observed["events"][-1]["payload"]["session"]["session_id"] == "s1"
        with urlopen(f"{base}/v1/runs/{run_id}") as response:
            status = json.load(response)
        assert status["status"] == "completed"
        assert status["terminal_state"] == "completed"
        assert bridge.commands == [
            ("configure_model", {"provider": "ollama", "model": "qwen:latest"}),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runner_service_does_not_serve_the_retired_custom_ui(tmp_path):
    server = JaegerWebServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
    server.bridge = _Bridge()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runner_resolves_hermes_transport_provider_from_jaeger_catalog(tmp_path):
    server = JaegerWebServer(("127.0.0.1", 0), "test", run_dir=tmp_path)

    class CatalogBridge(_Bridge):
        def query(self, what, args=None):
            if what == "model_catalog":
                return {"models": [
                    {"id": "gemma-4-26b:latest", "provider": "ollama"},
                    {"id": "glm-5.2:cloud", "provider": "ollama-cloud"},
                ]}
            return super().query(what, args)

    server.runner.bridge = CatalogBridge()
    assert server.runner._jaeger_provider("openai-api", "gemma-4-26b:latest") == "ollama"
    assert server.runner._jaeger_provider("openai-api", "glm-5.2:cloud") == "ollama-cloud"
    server.server_close()


def test_approval_broker_is_fail_closed_and_resolvable(tmp_path):
    server = JaegerWebServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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
