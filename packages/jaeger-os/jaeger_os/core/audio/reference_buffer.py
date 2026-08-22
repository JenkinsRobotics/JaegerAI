"""ReferenceBuffer — thread-safe ring buffer for AEC far-end audio.

AEC decoupling (0.9, seam ratified post-split): whatever module is
producing playback audio (kokoro_tts today, any future TTS-slot module
tomorrow) pushes its samples into a ReferenceBuffer; the STT mic-capture
pops samples from the same buffer to use as the AEC far-end reference.
This way the AEC can cancel the AI's own voice out of the mic input.
Neither side needs to know what's on the other end — see
:class:`FarEndReference` below, the protocol that makes this a seam
instead of a hardcoded pairing. ``AudioSession`` (session.py) accepts
any object satisfying it; ``nodes/runtime.py`` is what actually wires a
real TTS module's buffer in, discovery-driven, only when one is
installed.

Two usage patterns inside this module:

  playback side  (producer, e.g. kokoro_tts's KokoroTTS.speak()):
      buf.write(np.float32_audio)      # called each chunk played

  mic side  (consumer, inside mic callback — the FarEndReference use):
      far = buf.pop_frame(n_samples)   # call once per captured frame
      cleaned = aec.process(near, far)

The buffer is bounded — old samples drop off the front when the writer
gets ahead of the reader. That's fine for AEC: stale reference is no
worse than zeros for echo cancellation.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FarEndReference(Protocol):
    """Something that can supply the audio frames currently being
    played out — the far-end reference AEC subtracts from the mic
    signal.

    This is the whole seam: an STT engine (or ``AudioSession``) never
    needs to know what produced the audio, only that it can be pulled
    in fixed-size frames and reset between utterances. ``ReferenceBuffer``
    is the one production implementation today; anything duck-typed to
    this shape (including a test double) works as a far-end provider.
    """

    def pop_frame(self, n_samples: int) -> np.ndarray:
        """Return the next ``n_samples`` of reference audio (float32,
        zero-padded if fewer are available)."""
        ...

    def clear(self) -> None:
        """Drop any unread samples — called when playback stops so a
        new turn doesn't AEC against stale audio."""
        ...


class ReferenceBuffer:
    """Single-producer / single-consumer ring buffer of float32 samples."""

    def __init__(self, *, sample_rate: int = 16000, capacity_seconds: float = 2.0) -> None:
        self.sample_rate = sample_rate
        self.capacity = max(1, int(sample_rate * capacity_seconds))
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self._write = 0
        self._read = 0
        self._filled = 0
        self._lock = threading.Lock()

    def write(self, samples: np.ndarray) -> None:
        """Append samples (float32 mono in [-1, 1]) to the buffer. If the
        buffer is full, the oldest samples are overwritten — TTS playback
        runs faster than mic capture by design."""
        if samples.size == 0:
            return
        flat = samples.astype(np.float32, copy=False).reshape(-1)
        with self._lock:
            n = len(flat)
            if n >= self.capacity:
                # Truncate to the last `capacity` samples; we're behind anyway.
                self._buf[:] = flat[-self.capacity:]
                self._write = 0
                self._read = 0
                self._filled = self.capacity
                return
            end = self._write + n
            if end <= self.capacity:
                self._buf[self._write:end] = flat
            else:
                first = self.capacity - self._write
                self._buf[self._write:] = flat[:first]
                self._buf[: n - first] = flat[first:]
            self._write = (self._write + n) % self.capacity
            self._filled = min(self.capacity, self._filled + n)
            if self._filled == self.capacity:
                # Overwrote some unread data — advance the read pointer.
                self._read = self._write

    def pop_frame(self, n_samples: int) -> np.ndarray:
        """Return the next `n_samples` of reference audio. If the buffer
        has fewer than n_samples available, zero-pads the tail so AEC
        always gets the frame size it wants."""
        out = np.zeros(n_samples, dtype=np.float32)
        with self._lock:
            available = min(self._filled, n_samples)
            if available <= 0:
                return out
            end = self._read + available
            if end <= self.capacity:
                out[:available] = self._buf[self._read:end]
            else:
                first = self.capacity - self._read
                out[:first] = self._buf[self._read:]
                out[first:available] = self._buf[: available - first]
            self._read = (self._read + available) % self.capacity
            self._filled -= available
        return out

    def clear(self) -> None:
        """Drop all unread samples — call when TTS playback stops."""
        with self._lock:
            self._write = 0
            self._read = 0
            self._filled = 0
