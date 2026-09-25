"""STT node: Whisper large-v3-turbo, whole-utterance authoritative decode.

Node of the agent brain. Config source of truth stays core/policy.py;
the manifest documents it."""
from __future__ import annotations

import threading

import numpy as np

try:  # packaged engine
    from jaeger_agent.core.policy import SAMPLE_RATE, STT_MODEL
except ImportError:  # portable node folder loaded by the playground
    from policy import SAMPLE_RATE, STT_MODEL


class SttWhisper:
    def __init__(self) -> None:
        self.model = None
        self._lock = threading.Lock()   # preview and final share one model

    def load(self, say=print, *, model_name: str = STT_MODEL) -> None:
        from pywhispercpp.model import Model
        say(f"loading Whisper {model_name}…")
        self.model = Model(model_name, print_realtime=False,
                           print_progress=False)
        try:
            self.model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32),
                                  language="en")
        except Exception:
            pass

    def transcribe(self, audio) -> str:
        with self._lock:
            return " ".join(s.text for s in self.model.transcribe(
                np.asarray(audio, dtype=np.float32).reshape(-1),
                language="en")).strip()


def build():
    return SttWhisper()
