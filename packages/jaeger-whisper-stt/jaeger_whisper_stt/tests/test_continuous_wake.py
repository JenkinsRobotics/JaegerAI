from __future__ import annotations

import queue

from jaeger_whisper_stt.engine.continuous import WhisperSTTContinuous


def wake_engine() -> WhisperSTTContinuous:
    """Logic-only instance: wake commits do not need a model or microphone."""
    engine = WhisperSTTContinuous.__new__(WhisperSTTContinuous)
    engine.require_wake_word = True
    engine.wake_phrases = ("hey jaeger",)
    engine.wake_match_threshold = 0.78
    engine._state = "WAKE"
    engine._followup_deadline = 0.0
    engine._command_deadline = 0.0
    engine._committed_q = queue.Queue(maxsize=4)
    engine._output_drops = 0
    return engine


def test_wake_and_command_in_one_phrase_strips_the_wake() -> None:
    engine = wake_engine()
    engine._commit("Hey Jaeger, lights on")
    assert engine.next_phrase(timeout=0.01) == "lights on"
    assert engine._state == "WAKE"


def test_wake_only_arms_the_next_phrase_without_publishing_it() -> None:
    engine = wake_engine()
    engine._commit("hey jaeger")
    assert engine._state == "COMMAND"
    assert engine._committed_q.empty()

    engine._commit("lights on")
    assert engine.next_phrase(timeout=0.01) == "lights on"
    assert engine._state == "WAKE"


def test_unaddressed_phrase_is_not_published() -> None:
    engine = wake_engine()
    engine._commit("the television mentioned jaeger")
    assert engine._committed_q.empty()
