"""Whisper STT engine — mic capture + VAD/energy-segmented transcription.

The engine half of the ``jaeger_whisper_stt.nodes.whisper_stt`` module (0.8
M2b; folded in from ``jaeger_os/plugins/whisper_stt/``). ``registry.py``
is the swap point ``core/audio/session.py``'s ``_build_adapter`` calls
into by ``config.stt_mode`` name.

Two algorithm modes, same public API:
  • WhisperSTTTwoPass     — VAD-segmented; fast model gates the accurate model
  • WhisperSTTContinuous  — energy-segmented; one model + rolling re-transcription

Both expose: start, stop, set_paused, open_followup, next_phrase, in_speech.
Voice loop picks at startup via --stt-mode {two_pass, continuous}.

`WhisperSTT` is an alias for `WhisperSTTTwoPass` so older callers and
the default plugin entry continue to work.

Both modes accept optional `aec` + `far_end_buffer` parameters for
echo-cancellation-driven barge-in. Without them, callers should use
`set_paused(True)` during TTS playback.
"""

from __future__ import annotations

from .two_pass import WhisperSTTTwoPass
from .continuous import WhisperSTTContinuous

# Backwards-compat alias — default STT class is two-pass.
WhisperSTT = WhisperSTTTwoPass

__all__ = ["WhisperSTT", "WhisperSTTTwoPass", "WhisperSTTContinuous"]
