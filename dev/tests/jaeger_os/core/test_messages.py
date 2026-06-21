"""JROS bus message vocabulary — topic contract + wire round-trip."""

from __future__ import annotations

from jaeger_os.core.messages import (
    MESSAGES,
    AgentState,
    ChatMessage,
    ChatReply,
    Transcript,
)


def test_topics_follow_act_sense_convention() -> None:
    assert ChatMessage.topic == "/act/chat"      # operator → agent
    assert ChatReply.topic == "/sense/chat"      # agent → surfaces
    assert AgentState.topic == "/sense/agent_state"
    assert Transcript.topic == "/sense/transcript"


def test_registry_round_trips_a_chat_message() -> None:
    payload = MESSAGES.encode(ChatMessage(text="hi", source="gui"))
    out = MESSAGES.decode("/act/chat", payload)
    assert isinstance(out, ChatMessage)
    assert out.text == "hi"
    assert out.source == "gui"


def test_unregistered_topic_decodes_to_rawmessage_not_drop() -> None:
    # A missing registration is visible, not silently dropped.
    from jaeger_os.app.bus.api import RawMessage
    out = MESSAGES.decode("/act/unknown", b'{"foo": 1}')
    assert isinstance(out, RawMessage)
    assert out.topic == "/act/unknown"
