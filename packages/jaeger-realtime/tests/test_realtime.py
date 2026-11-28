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


def test_speech_preprocessor_first_comma_chunker_and_turn_end_judge() -> None:
    from jaeger_realtime import (
        FirstCommaChunker,
        TurnEndJudge,
        extract_visual_and_speech,
        to_speech_text,
    )

    prep = extract_visual_and_speech(
        "<think>verify servo torque</think>[joy] *smiles* Check ./src/app.py for $49.99 (looks good)!"
    )
    assert prep.expressions == ("joy",)
    assert "verify servo torque" in prep.thoughts
    assert "smiles" in prep.thoughts
    assert "src slash app dot py" in prep.spoken
    assert "49 dollars and 99 cents" in prep.spoken
    assert "*" not in prep.spoken and "[joy]" not in prep.spoken

    spoken_url = to_speech_text("Read https://docs.example.com/guide and x >= 3")
    assert "docs dot example dot com" in spoken_url
    assert "greater than or equal to" in spoken_url

    # FirstCommaChunker flushes early on first comma, then sentence boundaries (skipping 3.14)
    chunker = FirstCommaChunker(min_first_chars=12)
    c1 = chunker.feed("Checking the servos, ")
    assert len(c1) == 1 and "Checking the servos" in c1[0]
    c2 = chunker.feed("pi is roughly 3.14 and voltage is nominal. ")
    assert len(c2) == 1 and "3.14" in c2[0]
    c3 = chunker.feed("Done") + chunker.flush()
    assert c3 == ["Done"]

    # TurnEndJudge waits on trailing continuation words, completes on punctuation/silence
    judge = TurnEndJudge(base_pause_ms=1200, extended_pause_ms=3000)
    assert judge.judge("I want to check the motors and", pause_ms=1200).complete is False
    assert judge.judge("Check the motor temperature.", pause_ms=400).complete is True
    assert judge.judge("I want to check the motors and", pause_ms=3200).complete is True
