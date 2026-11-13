"""Inner-helper lifecycle: exactly one terminal delegate span per helper."""
from types import SimpleNamespace

from jaeger_ai.core.gateway.server import JaegerGatewayApp


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, session_id, event, data):
        self.events.append((session_id, event, data))


def _fake_gateway():
    bus = _Bus()
    gw = SimpleNamespace(event_bus=bus)
    gw._origin_turn = lambda record: ("s1", "r1")
    gw._step_for_call = lambda sid, call_id: None
    return gw, bus


def _record(status):
    return {"id": "handoff_x", "status": status, "to_agent_id": "native:design",
            "metadata": {"collaboration": "delegate", "call_id": "tool_1"}, "result": {}}


def test_terminal_delegate_event_is_emitted_once():
    gw, bus = _fake_gateway()
    JaegerGatewayApp._publish_delegate(gw, "agent.handoff", _record("running"))
    JaegerGatewayApp._publish_delegate(gw, "agent.handoff.finished", _record("cancelled"))
    JaegerGatewayApp._publish_delegate(gw, "agent.handoff.finished", _record("failed"))
    JaegerGatewayApp._publish_delegate(gw, "agent.handoff", _record("running"))
    names = [e for s, e, _ in bus.events if s == "s1"]
    assert names == ["delegate.started", "delegate.failed"]


def test_completed_helper_emits_finished():
    gw, bus = _fake_gateway()
    JaegerGatewayApp._publish_delegate(gw, "agent.handoff.finished", _record("completed"))
    assert [e for s, e, _ in bus.events if s == "s1"] == ["delegate.finished"]
