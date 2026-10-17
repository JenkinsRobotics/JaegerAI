"""Chat-study gaps: reasoning duration and persisted response parts."""
from __future__ import annotations

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _gateway(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway.store.ensure_session("s1")
    return gateway


def _events(gateway, name=None):
    rows = gateway.store.replay_events("s1", 0)["events"]
    return [e for e in rows if name is None or e["event"] == name]


def test_reasoning_done_once_per_run_with_duration(tmp_path):
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks("s1", "r1")
    callbacks.reasoning("thinking a")
    callbacks.reasoning("thinking b")
    callbacks.stream_delta("Answer")
    callbacks.reasoning("again")
    finish()
    done = _events(gateway, "turn.reasoning.done")
    assert len(done) == 2
    assert all(d["data"]["request_id"] == "r1" and d["data"]["duration_ms"] >= 0 for d in done)
    names = [e["event"] for e in _events(gateway)]
    assert names.index("turn.reasoning.done") < names.index("turn.delta")
