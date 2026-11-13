"""backlog.updated is coalesced so it cannot flood the stream."""
from jaeger_ai.core.gateway.event_bus import GatewayEventBus


def _row(task_id, action="sweep.flagged", status="open"):
    return {"task_id": task_id, "action": action, "status": status, "reasons": ["stale"]}


def test_identical_backlog_updates_are_coalesced():
    bus = GatewayEventBus()
    first = bus.publish("*", "backlog.updated", _row("t1"))
    again = bus.publish("*", "backlog.updated", _row("t1"))
    assert again.event_id == first.event_id
    changed = bus.publish("*", "backlog.updated", _row("t1", status="done"))
    assert changed.event_id != first.event_id
    assert bus.throttle_stats()["backlog.updated"] == 1


def test_backlog_updates_are_capped_per_minute_but_other_events_are_not():
    bus = GatewayEventBus()
    ids = {bus.publish("*", "backlog.updated", _row(f"t{i}")).event_id for i in range(100)}
    assert len(ids) == 20
    tool_ids = {bus.publish("s", "tool.started", {"call_id": str(i)}).event_id for i in range(50)}
    assert len(tool_ids) == 50
