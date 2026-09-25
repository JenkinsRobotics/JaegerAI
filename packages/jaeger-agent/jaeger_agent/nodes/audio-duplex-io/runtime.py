"""Duplex device node: 48 kHz AEC AudioIO, BargeMonitor, floor policy, AGC clamp.

Extracted 2026-09-02 from ../gemma_multimodal.py (the canonical single file).
Keep in sync by re-extraction; behavior must stay byte-equivalent."""
from __future__ import annotations

import queue
import sys
import time

import numpy as np

try:
    import pyaec                 # quasi/full audio pipelines need AEC
except ImportError:
    pyaec = None

try:  # packaged engine
    from jaeger_agent.core.policy import FRAME_MS, SAMPLE_RATE
except ImportError:  # portable node folder loaded by the playground
    from policy import FRAME_MS, SAMPLE_RATE

# ═══════════════════════════════════════════════════════════════════════════
# section: duplex device + barge (quasi/full audio pipeline) — from 03
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# section: duplex audio — VENDORED from voice_quasi_fullduplex.py
# (replaces MicStream at runtime; the class above stays as the vendored base)
# ═══════════════════════════════════════════════════════════════════════════
AEC_FRAME_MS = 10                 # Speex works on 10 ms int16 frames
AEC_FRAME_SAMPLES = SAMPLE_RATE * AEC_FRAME_MS // 1000
AEC_FRAMES_PER_VAD = FRAME_MS // AEC_FRAME_MS
AEC_FILTER_LENGTH = 3200
TTS_NATIVE_SR = 24000
STREAM_SR = 48000                 # device rate — keeps Kokoro's full band;
_DEC = STREAM_SR // SAMPLE_RATE   # the 16 k duplex stream discarded all
                                  # content above 8 kHz and the duplex apps
                                  # audibly sounded duller than half duplex
                                  # (live 2026-09-01). Mic + AEC decimate /3
                                  # back to the 16 k pipeline on ONE stream
                                  # clock, so AEC stays sample-aligned.


def _agc_gain(peak: float, noise: float,
              target: float = 0.06, mx: float = 12.0) -> float:
    """AGC gain with a noise-floor clamp: never lift idle noise above 0.010
    (the gates it feeds start at 0.012) — 12x on a quiet room opened turns
    on nothing and armed the barge monitor at idle (review 2026-09-01, #3)."""
    g = min(mx, max(1.0, target / max(peak, 1e-4)))
    return max(1.0, min(g, 0.010 / max(noise, 1e-4)))
BARGE_IN_MS = 300
# Barge-in needs real level, not just a VAD hit, or AEC echo residual and
# keyboard clicks stop the reply. Raise if she cuts herself off, lower if
# talking over her stops working. Depends on mic gain and speaker volume.
BARGE_IN_RMS = 0.02
# Whether user speech INTERRUPTS playback or the agent keeps talking. A
# user toggle for now (--barge stop|continue); the intended end state is an
# LLM OUTPUT CONTROL — the model tags each reply interruptible or not
# (a story wants to finish, an answer should yield). That control replaces
# this constant at exactly this seam.
BARGE_MODE = "stop"


