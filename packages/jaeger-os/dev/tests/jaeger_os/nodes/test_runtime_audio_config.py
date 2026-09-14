"""Standalone app configuration reaches the imported STT module."""

import pytest

from jaeger_os.core.audio import AudioSessionConfig
from jaeger_os.nodes.runtime import _overlay_audio_session_config


def test_manifest_stt_config_overlays_defaults_without_a_mind_package():
    configured = _overlay_audio_session_config(
        AudioSessionConfig(),
        {
            "stt_mode": "local_agreement",
            "fast_model_name": "small.en",
            "require_wake_word": True,
            "wake_phrases": ["hello cosmo", "hey cosmo"],
            "barge_in": True,
            "silence_hangover_ms": 900,
            "stream_window_s": 11.0,
            "stream_min_overlap_words": 4,
            "unrelated_surface_setting": "ignored",
        },
    )

    assert configured.stt_mode == "local_agreement"
    assert configured.fast_model_name == "small.en"
    assert configured.require_wake_word is True
    assert configured.wake_phrases == ("hello cosmo", "hey cosmo")
    assert configured.barge_in is True
    assert configured.silence_hangover_ms == 900
    assert configured.stream_window_s == 11.0
    assert configured.stream_min_overlap_words == 4


def test_manifest_realtime_config_is_validated_before_engine_startup():
    with pytest.raises(ValueError, match="mic_queue_max_frames"):
        _overlay_audio_session_config(
            AudioSessionConfig(), {"mic_queue_max_frames": 0},
        )


def test_tts_starts_playback_before_synthesis_and_shutdown_releases_driver(monkeypatch):
    from types import SimpleNamespace
    from jaeger_os.nodes import runtime
    from jaeger_os.nodes.base import NodeState

    calls = []
    runtime.shutdown()
    synth = SimpleNamespace(warm=lambda: None)
    factory = lambda bus: synth
    node = SimpleNamespace(state=NodeState.RUNNING, stop=lambda: calls.append("tts-stop"))
    thread = SimpleNamespace(start=lambda: calls.append("tts-start"), join=lambda **k: None)
    driver = SimpleNamespace(stop=lambda: calls.append("driver-stop"))

    def ensure_driver(*, config):
        calls.append(("driver", config))
        runtime._audio_io_node = driver
        return driver

    monkeypatch.setattr(runtime, "_default_synth_factory", factory)
    monkeypatch.setattr(runtime, "_synth_factory", factory)
    monkeypatch.setattr(runtime, "ensure_audio_io_node", ensure_driver)
    monkeypatch.setattr(runtime, "_tts_node_factory", lambda **k: node)
    monkeypatch.setattr(runtime, "_thread_factory", lambda n: thread)
    try:
        assert runtime.ensure_tts_node() is node
        assert calls[:2] == [("driver", {"capture": False}), "tts-start"]
    finally:
        runtime.shutdown()
    assert calls[-2:] == ["tts-stop", "driver-stop"]
    assert runtime._audio_io_node is None
