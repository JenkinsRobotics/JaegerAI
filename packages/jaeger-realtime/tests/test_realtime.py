"""Tests for standalone jaeger-realtime package."""

from __future__ import annotations

from jaeger_realtime import (
    AmbientSpeechGate,
    FirstCommaChunker,
    FullDuplexVoiceBridge,
    LLMSpeechGate,
    RealtimeVoiceSession,
    SelfSpeechFilter,
    TurnEndJudge,
    extract_visual_and_speech,
    is_farewell,
    is_hallucination,
    to_speech_text,
)


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


def test_voicellm_self_speech_filter_and_hallucination_drop() -> None:
    assert is_hallucination("[BLANK_AUDIO]") is True
    assert is_hallucination("(clicking)") is True
    assert is_hallucination("♪ music ♪") is True
    assert is_hallucination("Hey Jaeger check telemetry") is False

    echo_filter = SelfSpeechFilter(similarity_threshold=0.75, window_s=15.0)
    echo_filter.record_assistant_reply("The battery pack is at 94 percent and all servos are nominal.", now=100.0)

    # Acoustic bleed of full reply or long tail fragment is rejected
    r1 = echo_filter.check("The battery pack is at 94 percent and all servos are nominal", now=102.0)
    assert r1.is_echo is True and r1.similarity >= 0.9
    r2 = echo_filter.check("all servos are nominal", now=103.0)
    assert r2.is_echo is True and r2.reason == "substring_of_recent_reply"

    # Distinct user speech passes; expired replies no longer match
    r3 = echo_filter.check("Now rotate head left", now=104.0)
    assert r3.is_echo is False
    r4 = echo_filter.check("The battery pack is at 94 percent and all servos are nominal", now=125.0)
    assert r4.is_echo is False


def test_voicellm_streaming_llm_speech_gate_and_bridge_integration() -> None:
    # Streaming <reply> strips open & split closing tags
    gate = LLMSpeechGate(buffer_chars=24)
    chunks = [
        gate.feed("< rep"),
        gate.feed("ly >Battery is "),
        gate.feed("fully charged</rep"),
        gate.feed("ly>"),
        gate.flush(),
    ]
    assert gate.action == "reply" and gate.ignored is False
    assert "".join(chunks).strip() == "Battery is fully charged"

    # Streaming <ignore> suppresses all TTS output
    gate.reset()
    assert gate.feed("<ignore>TV announcer talking about weather") == ""
    assert gate.flush() == ""
    assert gate.action == "ignore" and gate.ignored is True

    # Untagged fallback still speaks cleanly
    gate.reset()
    out = gate.feed("All systems green without any explicit gate tag.") + gate.flush()
    assert gate.action == "reply" and gate.fallback_triggered is True
    assert "All systems green" in out

    # End-to-end bridge: hallucination drop, <ignore> suppression, echo rejection, mutual farewell
    spoken: list[str] = []
    chimes: list[str] = []

    def responder(text: str) -> str:
        low = text.lower()
        if "tv weather" in low:
            return "<ignore>"
        if "goodnight" in low:
            return "<reply>Goodnight, talk to you later!"
        return "<reply>Battery is at 98 percent and ready."

    bridge = FullDuplexVoiceBridge(
        responder=responder,
        on_tts_start=spoken.append,
        on_chime=chimes.append,
    )

    # Whisper hallucination dropped before LLM
    assert bridge.handle_utterance("[BLANK_AUDIO]", now=10.0)["action"] == "ignore"

    # Valid wake triggers reply + records self-speech + chimes
    res = bridge.handle_utterance("Hey Jaeger status?", now=11.0)
    assert res["action"] == "reply" and res["reply"] == "Battery is at 98 percent and ready."
    assert "wake" in chimes and "followup" in chimes

    # Mic picking up our own reply gets dropped as self-echo!
    echo_res = bridge.handle_utterance("Battery is at 98 percent and ready", now=12.0)
    assert echo_res["action"] == "ignore"
    assert echo_res["decision"]["reason"].startswith("self_speech_echo")
    assert bridge.session.snapshot()["echo_rejected_count"] == 1

    # Active follow-up where LLM emits <ignore> does not speak or pollute history
    ign_res = bridge.handle_utterance("TV weather forecast tonight", now=13.0)
    assert ign_res["action"] == "ignore"
    assert bridge.session.snapshot()["llm_ignored_count"] == 1
    assert len(spoken) == 1

    # Mutual farewell suppresses follow-up chime and clears follow-up window
    chimes.clear()
    bye_res = bridge.handle_utterance("Goodnight Jaeger", now=14.0)
    assert bye_res["action"] == "reply" and bye_res["end_of_conversation"] is True
    assert is_farewell(bye_res["reply"]) is True
    assert "followup" not in chimes
    # Next unaddressed remark is ignored because follow-up window closed
    after_bye = bridge.handle_utterance("just talking to myself", now=15.0)
    assert after_bye["action"] == "ignore"
