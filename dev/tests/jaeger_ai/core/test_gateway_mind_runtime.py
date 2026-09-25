"""create_runtime prefers the resident Gateway and never probes it under JAEGER_NO_ATTACH."""

from __future__ import annotations

import pytest
from jaeger_agent.core.messages import AgentRequest, AgentResponse

from jaeger_ai.core.gateway.client import GatewayTurnClient, TurnResult
from jaeger_ai.core.mind_runtime import create_runtime
from jaeger_ai.core.runtime.gateway_runtime import GatewayRuntime


class _Client:
    def __init__(self, *args, **kwargs):
        self.turns = []

    def probe(self):
        return {"service": "jaeger-gateway", "diagnostics": {"entity_id": "entity-test"}}

    def ensure_session(self, session_id, *, title, source):
        return {"session_id": session_id}

    def stream_turn(self, session_id, text, *, on_event, **kwargs):
        self.turns.append((session_id, text))
        return TurnResult("req-1", "completed", "GATEWAY-ANSWER")

    def resolve_approval(self, approval_id, decision):
        return {}


def test_no_attach_does_not_probe_the_gateway(monkeypatch):
    monkeypatch.setenv("JAEGER_NO_ATTACH", "1")
    constructed = []

    class _Boom:
        def __init__(self, *args, **kwargs):
            constructed.append(True)
            raise AssertionError("Gateway client constructed under JAEGER_NO_ATTACH")

    class _Sentinel:
        attached = False

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("jaeger_ai.core.gateway.client.GatewayTurnClient", _Boom)
    monkeypatch.setattr("jaeger_ai.core.mind_runtime.JaegerAIRuntime", _Sentinel)
    runtime = create_runtime(bus=object(), config={"instance_name": "isolated"})
    assert isinstance(runtime, _Sentinel)
    assert constructed == []


def test_create_runtime_uses_the_gateway_instead_of_booting(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)
    monkeypatch.setattr("jaeger_ai.core.gateway.client.GatewayTurnClient", _Client)

    def boom(*args, **kwargs):
        raise AssertionError("local agent must not boot when the Gateway answers")

    monkeypatch.setattr("jaeger_ai.core.mind_runtime.JaegerAIRuntime", boom)
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.attached.try_attach_runtime",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("bridge socket must not be tried first")),
    )
    runtime = create_runtime(bus=object(), config={"instance_name": "gui"})
    assert isinstance(runtime, GatewayRuntime)
    result = runtime.run_turn("Say hello", session_key="gui")
    assert result["text"] == "GATEWAY-ANSWER"
    assert runtime.health()["implementation"] == "jaeger-ai-gateway"
    runtime.close()


class _Bus:
    """Minimal synchronous topic bus; enough to prove the approval round trip."""

    def __init__(self):
        self.subscribers = {}

    def subscribe(self, topic, callback):
        self.subscribers.setdefault(topic, []).append(callback)

    def publish(self, message):
        for callback in self.subscribers.get(message.topic, []):
            callback(message)


class _ApprovalClient:
    def __init__(self):
        self.resolved = []
        self.requests = []

    def ensure_session(self, session_id, *, title, source):
        return {"session_id": session_id}

    def stream_turn(self, session_id, text, *, on_event, **kwargs):
        self.requests.append((session_id, text))
        on_event("approval.request", {
            "approval_id": "approval_1",
            "tool": "files.write_file",
            "session_id": session_id,
            "request_id": "req-approval",
            "options": ["once", "always", "deny"],
        })
        return TurnResult("req-approval", "completed", "approved answer")

    def resolve_approval(self, approval_id, decision):
        self.resolved.append((approval_id, decision))
        return {"approval_id": approval_id, "decision": decision}


class _SteerClient:
    def __init__(self):
        self.steered = []
        self.requests = []

    def ensure_session(self, session_id, *, title, source):
        return {"session_id": session_id}

    def stream_turn(self, session_id, text, *, on_event, **kwargs):
        self.requests.append((session_id, text))
        on_event("turn.start", {"request_id": "req-steer", "session_id": session_id})
        assert self.runtime.steer("use metric units") is True
        return TurnResult("req-steer", "completed", "steered answer")

    def steer(self, session_id, request_id, steering_text):
        self.steered.append((session_id, request_id, steering_text))
        return {"steered": True, "queued": True}


