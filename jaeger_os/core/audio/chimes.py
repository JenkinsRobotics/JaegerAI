"""Tiny UI earcons for wake and follow-up cues.

Played by the voice loop to give the user audible feedback that the agent
heard them. Two cues:

  • wake     — single tone, plays right after wake-word match (or any
               phrase commit when wake-word gating is off). Tells the user
               "I heard you, processing your request."
  • followup — two-note tone (low → high), plays when the follow-up window
               opens. Tells the user "you can keep talking without
               re-saying the wake word."

Ported from VoiceLLM/audio/chimes.py with VoiceLLM-specific config refs
replaced by constructor arguments + sane defaults. The voice_loop is the
only caller; it pauses the mic around playback (or relies on AEC) so we
don't capture our own chime as user speech.
"""

from __future__ import annotations

import sys
import time
from typing import Any

import numpy as np


# Defaults — chosen to match VoiceLLM's tuning. Override in the constructor
# if you want a different timbre.
CHIME_SAMPLE_RATE = 24000
CHIME_VOLUME = 0.18
WAKE_CHIME_FREQ = 880.0          # A5 — clear "ready" tone
WAKE_CHIME_DURATION_MS = 110
FOLLOWUP_CHIME_LOW_FREQ = 660.0  # E5
FOLLOWUP_CHIME_HIGH_FREQ = 988.0  # B5 — rising couplet
FOLLOWUP_CHIME_DURATION_MS = 80
FOLLOWUP_CHIME_GAP_MS = 40
TTS_TAIL_SLEEP_S = 0.12


def _make_chime(
    freq: float,
    duration_ms: int,
    *,
    sample_rate: int = CHIME_SAMPLE_RATE,
    volume: float = CHIME_VOLUME,
) -> np.ndarray:
    """Synthesize a single-frequency tone with a 10 ms fade-in/out so
    speakers don't click on transient onset."""
    n = int(sample_rate * duration_ms / 1000)
    t = np.arange(n) / sample_rate
    duration_s = duration_ms / 1000
    env = np.minimum(np.minimum(t / 0.01, 1.0), (duration_s - t) / 0.01).clip(0, 1)
    return (volume * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _make_followup_chime(
    *,
    sample_rate: int = CHIME_SAMPLE_RATE,
    volume: float = CHIME_VOLUME,
    low_freq: float = FOLLOWUP_CHIME_LOW_FREQ,
    high_freq: float = FOLLOWUP_CHIME_HIGH_FREQ,
    duration_ms: int = FOLLOWUP_CHIME_DURATION_MS,
    gap_ms: int = FOLLOWUP_CHIME_GAP_MS,
) -> np.ndarray:
    gap = np.zeros(int(sample_rate * gap_ms / 1000), dtype=np.float32)
    return np.concatenate([
        _make_chime(low_freq, duration_ms, sample_rate=sample_rate, volume=volume),
        gap,
        _make_chime(high_freq, duration_ms, sample_rate=sample_rate, volume=volume),
    ])


class ChimePlayer:
    """Pre-synthesizes both chimes at startup so `play()` is just an
    `sd.play()` call with no allocation. Thread-safe-ish: assumes only one
    caller at a time (the voice loop)."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        wake_enabled: bool = True,
        followup_enabled: bool = True,
        sample_rate: int = CHIME_SAMPLE_RATE,
        volume: float = CHIME_VOLUME,
        tail_sleep_s: float = TTS_TAIL_SLEEP_S,
        reference_buffer: Any = None,
    ) -> None:
        self.enabled_master = enabled
        self.wake_enabled = wake_enabled
        self.followup_enabled = followup_enabled
        self.sample_rate = sample_rate
        self.tail_sleep_s = tail_sleep_s
        # Optional: when set, chime audio is also pushed to the AEC reference
        # buffer so the STT plugin can cancel chime echo out of mic capture.
        # Without it, callers should pause the mic around play() calls.
        self.reference_buffer = reference_buffer
        self._wake = _make_chime(
            WAKE_CHIME_FREQ, WAKE_CHIME_DURATION_MS,
            sample_rate=sample_rate, volume=volume,
        )
        self._followup = _make_followup_chime(sample_rate=sample_rate, volume=volume)

    def enabled(self, kind: str) -> bool:
        if not self.enabled_master:
            return False
        if kind == "wake":
            return self.wake_enabled
        if kind == "followup":
            return self.followup_enabled
        return False

    def play(self, kind: str, *, output_device: Any = None) -> None:
        """Block on chime playback. Caller is responsible for pausing the
        mic around this call if AEC isn't active."""
        if not self.enabled(kind):
            return
        if kind == "wake":
            audio = self._wake
        elif kind == "followup":
            audio = self._followup
        else:
            return
        if self.reference_buffer is not None:
            # Push to AEC reference at the reference buffer's sample rate
            # (typically 16 kHz). If the chime is 24 kHz, downsample.
            try:
                ref_audio = audio
                if self.sample_rate != self.reference_buffer.sample_rate:
                    from scipy.signal import resample_poly
                    ref_audio = resample_poly(
                        audio, up=self.reference_buffer.sample_rate,
                        down=self.sample_rate,
                    ).astype(np.float32)
                self.reference_buffer.write(ref_audio)
            except Exception:
                pass
        # 0.3.0: prefer avaudio_io.OutputStream on macOS — same
        # wedging-CoreAudio fix as the rest of the voice pipeline.
        # Falls back to sounddevice on Linux or if the bridge can't
        # load.
        if sys.platform == "darwin":
            try:
                self._play_via_avaudio(audio)
                time.sleep(self.tail_sleep_s)
                return
            except Exception as exc:
                print(f"[chime] avaudio backend unavailable ({exc}); "
                      "falling back to sounddevice", file=sys.stderr, flush=True)
        try:
            import sounddevice as sd
            sd.play(audio, samplerate=self.sample_rate, device=output_device)
            sd.wait()
            time.sleep(self.tail_sleep_s)
        except Exception as exc:
            print(f"[chime] playback failed: {exc}", file=sys.stderr, flush=True)

    def _play_via_avaudio(self, audio) -> None:
        """Blocking chime playback through the avaudio_io bridge.
        Pumps the prebuilt audio buffer through a single OutputStream
        callback, waits for the finished_callback to fire."""
        import threading as _threading
        from jaeger_os.plugins.avaudio_io import (
            OutputStream as _AVOutputStream,
            CallbackStop,
        )

        blocksize = max(64, int(self.sample_rate * 0.02))  # 20 ms-ish
        cursor = [0]
        finished = _threading.Event()

        def _cb(outdata, frames, _t, _s):
            i = cursor[0]
            end = i + frames
            if i >= len(audio):
                outdata.fill(0.0)
                raise CallbackStop()
            if end > len(audio):
                n = len(audio) - i
                outdata[:n, 0] = audio[i:i + n]
                outdata[n:, 0] = 0.0
                cursor[0] = len(audio)
                raise CallbackStop()
            outdata[:, 0] = audio[i:end]
            cursor[0] = end

        stream = _AVOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=_cb,
            finished_callback=finished.set,
        )
        try:
            stream.start()
            timeout = float(len(audio)) / self.sample_rate + 1.0
            finished.wait(timeout=timeout)
        finally:
            stream.close()
