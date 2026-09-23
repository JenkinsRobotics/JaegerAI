"""create_runtime prefers the resident Gateway and never probes it under JAEGER_NO_ATTACH."""

from __future__ import annotations

from jaeger_ai.core.gateway.client import TurnResult
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
