"""Human-in-the-loop: a run parked on an approval is interrupted and resumes in place."""
from types import SimpleNamespace

from jaeger_ai.core.gateway.server import JaegerGatewayApp


class _Store:
    def __init__(self, status):
        self.status = status

    def get_request(self, rid):
        return {"request_id": rid, "status": self.status}

    def mark_request_status(self, rid, status):
        self.status = status


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, sid, event, data):
        self.events.append((event, data))


def test_interrupt_then_resume_marks_and_restores_status():
    gw = SimpleNamespace(store=_Store("running"), event_bus=_Bus())
    JaegerGatewayApp._run_interrupted(gw, "s", "r", "approval_1", {"tool": "files.write", "call_id": None})
    assert gw.store.status == "awaiting_approval"
    JaegerGatewayApp._run_resumed(gw, "s", "r", "approval_1", "once")
    assert gw.store.status == "running"
    names = [e for e, _ in gw.event_bus.events]
    assert names == ["run.interrupted", "run.resumed"]
    assert gw.event_bus.events[1][1]["approved"] is True


def test_cancelling_run_is_not_reopened_by_interrupt():
    gw = SimpleNamespace(store=_Store("cancelling"), event_bus=_Bus())
    JaegerGatewayApp._run_interrupted(gw, "s", "r", "approval_1", {})
    assert gw.store.status == "cancelling"
    JaegerGatewayApp._run_resumed(gw, "s", "r", "approval_1", "deny")
    assert gw.store.status == "cancelling"
    assert gw.event_bus.events[-1][1]["approved"] is False
