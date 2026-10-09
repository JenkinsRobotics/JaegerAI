"""The companion's local voice: Kokoro rendered to a WAV the browser plays (and meters)."""
import importlib
import io
import sys
import types
import wave
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[5] / "jaeger_ai" / "features" / "webui"


@pytest.fixture
def agents(monkeypatch):
    sys.path.insert(0, str(WEBUI))
    mod = importlib.import_module("api.jaeger_agents")
    monkeypatch.setattr(mod, "_KOKORO", None)
    calls = []

    class FakeKokoro:
        def render(self, text):
            import numpy as np
            calls.append(text)
            return np.sin(np.linspace(0, 400, 2400)).astype("float32")

    engine = types.ModuleType("jaeger_kokoro_tts.engine")
    engine.KokoroTTS = FakeKokoro
    engine.KOKORO_SAMPLE_RATE = 24000
    monkeypatch.setitem(sys.modules, "jaeger_kokoro_tts.engine", engine)
    mod._calls = calls
    return mod


def test_kokoro_renders_a_24k_mono_wav_with_capped_text(agents):
    body = agents.kokoro_wav("x" * 5000)
    with wave.open(io.BytesIO(body)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 2400)
    assert len(agents._calls[0]) == agents.KOKORO_MAX_CHARS


def test_empty_text_renders_nothing(agents):
    assert agents.kokoro_wav("   ") is None
    assert agents._calls == []


def test_companion_prefers_the_local_voice_and_falls_back_to_browser_speech():
    js = (WEBUI / "static" / "jaeger_companion.js").read_text()
    assert "speakAudio('api/jaeger/tts'" in js
    assert "req.catch(()=>{ try{ speakBrowser(t); }catch(_){} })" in js


def test_startup_warm_renders_once_off_the_request_path(agents, monkeypatch):
    monkeypatch.delenv("JAEGER_KOKORO_WARM", raising=False)
    t = agents.warm_kokoro_in_background()
    t.join(timeout=10)
    assert agents._calls == ["Ready."] and agents._KOKORO is not None
    agents.kokoro_wav("hello")                      # the warm engine is reused
    assert agents._calls == ["Ready.", "hello"]


def test_startup_warm_can_be_turned_off(agents, monkeypatch):
    monkeypatch.setenv("JAEGER_KOKORO_WARM", "0")
    assert agents.warm_kokoro_in_background() is None
    assert agents._calls == []


def test_webui_main_starts_the_warm_up():
    assert "warm_kokoro_in_background()" in (WEBUI / "server.py").read_text()
