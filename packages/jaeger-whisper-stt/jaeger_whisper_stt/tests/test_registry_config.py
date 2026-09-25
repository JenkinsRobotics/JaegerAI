from __future__ import annotations

from dataclasses import replace

import pytest

from jaeger_os.core.audio import AudioSession, AudioSessionConfig

from jaeger_whisper_stt.engine import registry


class Capture:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def test_vad_tuning_reaches_two_pass(monkeypatch) -> None:
    from jaeger_whisper_stt.engine import two_pass

    monkeypatch.setattr(two_pass, "WhisperSTTTwoPass", Capture)
    config = replace(
        AudioSessionConfig(), vad_aggressiveness=3, pre_roll_ms=510,
        silence_hangover_ms=920, max_speech_ms=14000,
        mic_queue_max_frames=77,
    )
    engine = registry._make_two_pass(config, "bus", ("hey jaeger",))
    assert engine.kwargs["vad_aggressiveness"] == 3
    assert engine.kwargs["pre_roll_ms"] == 510
    assert engine.kwargs["silence_hangover_ms"] == 920
    assert engine.kwargs["max_speech_ms"] == 14000
    assert engine.kwargs["mic_queue_max_frames"] == 77


def test_stream_tuning_reaches_local_agreement(monkeypatch) -> None:
    from jaeger_whisper_stt.engine import local_agreement

    monkeypatch.setattr(local_agreement, "WhisperSTTLocalAgreement", Capture)
    config = replace(
        AudioSessionConfig(), stream_window_s=11.0,
        stream_transcribe_every_s=0.8, stream_min_overlap_words=4,
        stream_resync_after_passes=7,
    )
    engine = registry._make_local_agreement(config, "bus", ())
    assert engine.kwargs["window_s"] == 11.0
    assert engine.kwargs["transcribe_every_s"] == 0.8
    assert engine.kwargs["min_overlap_words"] == 4
    assert engine.kwargs["resync_after_passes"] == 7


@pytest.mark.parametrize(
    ("field", "value"),
    (("vad_aggressiveness", 4),
     ("max_speech_ms", 100),
     ("stream_window_s", 0),
     ("mic_queue_max_frames", 0)),
)
def test_invalid_realtime_config_fails_before_startup(field, value) -> None:
    with pytest.raises(ValueError):
        replace(AudioSessionConfig(), **{field: value})


@pytest.mark.parametrize("method", ("window", "local_agreement"))
def test_rolling_modes_reject_engine_wake_gating(monkeypatch, method) -> None:
    import jaeger_os.core.modules as modules

    monkeypatch.setattr(
        modules, "resolve_slot_module",
        lambda slot, suffix: registry,
    )
    config = replace(
        AudioSessionConfig(), stt_mode=method, require_wake_word=True,
        wake_phrases=("hey jaeger",),
    )
    with pytest.raises(ValueError, match="cannot apply engine wake-word"):
        AudioSession._build_adapter(config, bus=object())