def test_gateway_runtime_routes_approvals_over_the_real_bus(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)
    client = _ApprovalClient()
    bus = _Bus()
    runtime = GatewayRuntime(client, {"service": "jaeger-gateway", "diagnostics": {}})
    runtime.start(events=None, bus=bus)

    def answer(request):
        assert request.id == "approval_1"
        assert request.kind == "approval"
        assert request.options == ("once", "always", "deny")
        bus.publish(AgentResponse(id=request.id, answer="once"))

    bus.subscribe(AgentRequest.topic, answer)
    result = runtime.run_turn("write the file", session_key="approval-session")

    assert result["text"] == "approved answer"
    assert client.resolved == [("approval_1", "once")]
    assert runtime.health()["approval_status"] == "Approval resolved as once"


def test_gateway_runtime_steers_the_active_gateway_request(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)
    client = _SteerClient()
    runtime = GatewayRuntime(client, {"service": "jaeger-gateway", "diagnostics": {}})
    client.runtime = runtime
    runtime.start(events=None, bus=_Bus())

    result = runtime.run_turn("repair the login loop", session_key="steer-session")

    assert result["text"] == "steered answer"
    assert client.steered == [("steer-session", "req-steer", "use metric units")]
    assert runtime.health()["steer_status"] == "No active Gateway turn"


def test_gateway_runtime_reports_unsupported_steering_instead_of_faking_it():
    runtime = GatewayRuntime(_ApprovalClient(), {"service": "jaeger-gateway", "diagnostics": {}})
    runtime.start(events=None, bus=None)
    assert runtime.steer("late") is False
    assert runtime.health()["steer_status"] == "No active Gateway turn to steer"


def test_gateway_runtime_reports_unsupported_approvals_instead_of_hidden_deny():
    client = _ApprovalClient()
    runtime = GatewayRuntime(client, {"service": "jaeger-gateway", "diagnostics": {}})
    runtime.start(events=None, bus=None)
    runtime.run_turn("write the file", session_key="approval-session")
    assert client.resolved == [("approval_1", "deny")]
    assert runtime.health()["approval_status"] == "No approval surface available; denied"


def test_create_runtime_uses_the_explicit_bridge_diagnostic_when_gateway_is_down(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)
    monkeypatch.setattr("jaeger_ai.core.runtime.gateway_runtime.try_gateway_runtime", lambda: None)

    class _AttachedSentinel:
        attached = True

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("jaeger_ai.core.runtime.attached.try_attach_runtime", lambda **kwargs: _AttachedSentinel())

    def boom(*args, **kwargs):
        raise AssertionError("a local agent must not boot when a live bridge is explicitly reachable")

    monkeypatch.setattr("jaeger_ai.core.mind_runtime.JaegerAIRuntime", boom)
    runtime = create_runtime(bus=object(), config={"instance_name": "gui"})
    assert isinstance(runtime, _AttachedSentinel)


def test_create_runtime_fails_closed_when_no_owner_is_available(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_ATTACH", raising=False)
    monkeypatch.setattr("jaeger_ai.core.runtime.gateway_runtime.try_gateway_runtime", lambda: None)
    monkeypatch.setattr("jaeger_ai.core.runtime.attached.try_attach_runtime", lambda **kwargs: None)

    def boom(*args, **kwargs):
        raise AssertionError("a second local agent must not boot")

    monkeypatch.setattr("jaeger_ai.core.mind_runtime.JaegerAIRuntime", boom)
    with pytest.raises(RuntimeError, match="refusing to boot a second local agent"):
        create_runtime(bus=object(), config={"instance_name": "gui"})


def test_gateway_client_targets_the_request_scoped_steering_route(monkeypatch):
    client = GatewayTurnClient("http://127.0.0.1:8810")
    captured = []
    monkeypatch.setattr(
        client,
        "_call",
        lambda method, path, body: captured.append((method, path, body))
        or {"request_id": "req-1", "steered": True, "queued": True},
    )

    result = client.steer("session one", "req-1", "use metric units")

    assert result["steered"] is True
    assert captured == [(
        "POST",
        "/v1/sessions/session one/requests/req-1/steer",
        {"text": "use metric units"},
    )]
