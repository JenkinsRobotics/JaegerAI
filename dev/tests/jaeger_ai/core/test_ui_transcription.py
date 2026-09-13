from __future__ import annotations

import base64
import importlib
from types import SimpleNamespace

import numpy as np
import pytest

from jaeger_ai.core.ui_transcription import transcribe_pcm


def _payload(seconds: float = 1.0, sample_rate: int = 48_000) -> str:
    samples = np.zeros(int(seconds * sample_rate), dtype="<f4")
    return base64.b64encode(samples.tobytes()).decode("ascii")


def test_native_pcm_uses_the_agent_whisper_cache_and_resamples(monkeypatch):
    observed = {}

    class Model:
        def transcribe(self, samples, language):
            observed.update(count=len(samples), language=language)
            return [SimpleNamespace(text=" hello "), SimpleNamespace(text="world ")]

    listen_module = importlib.import_module("jaeger_agent.tools.listen")
    monkeypatch.setattr(listen_module, "_get_model", lambda name: Model())
    result = transcribe_pcm(_payload(), sample_rate=48_000, model="medium.en")
    assert result["text"] == "hello world"
    assert result["model"] == "medium.en"
    assert observed == {"count": 16_000, "language": "en"}


@pytest.mark.parametrize("payload,rate,message", [
    ("", 48_000, "empty"),
    ("not base64", 48_000, "base64"),
    (_payload(0.1), 48_000, "too short"),
    (_payload(), 0, "positive"),
])
def test_invalid_native_audio_is_rejected(payload, rate, message):
    with pytest.raises(ValueError, match=message):
        transcribe_pcm(payload, sample_rate=rate)
