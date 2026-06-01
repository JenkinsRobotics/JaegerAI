"""ReferenceBuffer — thread-safe ring buffer for AEC far-end audio.

When barge-in is enabled, the TTS plugin pushes its playback samples
into a ReferenceBuffer; the STT mic-capture pops samples from the same
buffer to use as the AEC far-end reference. This way the AEC can cancel
the AI's own voice out of the mic input.

Two usage patterns inside this module:

  TTS side  (producer):
      buf.write(np.float32_audio)      # called each chunk played

  STT side  (consumer, inside mic callback):
      far = buf.pop_frame(n_samples)   # call once per captured frame
      cleaned = aec.process(near, far)

The buffer is bounded — old samples drop off the front when the writer
gets ahead of the reader. That's fine for AEC: stale reference is no
worse than zeros for echo cancellation.
"""

from __future__ import annotations

import threading

import numpy as np


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