class AudioIO:
    """Full-duplex 16 kHz audio with Speex acoustic echo cancellation.
    Cleaned 30 ms float32 frames land in .q — the same contract MicStream
    gives capture_turn, so the structured audio pipeline runs unchanged."""

    _AGC_TARGET = 0.06
    _AGC_MAX = 12.0

    def __init__(self) -> None:
        if pyaec is None:
            raise RuntimeError(
                "pyaec is required for quasi/full audio_mode; "
                "install jaeger-agent[multimodal-duplex]"
            )
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is required for quasi/full audio_mode; "
                "install jaeger-agent[multimodal]"
            ) from exc
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        self.paused = False           # contract parity; quasi never pauses
        self._play_q: queue.Queue[np.ndarray] = queue.Queue()
        self._current_chunk = np.zeros(0, dtype=np.int16)
        self._mic_pending: list[np.ndarray] = []
        self._agc_peak = 0.0
        self._agc_noise = 0.02
        self._aec = pyaec.Aec(
            frame_size=AEC_FRAME_SAMPLES,
            filter_length=AEC_FILTER_LENGTH,
            sample_rate=SAMPLE_RATE,
            enable_preprocess=True,
        )
        # warm every cold path the realtime callback touches — first-call
        # overhead caused a burst of input overflows at startup (live)
        zeros16 = [0] * AEC_FRAME_SAMPLES
        for _ in range(3):
            self._aec.cancel_echo(zeros16, zeros16)
        np.zeros(AEC_FRAME_SAMPLES * _DEC,
                 dtype=np.int16).astype(np.float32).reshape(-1, _DEC).mean(axis=1)
        self._last_status = 0.0
        self._playing = False
        self._barged = False
        self._stream = sd.Stream(
            samplerate=STREAM_SR, channels=(1, 1), dtype="int16",
            blocksize=AEC_FRAME_SAMPLES * _DEC, callback=self._cb,
            latency=("low", "low"),
        )

    def _cb(self, indata, outdata, frames, _time_info, status) -> None:
        if status:
            now = time.monotonic()
            if now - self._last_status >= 1.0:      # throttle: startup bursts
                self._last_status = now             # flooded the terminal
                print(f"[audio] {status}", file=sys.stderr)
        if frames != AEC_FRAME_SAMPLES * _DEC:
            outdata.fill(0)
            return
        out = np.zeros(frames, dtype=np.int16)
        n_filled = 0
        cur = self._current_chunk        # LOCAL ref: interrupt_playback()
        while n_filled < frames:         # swaps the attribute mid-loop, and
            if self._barged:             # slicing the swapped (empty) array
                break                    # raised inside the PortAudio
            if len(cur) == 0:            # callback (review 2026-09-01, #8)
                try:
                    cur = self._play_q.get_nowait()
                except queue.Empty:
                    break
            take = min(frames - n_filled, len(cur))
            out[n_filled:n_filled + take] = cur[:take]
            cur = cur[take:]
            n_filled += take
        self._current_chunk = (np.zeros(0, dtype=np.int16) if self._barged
                               else cur)
        outdata[:, 0] = out
        self._playing = (n_filled > 0 or len(cur) > 0
                         or not self._play_q.empty())
        # decimate mic and reference to 16 k with the SAME boxcar — AEC runs
        # at pipeline rate on identically-treated signals
        mic16 = indata[:, 0].astype(np.float32).reshape(-1, _DEC).mean(axis=1)
        ref16 = out.astype(np.float32).reshape(-1, _DEC).mean(axis=1)
        cleaned = self._aec.cancel_echo(
            mic16.astype(np.int16).tolist(),
            ref16.astype(np.int16).tolist())
        self._mic_pending.append(np.asarray(cleaned, dtype=np.int16))
        if len(self._mic_pending) >= AEC_FRAMES_PER_VAD:
            bundled = np.concatenate(self._mic_pending[:AEC_FRAMES_PER_VAD])
            self._mic_pending = self._mic_pending[AEC_FRAMES_PER_VAD:]
            f32 = (bundled.astype(np.float32) / 32767.0).reshape(-1, 1)
            rms = float(np.sqrt(np.mean(f32 ** 2)))
            self._agc_peak = max(rms, self._agc_peak * 0.998)
            self._agc_noise = min(max(rms, 1e-4), self._agc_noise * 1.0005)
            self.q.put(f32 * _agc_gain(self._agc_peak, self._agc_noise,
                                       self._AGC_TARGET, self._AGC_MAX))

    def play_chunk(self, chunk_f32_24k: np.ndarray) -> None:
        """Native-quality path: Kokoro's 24 k floats upsample x2 to the 48 k
        device — nothing above 8 kHz is discarded anymore."""
        try:
            from scipy.signal import resample_poly
        except ImportError as exc:
            raise RuntimeError(
                "scipy is required for duplex playback; "
                "install jaeger-agent[multimodal]"
            ) from exc
        up = resample_poly(np.asarray(chunk_f32_24k, dtype=np.float32),
                           up=STREAM_SR, down=TTS_NATIVE_SR)
        self._play_q.put(np.clip(up * 32767.0, -32768,
                                 32767).astype(np.int16))

    def is_playing(self) -> bool:
        return self._playing

    def interrupt_playback(self) -> None:
        self._barged = True              # flag FIRST — the callback checks it
        with self._play_q.mutex:
            self._play_q.queue.clear()
        self._current_chunk = np.zeros(0, dtype=np.int16)

    def clear_barge(self) -> None:
        self._barged = False

    def drain(self) -> None:
        with self.q.mutex:
            self.q.queue.clear()

    def __enter__(self) -> "AudioIO":
        self._stream.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stream.stop()


class BargeMonitor:
    """Sustained real level on the CLEANED mic during playback = barge.
    AEC residual and clicks sit below BARGE_IN_RMS; a spoken word or two
    crosses it for BARGE_IN_MS. A brief blip resets the streak."""

    _WIN = 12                 # frames considered (360 ms)
    _NEED = 10                # loud frames within the window (300 ms speech)

    def __init__(self) -> None:
        self._recent: list[tuple[bool, np.ndarray]] = []

    def feed(self, frame: np.ndarray) -> bool:
        # windowed MAJORITY, not a consecutive streak: real speech dips
        # below threshold between words, and the streak reset meant a real
        # interruption was transcribed but never cut playback (sim
        # 2026-09-01). Sparse clicks still never accumulate 10-of-12.
        f = np.asarray(frame, dtype=np.float32).reshape(-1)
        loud = float(np.sqrt(np.mean(f ** 2))) >= BARGE_IN_RMS
        self._recent.append((loud, f))
        self._recent = self._recent[-self._WIN:]
        return sum(1 for loud, _ in self._recent if loud) >= self._NEED

    def tail(self) -> list[np.ndarray]:
        """The barge speech itself — carried into the next capture."""
        return [f.reshape(-1, 1) for _, f in self._recent]


def _resample_to_mic_rate(audio_f32: np.ndarray) -> np.ndarray:
    if audio_f32.size == 0:
        return np.zeros(0, dtype=np.int16)
    try:
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise RuntimeError(
            "scipy is required for audio resampling; "
            "install jaeger-agent[multimodal]"
        ) from exc
    resampled = resample_poly(audio_f32, up=SAMPLE_RATE, down=TTS_NATIVE_SR)
    return np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)


__all__ = [
    "_agc_gain",
    "AudioIO",
    "BargeMonitor",
    "_resample_to_mic_rate",
    "AEC_FRAME_MS",
    "AEC_FRAME_SAMPLES",
    "AEC_FRAMES_PER_VAD",
    "AEC_FILTER_LENGTH",
    "TTS_NATIVE_SR",
    "STREAM_SR",
    "_DEC",
    "BARGE_IN_MS",
    "BARGE_IN_RMS",
    "BARGE_MODE",
]
