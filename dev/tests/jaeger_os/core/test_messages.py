"""JROS bus message vocabulary — topic contract + publish/subscribe delivery."""

from __future__ import annotations

import time

from jaeger_os.core.messages import (
    AgentState,
    ChatMessage,
    ChatReply,
    Transcript,
)
from jaeger_os.transport import InProcBus


def test_topics_follow_act_sense_convention() -> None:
    assert ChatMessage.topic == "/act/chat"      # operator → agent
    assert ChatReply.topic == "/sense/chat"      # agent → surfaces
    assert AgentState.topic == "/sense/agent_state"
    assert Transcript.topic == "/sense/transcript"


def test_chat_message_round_trips_over_the_bus() -> None:
    # 0.8 U1 dropped the ZMQ MessageRegistry (chassis-ZMQ path, unexercised
    # in production) along with app/bus/. The pass-through in-process bus
    # never needed a wire registry — it just delivers the dataclass — so
    # the meaningful contract now is publish -> subscribe delivery.
    bus = InProcBus()
    try:
        got: list[ChatMessage] = []
        bus.subscribe(ChatMessage.topic, got.append)
        sent = ChatMessage(text="hi", source="gui")
        bus.publish(sent)
        deadline = time.monotonic() + 3.0
        while not got and time.monotonic() < deadline:
            time.sleep(0.01)
        assert got and got[0] is sent
        assert got[0].text == "hi" and got[0].source == "gui"
    finally:
        bus.close()
