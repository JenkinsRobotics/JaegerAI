"""Tests for standalone jaeger-realtime package."""

from __future__ import annotations

from jaeger_realtime import AmbientSpeechGate, RealtimeVoiceSession


def test_ambient_speech_gate_and_barge_in() -> None:
    barge_ins: list[str] = []
    session = RealtimeVoiceSession(gate=AmbientSpeechGate(), on_barge_in=barge_ins.append)

    # Background room chatter is ignored
    d1 = session.on_heard_transcript("pass the coffee please")
    assert d1.action == "ignore"

    # Addressing Jaeger triggers reply + interrupts active speech (barge-in!)
    session.begin_speaking()
    d2 = session.on_heard_transcript("Hey Jaeger stop and check the build")
    assert d2.action == "reply"
    assert barge_ins == ["Hey Jaeger stop and check the build"]
    snap = session.snapshot()
    assert snap["barge_in_count"] == 1 and snap["speaking"] is False
