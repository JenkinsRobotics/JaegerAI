"""Shared helpers for the STT method bench (``bench.py`` + each method's
``bench()``).  Loading a WAV and a pywhispercpp model is identical across
methods; each method composes these per its own strategy.

Kept dependency-light: WAV via the stdlib ``wave`` + numpy; pywhispercpp
imported lazily inside ``load_stt_model`` so importing this module never
pulls the model runtime.
"""

from __future__ import annotations

import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BenchResult:
    method: str
    model_load_s: float
    transcribe_s: float
    audio_s: float
    text: str
    extra: dict = field(default_factory=dict)
    wer: float | None = None
    error: str | None = None

    @property
    def rtf(self) -> float:
        """Real-time factor: transcribe seconds per audio second (<1 = faster than real time)."""
        return round(self.transcribe_s / max(1e-9, self.audio_s), 3)


def load_wav_16k(path: str | Path):
    """Load a WAV as float32 mono @ 16 kHz (what whisper.cpp wants)."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr, n, ch, sw = (w.getframerate(), w.getnframes(),
                         w.getnchannels(), w.getsampwidth())
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sw} bytes")
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n_out = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a), n_out, endpoint=False),
                      np.arange(len(a)), a).astype(np.float32)
    return a, 16000


def load_stt_model(name: str):
    """A pywhispercpp model with the same flags the live methods use."""
    from pywhispercpp.model import Model

    return Model(name, print_realtime=False, print_progress=False,
                 single_segment=True, no_context=True)


def segments_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    try:
        return " ".join(getattr(s, "text", str(s)) for s in result).strip()
    except TypeError:
        return str(result).strip()


def transcribe_timed(model: Any, audio: Any) -> tuple[str, float]:
    t = time.perf_counter()
    out = model.transcribe(audio, language="en")
    return segments_text(out), time.perf_counter() - t


def timed(fn):
    t = time.perf_counter()
    val = fn()
    return val, time.perf_counter() - t


def word_error_rate(ref: str, hyp: str) -> float:
    """Word-level edit distance / reference length (0 = perfect)."""
    r, h = ref.lower().split(), hyp.lower().split()
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return round(prev[len(h)] / len(r), 3)
