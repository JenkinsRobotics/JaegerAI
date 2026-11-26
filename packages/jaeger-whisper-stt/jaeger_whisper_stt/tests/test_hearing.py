"""The ``stt`` slot's direct call: a caller that already holds the audio
(Jaeger Agent's voice loop, a ``listen`` tool) hands over PCM and gets
timed text back. No bus, no microphone."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

import jaeger_whisper_stt
from jaeger_whisper_stt import TranscriptSegment


@pytest.fixture
def whisper(monkeypatch):
    """A stand-in for pywhispercpp, so no model is loaded."""
    class Calls(list):
        pass

    calls = Calls()

    class Model:
        info = "WHISPER : COREML = 0 | MTL : EMBED_LIBRARY = 1 | CPU : NEON = 1 |"

        def __init__(self, name, **kw):
            calls.append(("load", name))

        @staticmethod
        def system_info():
            return Model.info

        def transcribe(self, audio, **kw):
            calls.append(("decode", audio.dtype.name, audio.shape, kw))
            return [types.SimpleNamespace(text=" Hello. ", t0=7, t1=93, probability=float("nan"))]

    mod = types.ModuleType("pywhispercpp.model")
    mod.Model = Model
    monkeypatch.setitem(sys.modules, "pywhispercpp", types.ModuleType("pywhispercpp"))
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", mod)
    calls.Model = Model
    return calls


def test_open_hearing_loads_once_primes_and_says_what_it_runs_on(whisper):
    hearing = jaeger_whisper_stt.open_hearing(model="large-v3-turbo")
    assert whisper[0] == ("load", "large-v3-turbo")
    assert [c[0] for c in whisper] == ["load", "decode"]     # primed: the first real clip is fast
    assert (hearing.model, hearing.compute) == ("large-v3-turbo", "metal")


def test_transcribe_takes_pcm_and_returns_timed_segments(whisper):
    hearing = jaeger_whisper_stt.open_hearing()
    del whisper[:]
    stop = lambda: False
    out = hearing.transcribe(np.zeros((2, 800), dtype=np.float64), prompt="Hi.", abort=stop)
    assert out == [TranscriptSegment(start_ms=70, end_ms=930, text="Hello.", probability=None)]
    assert whisper == [("decode", "float32", (1600,),
                        {"language": "en", "initial_prompt": "Hi.", "abort_callback": stop})]
    del whisper[:]
    hearing.transcribe([0.0] * 160, language="de")
    assert whisper[0][3] == {"language": "de"}               # nothing passed that was not asked for


def test_compute_is_cpu_when_the_build_has_no_gpu(whisper, monkeypatch):
    monkeypatch.setattr(whisper.Model, "info", "WHISPER : COREML = 0 | CPU : NEON = 1 |")
    assert jaeger_whisper_stt.open_hearing().compute == "cpu"
