"""Whisper STT engine — mic capture + VAD/energy-segmented transcription.

The engine half of the ``jaeger_whisper_stt`` module (0.8
M2b; folded in from ``jaeger_os/plugins/whisper_stt/``). ``registry.py``
is the swap point ``core/audio/session.py``'s ``_build_adapter`` calls
into by ``config.stt_mode`` name.

Six methods over three segmentation strategies, one public API:

  VAD-segmented (WebRTC VAD closes a phrase)
    • vad_segment      WhisperSTTTwoPass(accurate_model_name=None)
    • two_pass         WhisperSTTTwoPass — fast model gates the accurate one
  Energy-segmented (RMS silence closes a phrase)
    • continuous       WhisperSTTContinuous — rolling re-transcription
    • phrase_word      WhisperSTTPhraseWord — the above, emitting partials
  Rolling window (never segments)
    • window           WhisperSTTWindow(commit="window") — captions
    • local_agreement  WhisperSTTLocalAgreement — word-cursor streaming

All expose: start, stop, set_paused, open_followup, next_phrase,
in_speech, in_utterance, set_on_speech_detected, drain_pending.  The
three ``partials=True`` methods additionally expose ``set_on_partial``
for live ``is_final=False`` text.  Pick by name via ``registry.get()``
(``config.stt_mode``) or ``jaeger-whisper-stt run <method>``.

`WhisperSTT` is an alias for `WhisperSTTTwoPass` so older callers and
the default plugin entry continue to work.

Echo cancellation is NOT here and takes no parameters here. The
pipelines used to accept `aec` + `far_end_buffer` so they could cancel
the robot's own voice out of the microphone; both are gone, because
`jaeger_os.nodes.audio_io` owns the device, the playback reference and
the canceller, and publishes already-cleaned frames on `/sense/mic/pcm`.
A pipeline that re-cancelled would be cancelling twice. `set_paused()`
survives as a local drop for a consumer that wants to ignore audio
during playback — it no longer pauses the shared device.
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "WhisperSTT": (".two_pass", "WhisperSTTTwoPass"),
    "WhisperSTTTwoPass": (".two_pass", "WhisperSTTTwoPass"),
    "WhisperSTTContinuous": (".continuous", "WhisperSTTContinuous"),
    "WhisperSTTPhraseWord": (".phrase_word", "WhisperSTTPhraseWord"),
    "WhisperSTTWindow": (".window", "WhisperSTTWindow"),
    "WhisperSTTLocalAgreement": (
        ".local_agreement", "WhisperSTTLocalAgreement"),
}


def __getattr__(name: str):
    """Resolve one algorithm without importing all optional algorithms."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value

__all__ = [
    "WhisperSTT",
    "WhisperSTTTwoPass",
    "WhisperSTTContinuous",
    "WhisperSTTPhraseWord",
    "WhisperSTTWindow",
    "WhisperSTTLocalAgreement",
]
