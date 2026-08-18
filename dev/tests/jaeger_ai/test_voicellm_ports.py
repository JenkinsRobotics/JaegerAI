"""VoiceLLM-update ports (2026-06-12) — regression pins.

VoiceLLM is the end-to-end voice testbed; its recent review fixes are
ported here: speech-side latency timing threaded through the
transcript, short-phrase early commit, farewell detection, ♪/*
hallucination ingress filtering, and the MLX stop-marker holdback
(tested in test_mlx_adapter.py).
"""

from __future__ import annotations

import pytest


# ── farewell detection ─────────────────────────────────────────────


def test_farewell_patterns_match_common_forms():
    from jaeger_os.core.voice import is_farewell
    for text in (
        "good night", "Goodnight!", "g'night", "goodbye", "bye",
        "bye-bye", "see you later", "see ya", "catch you later",
        "talk to you later", "ttyl", "sleep well",
        "have a good day", "take care", "until next time",
        "Okay — good night, sleep well!",
    ):
        assert is_farewell(text), text


def test_farewell_rejects_ordinary_speech():
    from jaeger_os.core.voice import is_farewell
    for text in (
        "what's the weather", "tell me a story",
        "the byte order matters here",     # 'bye' must not match inside words
        "I bought a goodyear tire", "",
    ):
        assert not is_farewell(text), text


# ── ♪/* hallucination ingress filter ───────────────────────────────


def test_sound_wrapped_artifacts_are_non_speech():
    from jaeger_os.core.voice import is_non_speech_marker
    for text in ("♪ music ♪", "*coughs*", "* scissors snipping *",
                 "♪♪♪", "*sighs*."):
        assert is_non_speech_marker(text), text


def test_real_speech_still_passes_ingress():
    from jaeger_os.core.voice import is_non_speech_marker
    for text in ("play some music", "the answer is 5 * 3",
                 "(yes)", "two times three"):
        assert not is_non_speech_marker(text), text


# ── short-phrase early commit (VAD block math) ─────────────────────


def _mk_worker(**over):
    """Construct a _VadWorker with stub deps — only the block math is
    under test, no audio."""
    pytest.importorskip("webrtcvad")
    from jaeger_whisper_stt.nodes.whisper_stt.engine.two_pass.pipeline import _VadWorker
    import queue
    import threading

    class _StubMic:
        q = queue.Queue()

    params = dict(
        sample_rate=16000, frame_ms=30, vad_aggressiveness=2,
        pre_roll_ms=240, post_padding_ms=250,
        silence_hangover_ms=700, min_speech_ms=400,
        max_speech_ms=8000, barge_in_ms=200,
        short_phrase_max_ms=1500, short_phrase_hangover_ms=350,
    )
    params.update(over)
    return _VadWorker(
        _StubMic(), None, queue.Queue(), threading.Event(), **params,
    )


def test_short_phrase_knobs_compute_blocks():
    w = _mk_worker()
    assert w.silence_blocks_to_end == 700 // 30
    assert w.short_phrase_max_blocks == 1500 // 30
    assert w.short_hangover_blocks == 350 // 30


def test_short_phrase_path_disabled_with_zero():
    w = _mk_worker(short_phrase_max_ms=0)
    assert w.short_phrase_max_blocks == 0


# ── speech-side timing thread-through ──────────────────────────────


def test_transcript_topic_carries_timing_fields():
    from jaeger_os.transport import topics
    t = topics.Transcript(text="hi", speech_end_pc=12.5, stt_done_pc=12.9)
    assert t.speech_end_pc == 12.5
    assert t.stt_done_pc == 12.9
    # Defaults stay 0.0 = unknown, so engines that don't report timing
    # keep working.
    t2 = topics.Transcript(text="hi")
    assert t2.speech_end_pc == 0.0 and t2.stt_done_pc == 0.0


def test_audio_session_exposes_adapter_timing():
    from jaeger_os.core.audio.session import AudioSession

    class _StubAdapter:
        last_phrase_timing = {"speech_end": 1.0, "stt_done": 1.4}
        def set_on_speech_detected(self, cb): ...

    session = AudioSession.__new__(AudioSession)
    session.adapter = _StubAdapter()
    assert session.last_phrase_timing == {"speech_end": 1.0, "stt_done": 1.4}

    class _NoTimingAdapter:
        pass

    session.adapter = _NoTimingAdapter()
    assert session.last_phrase_timing == {}
