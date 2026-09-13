"""Buffered speech-to-text for native UI clients.

The Swift client owns CoreAudio capture. This adapter accepts the captured
Float32 PCM buffer and routes transcription through Jaeger Agent's existing
Whisper model cache, so the desktop app does not carry a second, stubbed STT
implementation.
"""

from __future__ import annotations

import base64
import time
from typing import Any

_TARGET_RATE = 16_000
_MAX_SECONDS = 60.0


def transcribe_pcm(
    pcm_f32le: str,
    *,
    sample_rate: float,
    model: str = "medium.en",
) -> dict[str, Any]:
    """Decode base64 Float32 PCM, resample to 16 kHz, and transcribe."""
    if not pcm_f32le:
        raise ValueError("audio buffer is empty")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    try:
        raw = base64.b64decode(pcm_f32le, validate=True)
    except Exception as exc:
        raise ValueError("audio buffer is not valid base64") from exc
    if not raw or len(raw) % 4:
        raise ValueError("audio buffer must contain Float32 PCM")

    import numpy as np

    samples = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False)
    seconds = len(samples) / sample_rate
    if seconds < 0.2:
        raise ValueError("audio buffer is too short")
    if seconds > _MAX_SECONDS:
        raise ValueError(f"audio buffer exceeds {_MAX_SECONDS:.0f} seconds")
    if sample_rate != _TARGET_RATE:
        out_count = max(1, int(len(samples) * _TARGET_RATE / sample_rate))
        samples = np.interp(
            np.linspace(0, len(samples), out_count, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)

    # This is the same cached pywhispercpp model and default used by the
    # shipped Jaeger Agent `listen` tool. Runtime readiness warms medium.en,
    # so UI transcription reuses that model instead of loading a second one.
    from jaeger_agent.tools.listen import _get_model

    started = time.perf_counter()
    segments = _get_model(model).transcribe(samples, language="en")
    text = " ".join(
        str(getattr(segment, "text", segment) or "").strip()
        for segment in segments
    ).strip()
    if not text:
        raise ValueError("no speech detected")
    return {
        "text": text,
        "model": model,
        "audio_seconds": round(seconds, 3),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


__all__ = ["transcribe_pcm"]
