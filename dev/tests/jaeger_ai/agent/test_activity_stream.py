"""Live activity stream — the emit path (message + config + bus adapter).

The render side is Qt (manual), but the data path is unit-testable: the
AgentActivity message, the display.activity_trace setting, and the bridge's
event adapter forwarding agent.activity onto the chassis bus.
"""

from jaeger_ai.core.instance.schemas import DisplayConfig
from jaeger_ai.core.messages import AgentActivity


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




