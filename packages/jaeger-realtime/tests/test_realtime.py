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


def test_directive_10_consecutive_voice_exchanges_with_barge_in() -> None:
    from jaeger_realtime import FullDuplexVoiceBridge

    cancels: list[str] = []
    spoken: list[str] = []
    bridge = FullDuplexVoiceBridge(
        responder=lambda text: f"Ack: {text}",
        on_tts_start=spoken.append,
        on_tts_cancel=cancels.append,
    )

    # Turn 1 wakes Jaeger; turns 2-10 continue naturally with 3 mid-speech barge-ins!
    utterances = [
        ("Hey Jaeger, are you listening?", False),
        ("Check the YouTube timeline", False),
        ("Wait actually switch to scene 2", True),
        ("How much free RAM do we have?", False),
        ("Stop talking and pause Minecraft", True),
        ("Look left with the gimbal camera", False),
        ("Good, now center the camera", False),
        ("Hold on, export the OTIO timeline first", True),
        ("Verify the build is green", False),
        ("Thanks, standing by", False),
    ]
    for idx, (utt, interrupt_mid_speech) in enumerate(utterances, start=1):
        res = bridge.handle_utterance(utt, in_active_dialog=(idx > 1), still_speaking=interrupt_mid_speech)
        assert res["action"] == "reply" and res["turn"] == idx

    assert len(bridge.history) == 10
    assert len(spoken) == 10
    assert len(cancels) == 3
    assert bridge.session.snapshot()["barge_in_count"] == 3
