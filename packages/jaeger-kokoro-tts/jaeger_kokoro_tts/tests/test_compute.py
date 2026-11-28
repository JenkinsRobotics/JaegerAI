"""Kokoro runs on the fastest device the machine has, with no setting to
find, and ``tts.compute`` says which: "mlx" (Apple GPU), "cuda" or "cpu".
These load the real models; ``test_mlx_backend.py`` covers the choosing
logic with stand-ins."""

from __future__ import annotations

import platform
import sys
import threading

import pytest

from jaeger_kokoro_tts import engine as eng
from jaeger_kokoro_tts.engine import KokoroTTS

APPLE = sys.platform == "darwin" and platform.machine() == "arm64"


@pytest.mark.model
@pytest.mark.skipif(not APPLE, reason="MLX is Apple Silicon only")
def test_apple_silicon_renders_on_mlx():
    pytest.importorskip("mlx_audio")
    tts = KokoroTTS()
    assert tts.compute == ""          # nothing is claimed before the load
    # The app warms on a background thread and speaks from another one.
    warm = threading.Thread(target=tts._ensure_pipeline)
    warm.start()
    warm.join()
    audio = tts.render("Hello there.")
    assert tts.compute == "mlx"
    assert audio is not None and audio.ndim == 1 and len(audio) > 8000


@pytest.mark.model
def test_off_apple_silicon_mlx_is_never_tried(monkeypatch):
    """A Linux robot must not try MLX, nor warn about it at every boot."""
    tried, logged = [], []
    monkeypatch.setattr(eng, "_APPLE_SILICON", False)
    monkeypatch.setattr(eng, "_MlxPipeline", lambda lang: tried.append(lang))
    monkeypatch.setattr(eng, "log", lambda tag, msg, **kw: logged.append(msg))
    tts = KokoroTTS()
    audio = tts.render("Hello there.")
    assert tried == [] and not any("MLX" in m for m in logged)
    assert tts.compute in ("cuda", "cpu")
    assert audio is not None and audio.ndim == 1 and len(audio) > 8000
