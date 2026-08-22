"""Framework-level audio helpers.

Under the vocabulary contract, this directory holds *Library*-layer audio
utilities used by the kokoro_tts and whisper_stt plugins. NOT plugins
themselves (no external integration), NOT tools (not LLM-callable), NOT
runners (no background loop owned here).

Current contents:
  • aec.py — AECWrapper around speexdsp's EchoCanceller, passthrough
    fallback when speexdsp isn't installed
  • reference_buffer.py — small thread-safe ring buffer a playback
    module (kokoro_tts today) fills with samples and an STT engine's
    mic capture pops from for AEC's far-end reference; also defines
    :class:`FarEndReference`, the duck-typed protocol that makes this a
    seam rather than a hardcoded TTS<->STT pairing (0.9 AEC decoupling)
  • chimes.py — pre-synthesized wake / follow-up earcons the voice loop
    plays as audible feedback
  • session.py — shared mic/AEC/STT session wrapper used by the
    audio-session node and TUI voice path; accepts an optional
    ``far_end`` provider, never a TTS-specific type

AEC + ReferenceBuffer are used together to enable barge-in: a playback
module publishes its audio to a FarEndReference-shaped buffer; the STT
mic-capture pulls those samples and uses them as the AEC far-end
reference so the AI's own voice gets canceled out of the captured mic
audio. Without a provider (no TTS-slot module installed, or barge-in
off), callers fall back to `set_paused(True)` during TTS or simply run
without echo cancellation — no engine construction requires the other
engine to exist. See ``jaeger_os/nodes/runtime.py``'s
``_resolve_far_end_provider`` for the discovery-driven wiring.
"""

from __future__ import annotations

from .aec import AECWrapper, aec_available
from .reference_buffer import FarEndReference, ReferenceBuffer
from .chimes import ChimePlayer
from .session import AudioSession, AudioSessionConfig, STTAdapter

__all__ = [
    "AECWrapper", "aec_available", "FarEndReference", "ReferenceBuffer",
    "ChimePlayer", "AudioSession", "AudioSessionConfig", "STTAdapter",
]
