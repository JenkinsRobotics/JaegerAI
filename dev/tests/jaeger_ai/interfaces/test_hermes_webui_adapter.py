from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from jaeger_ai.cli.entry import _route
from jaeger_ai.features.webui.adapter.server import HermesWebUIAdapterServer


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

    def turn(self, text, session, on_event=None, on_request=None, **kwargs):
        if on_event:
            on_event({"type": "delta", "text": "hello "})
            on_event({"type": "reasoning", "text": "checked"})
        return {"text": f"hello {text}"}


def test_cli_routes_hermes_webui_adapter():
    assert _route(["hermes-webui-adapter", "--port", "9999"], "/python") == [
        "/python", "-m", "jaeger_ai.features.webui.adapter", "--port", "9999"
    ]


@pytest.mark.integration
def test_health_endpoint_uses_bridge_contract(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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


class _ScheduleBridge(_Bridge):
    def __init__(self):
        super().__init__()
        self.jobs = [{
            "name": "morning",
            "cron": "0 9 * * *",
            "prompt": "Prepare my morning brief",
            "created_at": "2026-08-29T09:00:00+00:00",
            "next_run_at": "2026-08-30T16:00:00+00:00",
            "last_run_at": None,
            "cancelled": False,
            "status": "active",
            "paused": False,
        }]

    def query(self, what, args=None):
        if what == "list_schedules":
            return {"count": len(self.jobs), "schedules": list(self.jobs)}
        if what == "cron":
            return {
                "scheduler": "jaeger",
                "count": len(self.jobs),
                "jobs": list(self.jobs),
                "running": {},
            }
        if what == "heartbeat":
            return {"enabled": True, "interval_minutes": 30}
        return super().query(what, args)


@pytest.mark.integration
def test_schedule_compatibility_routes_translate_hermes_webui_contract(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
    bridge = _ScheduleBridge()
    server.bridge = bridge
    server.runner.bridge = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/v1/scheduler/status") as response:
            status = json.load(response)
        assert status == {
            "configured": True,
            "running": True,
            "owner": "jaeger",
            "scheduler": "jaeger",
            "heartbeat": {"enabled": True, "interval_minutes": 30},
        }

        with urlopen(f"{base}/v1/schedules") as response:
            payload = json.load(response)
        assert payload["jobs"] == [{
            "id": "morning",
            "name": "morning",
            "prompt": "Prepare my morning brief",
            "schedule": {"kind": "cron", "expression": "0 9 * * *"},
            "schedule_display": "0 9 * * *",
            "enabled": True,
            "state": "active",
            "created_at": "2026-08-29T09:00:00+00:00",
            "next_run_at": "2026-08-30T16:00:00+00:00",
            "last_run_at": None,
            "last_status": None,
            "deliver": "local",
            "skills": [],
            "profile": None,
            "provider": None,
            "model": None,
            "no_agent": False,
            "toast_notifications": True,
        }]

        created = _post(f"{base}/v1/schedules/create", {
            "name": "evening",
            "schedule": "0 18 * * *",
            "prompt": "Summarize today",
        })
        assert created["ok"] is True
        assert bridge.commands[-1] == (
            "create_schedule",
            {
                "name": "evening",
                "schedule": "0 18 * * *",
                "prompt": "Summarize today",
                "deliver": "local",
            },
        )

        assert _post(f"{base}/v1/schedules/morning/pause", {})["ok"] is True
        assert _post(f"{base}/v1/schedules/morning/resume", {})["ok"] is True
        assert _post(f"{base}/v1/schedules/morning/cancel", {})["ok"] is True
        assert [name for name, _args in bridge.commands[-3:]] == [
            "pause_schedule", "resume_schedule", "cancel_schedule",
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.integration
def test_runner_contract_translates_streamed_chat_to_hermes_events(tmp_path, monkeypatch):
    # The adapter probes the live serving window so configure_model does not
    # leave Ollama at its 4096 default. That probe talks to 127.0.0.1:11434
    # for real, so on a developer machine running Ollama this test picked up
    # whatever that daemon served and the command grew a context_length the
    # assertion below did not expect — green on CI, red on a dev box. Pin the
    # probe so the forwarded value is the one under test.
    from jaeger_ai.core.models import ollama_context as _oc

    monkeypatch.setattr(_oc, "resolve_serving_context",
                        lambda **kwargs: (65_536, "configured"))

    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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
        # Per-turn model and provider are now passed to bridge.turn directly
        # without mutating global bridge state via configure_model (785870d7).
        assert bridge.commands == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.integration
def test_runner_service_does_not_serve_the_retired_custom_ui(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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


@pytest.mark.integration
def test_runner_resolves_hermes_transport_provider_from_jaeger_catalog(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)

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
    assert server.runner._jaeger_provider("openai-api", "glm-5.2:cloud") == "ollama"
    server.server_close()


@pytest.mark.integration
def test_runner_uses_catalog_route_instead_of_product_lane(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)

    class CatalogBridge(_Bridge):
        def query(self, what, args=None):
            if what == "model_catalog":
                return {"models": [{
                    "id": "gemma4:latest",
                    "provider": "ollama-local",
                    "route_provider": "ollama",
                }]}
            return super().query(what, args)

    server.runner.bridge = CatalogBridge()
    try:
        assert server.runner._jaeger_provider("", "gemma4:latest") == "ollama"
    finally:
        server.server_close()


@pytest.mark.integration
def test_runner_routes_both_ollama_picker_lanes_through_mac_daemon(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
    try:
        assert server.runner._jaeger_provider("ollama-local", "gemma-4-26b:latest") == "ollama"
        assert server.runner._jaeger_provider("ollama-cloud", "glm-5.2:cloud") == "ollama"
    finally:
        server.server_close()


@pytest.mark.integration
def test_approval_broker_is_fail_closed_and_resolvable(tmp_path):
    server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
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


@pytest.mark.integration
def test_runner_start_proxies_the_gateway_and_events_stay_one_schema(tmp_path, monkeypatch):
    """The browser's run surface is a thin projection of the Gateway's turn.

    The old contract streamed bridge frames translated into Hermes events;
    that schema is retired. The run id IS the Gateway's request_id and the
    event feed IS the Gateway's durable session stream — asserted here
    against a real owned Gateway, not a mock of one.
    """
    owned = OwnedGateway(tmp_path)
    owned.start()
    try:
        monkeypatch.setenv("JAEGER_GATEWAY_URL", owned.url)
        server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            owned.request("/v1/sessions", {"session_id": "s1", "profile": "jaeger"})
            started = _post(f"{base}/v1/runs", {
                "message": "Say CONTRACT-ANSWER", "session_id": "s1",
            })
            run_id = started["run_id"]
            _, admitted = owned.request(f"/v1/sessions/s1/requests/{run_id}")
            assert admitted["request_id"] == run_id

            deadline = time.time() + 20
            observed: dict = {"events": []}
            while time.time() < deadline:
                with urlopen(f"{base}/v1/runs/{run_id}/events") as response:
                    observed = json.load(response)
                if any(row["event"].startswith("turn.") and
                       row["event"].split(".", 1)[1] in
                       {"finish", "failed", "cancelled", "unknown"}
                       for row in observed["events"]):
                    break
                time.sleep(0.05)
            assert observed["run_id"] == run_id
            finish = [row for row in observed["events"] if row["event"] == "turn.finish"]
            assert finish, observed["events"]
            payload = finish[-1]["payload"]
            assert payload.get("output") == "CONTRACT-ANSWER"
            assert payload["request_id"] == run_id

            with urlopen(f"{base}/v1/runs/{run_id}") as response:
                status = json.load(response)
            assert status["status"] == "completed"
            assert status["terminal_state"] == "completed"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    finally:
        owned.stop()


@pytest.mark.integration
def test_clarify_respond_resolves_the_gateway_form_and_unblocks_turn(tmp_path, monkeypatch):
    """A clarify card is a Gateway entity resolved exactly once (GB-033).

    The adapter reads the form's revision from the Gateway record and answers
    POST /v1/sessions/{id}/clarify/{clarify_id}; the parked turn then receives
    the answer and finishes. A second response must fail closed — the form is
    already resolved.
    """
    owned = OwnedGateway(tmp_path)
    owned.start()
    try:
        monkeypatch.setenv("JAEGER_GATEWAY_URL", owned.url)
        server = HermesWebUIAdapterServer(("127.0.0.1", 0), "test", run_dir=tmp_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            owned.request("/v1/sessions", {"session_id": "s1", "profile": "jaeger"})
            started = _post(f"{base}/v1/runs", {
                "message": "CONTRACT-CLARIFY", "session_id": "s1",
            })
            run_id = started["run_id"]

            deadline = time.time() + 20
            seen = ""
            events: list = []
            while time.time() < deadline:
                with urlopen(f"{base}/v1/runs/{run_id}/events") as response:
                    payload = json.load(response)
                events = [row for row in payload["events"]
                          if row.get("event") == "clarify.request"]
                if events:
                    break
                time.sleep(0.05)
            clarification = events[-1]["payload"]
            assert clarification["question"] == "Which environment should be used?"
            assert clarification["request_id"] == run_id
            clarify_id = str(clarification["clarify_id"])
            revision = int(clarification["revision"])

            respond = _post(
                f"{base}/v1/runs/{run_id}/clarifications/{clarify_id}/respond",
                {"response": "staging"},
            )
            assert respond["ok"] is True, respond
            assert respond["revision"] == revision
            assert respond["delivered"] is True

            form = owned.request(f"/v1/sessions/s1/clarify?clarify_id={clarify_id}")[1]
            assert form["form"]["status"] == "answered"
            assert form["form"]["answer"] == "staging"

            again = _post(
                f"{base}/v1/runs/{run_id}/clarifications/{clarify_id}/respond",
                {"response": "prod"},
            )
            assert again["ok"] is False

            deadline = time.time() + 20
            output = None
            while time.time() < deadline:
                _, row = owned.request(f"/v1/sessions/s1/requests/{run_id}")
                if row["status"] in {"completed", "failed", "cancelled",
                                     "execution_unknown"}:
                    output = row
                    break
                time.sleep(0.05)
            assert output and output["status"] == "completed", output
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    finally:
        owned.stop()


