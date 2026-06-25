"""Live activity stream — the emit path (message + config + bus adapter).

The render side is Qt (manual), but the data path is unit-testable: the
AgentActivity message, the display.activity_trace setting, and the bridge's
event adapter forwarding agent.activity onto the chassis bus.
"""

from jaeger_os.agent.loop.bridge import _BusEventAdapter
from jaeger_os.core.instance.schemas import DisplayConfig
from jaeger_os.core.messages import AgentActivity


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, msg) -> None:
        self.published.append(msg)


def test_agent_activity_message_shape() -> None:
    a = AgentActivity(kind="tool", text="setup_plugin", session="s")
    assert a.topic == "/sense/activity"
    assert a.kind == "tool" and a.text == "setup_plugin" and a.session == "s"


def test_activity_trace_setting_default_and_parse() -> None:
    assert DisplayConfig().activity_trace == "full"
    for v in ("full", "summary", "clear", "off"):
        assert DisplayConfig(activity_trace=v).activity_trace == v


def test_adapter_forwards_agent_activity_with_session() -> None:
    bus = _FakeBus()
    ad = _BusEventAdapter(bus)
    ad.current_session = "sess1"
    ad.publish("agent.activity", kind="thinking", text="[retrying once]")
    assert len(bus.published) == 1
    m = bus.published[0]
    assert isinstance(m, AgentActivity)
    assert m.kind == "thinking"
    assert m.text == "[retrying once]"
    assert m.session == "sess1"   # tagged with the bridge's current turn


def test_adapter_ignores_unknown_events() -> None:
    bus = _FakeBus()
    _BusEventAdapter(bus).publish("something.else", foo=1)
    assert bus.published == []
