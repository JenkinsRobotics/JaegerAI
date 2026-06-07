"""Framework-level audio helpers.

Under the vocabulary contract, this directory holds *Library*-layer audio
utilities used by the kokoro_tts and whisper_stt plugins. NOT plugins
themselves (no external integration), NOT tools (not LLM-callable), NOT
runners (no background loop owned here).

Current contents:
  • aec.py — AECWrapper around speexdsp's EchoCanceller, passthrough
    fallback when speexdsp isn't installed
  • reference_buffer.py — small thread-safe ring buffer the TTS plugin
    fills with playback samples and the STT plugin's mic capture pops
    from for AEC's far-end reference
  • chimes.py — pre-synthesized wake / follow-up earcons the voice loop
    plays as audible feedback
  • session.py — shared mic/AEC/STT session wrapper used by the
    audio-session node and TUI voice path

AEC + ReferenceBuffer are used together to enable barge-in: TTS publishes
its playback audio to the ReferenceBuffer; the STT mic-capture pulls those
samples and uses them as the AEC far-end reference so the AI's own voice
gets canceled out of the captured mic audio. Without AEC, callers fall
back to `set_paused(True)` during TTS, which works but precludes barge-in.
"""

from __future__ import annotations

from .aec import AECWrapper, aec_available
from .reference_buffer import ReferenceBuffer
from .chimes import ChimePlayer
from .session import AudioSession, AudioSessionConfig, STTAdapter

__all__ = [
    "AECWrapper", "aec_available", "ReferenceBuffer", "ChimePlayer",
    "AudioSession", "AudioSessionConfig", "STTAdapter",
]
