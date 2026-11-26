"""Kokoro prefers the Apple GPU (MLX) and must never be left without a
voice when MLX is missing or broken."""

from __future__ import annotations

import os
import sys
import types

import numpy as np
import pytest

from jaeger_kokoro_tts import engine as eng


@pytest.fixture
def fake_torch_kokoro(monkeypatch):
    """Stand-ins for the PyTorch path, so no model is loaded."""
    built = []
    mod = types.ModuleType("kokoro")
    mod.KPipeline = lambda **kw: built.append(kw) or "torch-pipeline"
    monkeypatch.setitem(sys.modules, "kokoro", mod)
    monkeypatch.setattr(eng, "ensure_short_espeak_paths", lambda: None)
    monkeypatch.setattr(eng, "ensure_hf_offline_if_cached", lambda *a, **k: True)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("JAEGER_KOKORO_BACKEND", raising=False)
    monkeypatch.setattr(eng, "_APPLE_SILICON", True)
    monkeypatch.setitem(sys.modules, "mlx_audio", types.ModuleType("mlx_audio"))
    espeak = types.ModuleType("misaki.espeak")
    monkeypatch.setitem(sys.modules, "misaki", types.ModuleType("misaki"))
    monkeypatch.setitem(sys.modules, "misaki.espeak", espeak)
    return built


def test_it_uses_mlx_when_mlx_loads(fake_torch_kokoro, monkeypatch):
    monkeypatch.setattr(eng, "_MlxPipeline", lambda lang: f"mlx-{lang}")
    tts = eng.KokoroTTS()
    assert tts._ensure_pipeline() == "mlx-a" and tts.compute == "mlx"
    assert fake_torch_kokoro == []          # PyTorch was never built


def test_a_broken_mlx_falls_back_to_pytorch(fake_torch_kokoro, monkeypatch):
    def boom(lang):
        os.environ["HF_HUB_OFFLINE"] = "1"   # as the cache check would
        raise RuntimeError("no metal")
    monkeypatch.setattr(eng, "_MlxPipeline", boom)
    tts = eng.KokoroTTS()
    assert tts._ensure_pipeline() == "torch-pipeline" and tts.compute == "cpu"
    # PyTorch may still need to download: offline must not be left forced.
    assert "HF_HUB_OFFLINE" not in os.environ


def test_the_backend_can_be_forced_either_way(fake_torch_kokoro, monkeypatch):
    monkeypatch.setattr(eng, "_MlxPipeline", lambda lang: 1 / 0)
    monkeypatch.setenv("JAEGER_KOKORO_BACKEND", "mlx")
    with pytest.raises(ZeroDivisionError):   # asked for MLX: no silent fallback
        eng.KokoroTTS()._ensure_pipeline()
    monkeypatch.setenv("JAEGER_KOKORO_BACKEND", "torch")
    monkeypatch.setattr(eng, "_MlxPipeline", lambda lang: "mlx")
    assert eng.KokoroTTS()._ensure_pipeline() == "torch-pipeline"


def test_mlx_chunks_look_like_kokoros(monkeypatch):
    """Whatever shape MLX hands back, the engine gets flat float32."""
    pipe = eng._MlxPipeline.__new__(eng._MlxPipeline)
    pipe._lock, pipe._lang, pipe._vocab = eng.threading.Lock(), "a", {}
    pipe._pipe = lambda text, voice, speed: iter([
        types.SimpleNamespace(audio=np.ones((1, 480), dtype=np.float64)),
        types.SimpleNamespace(audio=None)])
    out = list(pipe("hi", voice="af_heart"))
    assert len(out) == 1 and out[0].audio.shape == (480,)
    assert out[0].audio.dtype == np.float32


def _mlx(lang="a"):
    pipe = eng._MlxPipeline.__new__(eng._MlxPipeline)
    pipe._lock, pipe._lang = eng.threading.Lock(), lang
    pipe._vocab = {"m": 1, "ˈ": 2, "ɑ": 3, "f": 4}
    return pipe


def test_mlx_chunks_carry_lip_marks_from_the_models_own_timings():
    """m/b/p close the lips and f/v tuck the lower lip: sound alone cannot
    tell them from n/t/s, so the times come from Kokoro's phoneme lengths
    (25 ms frames, <bos> first; a phoneme the model has no id for is skipped)."""
    pipe = _mlx()
    pipe._pipe = lambda text, voice, speed: iter([types.SimpleNamespace(
        audio=np.ones(480), phonemes="mˈɑ?f", pred_dur=np.array([4, 2, 1, 3, 2, 4]))])
    (chunk,) = pipe("mom", voice="af_heart")
    assert chunk.marks == [[0.025, 0.075, "p"], [0.175, 0.225, "f"]]


def test_a_british_voice_is_read_with_british_rules():
    """A Kokoro voice's first letter is its language."""
    pipe = _mlx("a")
    read = lambda lang: lambda text, voice, speed: iter(
        [types.SimpleNamespace(audio=np.full(2, float(ord(lang))))])
    pipe._pipe = read("a")
    pipe._model = types.SimpleNamespace(_get_pipeline=read)
    heard = lambda voice: chr(int(next(iter(pipe("hi", voice=voice))).audio[0]))
    assert [heard("af_heart"), heard("bf_emma"), heard("am_adam"), heard("jf_alpha")] == ["a", "b", "a", "a"]
