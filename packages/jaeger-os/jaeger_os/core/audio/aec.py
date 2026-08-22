"""Acoustic Echo Cancellation wrapper.

Thin facade over `speexdsp.EchoCanceller`. Two reasons for the wrapper:
  1. Graceful fallback — if `speexdsp` isn't installed, `AECWrapper`
     becomes a passthrough that returns the near-end audio unchanged.
     The rest of the framework doesn't have to special-case it.
  2. Single ingestion point — input/output is float32 mono (-1..1),
     converted internally to int16 (the only format speexdsp accepts).
     STT and TTS plugins both work in float32, so this keeps them
     uniform.

Usage:
    aec = AECWrapper(sample_rate=16000, frame_ms=10)
    if not aec.enabled:
        print("AEC unavailable; falling back to set_paused()")
    clean = aec.process(near_float32, far_float32)  # both np.float32 (-1..1)

Frame size constraint: speexdsp wants near and far buffers of the SAME
length, equal to `frame_samples` (default 160 samples = 10 ms @ 16 kHz).
Callers chunking audio into different frame sizes need to slice/zero-pad
before calling process().
"""

from __future__ import annotations

from typing import Any

import numpy as np


def aec_available() -> bool:
    """True iff the speexdsp library can be imported."""
    try:
        import speexdsp  # noqa: F401
        return True
    except Exception:
        return False


class AECWrapper:
    """Wrap speexdsp's EchoCanceller with float32 in/out + passthrough."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 10,
        filter_length: int = 3200,
        enabled: bool = True,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.filter_length = filter_length
        self._impl: Any = None
        self.enabled = False
        self.backend = "none"

        if not enabled:
            return
        try:
            # speexdsp 0.1.1 (PyPI: speexdsp) ships a SWIG wrapper. The
            # `EchoCanceller` class is abstract — you instantiate via the
            # `EchoCanceller_create(frame_size, filter_length, sample_rate)`
            # factory. We import that name explicitly so we don't trip over
            # forks that ship a different surface; if the factory isn't
            # present we fall through to passthrough.
            from speexdsp import EchoCanceller_create  # type: ignore
            self._impl = EchoCanceller_create(
                self.frame_samples, filter_length, sample_rate,
            )
            self.enabled = True
            self.backend = "speexdsp"
        except Exception:
            self._impl = None
            self.enabled = False
            self.backend = "none"

    def process(self, near: np.ndarray, far: np.ndarray | None) -> np.ndarray:
        """Cancel the far-end reference out of near-end (mic) audio.

        Both inputs are float32 mono in [-1, 1]. If AEC is disabled or
        far is None, returns near unchanged. If lengths differ, the
        shorter is zero-padded so speexdsp's frame constraint is met.
        """
        if not self.enabled or self._impl is None:
            return near
        if far is None:
            far = np.zeros_like(near)
        if len(near) != len(far):
            # Pad/trim to whichever is longer so we don't crash speexdsp.
            target = max(len(near), len(far))
            if len(near) < target:
                near = np.pad(near, (0, target - len(near)))
            if len(far) < target:
                far = np.pad(far, (0, target - len(far)))
        # speexdsp wants int16 PCM; round-trip via int16.
        near_i16 = (near * 32767).clip(-32768, 32767).astype(np.int16)
        far_i16 = (far * 32767).clip(-32768, 32767).astype(np.int16)
        try:
            cleaned_i16 = self._impl.process(near_i16.tobytes(), far_i16.tobytes())
            cleaned = np.frombuffer(cleaned_i16, dtype=np.int16).astype(np.float32) / 32768.0
            return cleaned
        except Exception:
            # On any backend error, fall back to passthrough rather than
            # losing the user's audio entirely.
            return near
