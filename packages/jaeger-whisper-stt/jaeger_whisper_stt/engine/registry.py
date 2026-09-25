"""STT method registry — the single place that maps a method NAME to its
live-adapter factory + its bench probe.

The audio session flips methods by name (``config.stt_mode``) via
:func:`get`; the CLI bench iterates :data:`METHODS`.  Adding a method =
add a subfolder + one entry here.  Imports stay lazy so importing the
registry never pulls the model runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Method:
    name: str
    desc: str
    # (config, bus, wake_phrases) -> live STTAdapter
    make: Callable[..., Any]
    # (audio, sr, ref=None) -> BenchResult
    bench: Callable[..., Any]
    available: bool = True
    #: Does this method emit ``is_final=False`` text while the speaker is
    #: still talking?  Read by the CLI's ``list`` and by anything that
    #: wants to know whether wiring a caption pane is worth it — a
    #: consumer cannot tell from the adapter API alone, because
    #: ``set_on_partial`` simply never fires on the phrase-final methods.
    partials: bool = False
    #: Rolling word/window commits can split a wake phrase from its command,
    #: so those modes deliberately leave directed-command policy to the app.
    wake_word: bool = True


# ── live-adapter factories (mirror the kwargs core/audio/session.py uses) ──
#
# `aec` and `reference_buffer` used to be threaded through here to reach
# the mic. Both are gone: jaeger_os.nodes.audio_io owns the device and
# the canceller, and publishes cleaned frames. What a pipeline needs now
# is the one thing that actually carries audio — the bus.
def _value(config, name: str, default):
    """Read a new tuning field while retaining older JaegerOS compatibility."""
    return getattr(config, name, default)


def _make_two_pass(config, bus, wake_phrases):
    from .two_pass import WhisperSTTTwoPass
    return WhisperSTTTwoPass(
        fast_model_name=config.fast_model_name,
        accurate_model_name=config.accurate_model_name,
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        vad_aggressiveness=_value(config, "vad_aggressiveness", 2),
        pre_roll_ms=_value(config, "pre_roll_ms", 240),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        silence_hangover_ms=_value(config, "silence_hangover_ms", 700),
        min_speech_ms=_value(config, "min_speech_ms", 400),
        max_speech_ms=_value(config, "max_speech_ms", 8000),
        barge_in_ms=_value(config, "barge_in_ms", 200),
        short_phrase_max_ms=_value(config, "short_phrase_max_ms", 1500),
        short_phrase_hangover_ms=_value(
            config, "short_phrase_hangover_ms", 350),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


def _make_continuous(config, bus, wake_phrases):
    from .continuous import WhisperSTTContinuous
    return WhisperSTTContinuous(
        model_name=config.fast_model_name,
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        phrase_timeout_s=_value(
            config, "continuous_phrase_timeout_s", 1.0),
        max_phrase_s=_value(config, "continuous_max_phrase_s", 8.0),
        transcribe_every_s=_value(
            config, "continuous_transcribe_every_s", 0.6),
        min_transcribe_s=_value(
            config, "continuous_min_transcribe_s", 0.4),
        energy_threshold=_value(
            config, "continuous_energy_threshold", 0.005),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


def _make_vad_segment(config, bus, wake_phrases):
    """two_pass minus the second pass — MockingAgent's stream.py shape."""
    from .two_pass import WhisperSTTTwoPass
    return WhisperSTTTwoPass(
        fast_model_name=config.fast_model_name,
        accurate_model_name=None,
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        vad_aggressiveness=_value(config, "vad_aggressiveness", 2),
        pre_roll_ms=_value(config, "pre_roll_ms", 240),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        silence_hangover_ms=_value(config, "silence_hangover_ms", 700),
        min_speech_ms=_value(config, "min_speech_ms", 400),
        max_speech_ms=_value(config, "max_speech_ms", 8000),
        barge_in_ms=_value(config, "barge_in_ms", 200),
        short_phrase_max_ms=_value(config, "short_phrase_max_ms", 1500),
        short_phrase_hangover_ms=_value(
            config, "short_phrase_hangover_ms", 350),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


def _make_phrase_word(config, bus, wake_phrases):
    from .phrase_word import WhisperSTTPhraseWord
    return WhisperSTTPhraseWord(
        model_name=config.fast_model_name,
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        phrase_timeout_s=_value(
            config, "continuous_phrase_timeout_s", 1.0),
        max_phrase_s=_value(config, "continuous_max_phrase_s", 8.0),
        transcribe_every_s=_value(
            config, "continuous_transcribe_every_s", 0.6),
        min_transcribe_s=_value(
            config, "continuous_min_transcribe_s", 0.4),
        energy_threshold=_value(
            config, "continuous_energy_threshold", 0.005),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


def _make_window(config, bus, wake_phrases):
    from .window import WhisperSTTWindow
    return WhisperSTTWindow(
        model_name=config.fast_model_name,
        commit="window",
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        window_s=_value(config, "stream_window_s", 7.0),
        transcribe_every_s=_value(
            config, "stream_transcribe_every_s", 1.2),
        min_transcribe_s=_value(config, "stream_min_transcribe_s", 1.0),
        energy_threshold=_value(
            config, "stream_energy_threshold", 0.008),
        min_commit_words=_value(config, "stream_min_commit_words", 1),
        min_overlap_words=_value(config, "stream_min_overlap_words", 2),
        max_commit_words=_value(config, "stream_max_commit_words", 28),
        resync_after_passes=_value(
            config, "stream_resync_after_passes", 4),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


def _make_local_agreement(config, bus, wake_phrases):
    from .local_agreement import WhisperSTTLocalAgreement
    return WhisperSTTLocalAgreement(
        model_name=config.fast_model_name,
        require_wake_word=config.require_wake_word,
        wake_phrases=wake_phrases,
        followup_window_s=config.followup_window_s,
        language=getattr(config, "language", "en"),
        wake_match_threshold=_value(config, "wake_match_threshold", 0.78),
        window_s=_value(config, "stream_window_s", 7.0),
        transcribe_every_s=_value(
            config, "stream_transcribe_every_s", 1.2),
        min_transcribe_s=_value(config, "stream_min_transcribe_s", 1.0),
        energy_threshold=_value(
            config, "stream_energy_threshold", 0.008),
        min_commit_words=_value(config, "stream_min_commit_words", 1),
        min_overlap_words=_value(config, "stream_min_overlap_words", 2),
        max_commit_words=_value(config, "stream_max_commit_words", 28),
        resync_after_passes=_value(
            config, "stream_resync_after_passes", 4),
        post_padding_ms=_value(config, "post_padding_ms", 250),
        mic_queue_max_frames=_value(config, "mic_queue_max_frames", 200),
        output_queue_max_phrases=_value(
            config, "output_queue_max_phrases", 16),
        bus=bus,
    )


# ── lazy bench wrappers (keep registry import light) ──
def _bench_two_pass(*a, **k):
    from .two_pass import bench
    return bench(*a, **k)


def _bench_vad_segment(*a, **k):
    from .two_pass import bench_vad_segment
    return bench_vad_segment(*a, **k)


def _bench_continuous(*a, **k):
    from .continuous import bench
    return bench(*a, **k)


def _bench_phrase_word(*a, **k):
    from .phrase_word import bench
    return bench(*a, **k)


def _bench_window(*a, **k):
    from .window import bench
    return bench(*a, **k)


def _bench_local_agreement(*a, **k):
    from .local_agreement import bench
    return bench(*a, **k)


# Ordered cheapest/simplest -> richest. `jaeger-whisper-stt list` prints
# them in this order, so it doubles as the "which do I want?" ladder.
METHODS: dict[str, Method] = {
    "vad_segment": Method(
        "vad_segment", "VAD closes a phrase, one model commits it",
        _make_vad_segment, _bench_vad_segment),
    "two_pass": Method(
        "two_pass", "dual whisper — fast base.en gates accurate medium.en",
        _make_two_pass, _bench_two_pass),
    "continuous": Method(
        "continuous", "energy-segmented, rolling re-transcription",
        _make_continuous, _bench_continuous),
    "phrase_word": Method(
        "phrase_word", "continuous + live partials for the open phrase",
        _make_phrase_word, _bench_phrase_word, partials=True),
    "window": Method(
        "window", "rolling window captions, no VAD — clock-driven finals",
        _make_window, _bench_window, partials=True, wake_word=False),
    "local_agreement": Method(
        "local_agreement", "rolling window + word-cursor commit (streaming)",
        _make_local_agreement, _bench_local_agreement,
        partials=True, wake_word=False),
}


def get(name: str) -> Method:
    """Return a configured method or fail loudly on a misspelling.

    Silently booting ``two_pass`` after an invalid deployment setting makes a
    robot appear healthy while running the wrong latency/memory profile.
    """
    try:
        return METHODS[name]
    except KeyError:
        choices = ", ".join(METHODS)
        raise ValueError(f"unknown STT method {name!r}; choose one of: {choices}") \
            from None
