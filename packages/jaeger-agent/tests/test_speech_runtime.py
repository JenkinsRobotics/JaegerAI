from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np

from jaeger_agent.core.config import MultimodalConfig
from jaeger_agent.core.speech import SpeechRuntime


def test_speech_runtime_owns_and_reuses_agent_nodes(monkeypatch) -> None:
    from jaeger_agent.core import engine

    calls = []

    class Stt:
        def load(self, _say, *, model_name):
            calls.append(("stt-load", model_name))

        def transcribe(self, audio):
            calls.append(("stt", len(audio)))
            return "heard"

    class Tts:
        def load(self, _say, *, voice, language):
            calls.append(("tts-load", voice, language))

        def synth(self, text):
            calls.append(("tts", text))
            yield np.asarray([0.25], dtype=np.float32)
            yield np.asarray([-0.25], dtype=np.float32)

    stt = Stt()
    tts = Tts()
    monkeypatch.setattr(engine, "stt_mod", SimpleNamespace(build=lambda: stt))
    monkeypatch.setattr(engine, "tts_mod", SimpleNamespace(build=lambda: tts))
    runtime = SpeechRuntime(
        MultimodalConfig(
            stt_model="agent-whisper",
            kokoro_voice="agent-voice",
            kokoro_language="a",
        )
    )

    runtime.load(lambda _message: None)
    runtime.load(lambda _message: None)

    assert runtime.transcribe(np.zeros(320, dtype=np.float32)) == "heard"
    assert runtime.synthesize("hello").tolist() == [0.25, -0.25]
    assert calls == [
        ("tts-load", "agent-voice", "a"),
        ("stt-load", "agent-whisper"),
        ("stt", 320),
        ("tts", "hello"),
    ]


def test_speech_runtime_does_not_buffer_tts_chunks():
    completed = []

    def synth(text):
        yield np.asarray([0.5], dtype=np.float32)
        completed.append(text)
        yield np.asarray([-0.5], dtype=np.float32)

    runtime = SpeechRuntime()
    runtime._loaded = True
    runtime.tts = SimpleNamespace(synth=synth)
    stream = runtime.synthesize_stream("hello")
    assert next(stream).tolist() == [0.5]
    assert completed == []
    stream.close()
    assert runtime._tts_lock.acquire(blocking=False)
    runtime._tts_lock.release()


def test_segment_decode_uses_the_node_lock_and_keeps_timestamps():
    lock = threading.Lock()
    cancel = threading.Event()

    def decode(audio, **options):
        assert lock.locked()
        assert audio.dtype == np.float32
        assert options == {"language": "en", "initial_prompt": "Hello.",
                           "abort_callback": cancel.is_set}
        return [SimpleNamespace(text="world", t0=7, t1=93)]

    runtime = SpeechRuntime()
    runtime._loaded = True
    runtime.stt = SimpleNamespace(_lock=lock, model=SimpleNamespace(transcribe=decode))
    assert runtime.transcribe_segments([0.0], initial_prompt="Hello.", abort_callback=cancel.is_set) == [
        {"text": "world", "t0": 7, "t1": 93}]
    assert not lock.locked()


def test_device_sample_rate_is_resampled_inside_agent():
    calls = []
    runtime = SpeechRuntime()
    runtime._loaded = True
    runtime.stt = SimpleNamespace(transcribe=lambda audio: calls.append(audio) or "heard")
    assert runtime.transcribe(np.ones(48000), sample_rate=48000) == "heard"
    assert calls[0].shape == (16000,)
    assert calls[0].dtype == np.float32


def test_speech_playback_writes_bounded_chunks_and_releases_device(monkeypatch):
    import sys
    from jaeger_agent.core.policy import TTS_RATE
    events = []
    class Output:
        def __init__(self, **kwargs):
            assert kwargs['samplerate'] == TTS_RATE
            assert kwargs['channels'] == 1
        def start(self): events.append('start')
        def write(self, samples): events.append(samples.copy())
        def stop(self): events.append('stop')
        def abort(self): events.append('abort')
        def close(self): events.append('close')
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(OutputStream=Output))
    runtime = SpeechRuntime()
    runtime._loaded = True
    samples = np.linspace(-1, 1, TTS_RATE, dtype=np.float32)
    runtime.tts = SimpleNamespace(synth=lambda _: iter([samples[:1], samples[1:]]))
    assert runtime.speak('hello')
    assert events[0] == 'start' and events[-2:] == ['stop', 'close']
    writes = [x for x in events if isinstance(x, np.ndarray)]
    assert max(map(len, writes)) <= TTS_RATE // 50
    np.testing.assert_array_equal(np.concatenate(writes), samples)
    assert not runtime._playback_lock.locked()
    assert not runtime._tts_lock.locked()


def test_turn_cancel_interrupts_explicit_playback_owner_and_closes(monkeypatch):
    import sys
    from jaeger_agent.core.cancellation import turn_cancellation
    events = []
    turn = threading.Event()
    playback = threading.Event()
    class Output:
        def __init__(self, **kwargs): pass
        def start(self): events.append('start')
        def write(self, samples):
            events.append('write')
            turn.set()
        def stop(self): events.append('stop')
        def abort(self): events.append('abort')
        def close(self): events.append('close')
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(OutputStream=Output))
    runtime = SpeechRuntime()
    runtime._loaded = True
    runtime.tts = SimpleNamespace(synth=lambda _: iter([np.ones(24000, dtype=np.float32)]))
    with turn_cancellation(turn):
        assert not runtime.speak('hello', cancel_event=playback)
    assert events == ['start', 'write', 'abort', 'close']
    assert not runtime._playback_lock.locked()
    assert not runtime._tts_lock.locked()


def test_device_failure_does_not_lock_future_speech(monkeypatch):
    import sys
    import pytest
    closed = []
    class Output:
        def __init__(self, **kwargs): pass
        def start(self): raise OSError('device disconnected')
        def stop(self): pass
        def close(self): closed.append(True)
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(OutputStream=Output))
    runtime = SpeechRuntime()
    runtime._loaded = True
    runtime.tts = SimpleNamespace(synth=lambda _: iter([np.ones(480, dtype=np.float32)]))
    with pytest.raises(OSError, match='disconnected'):
        runtime.speak('hello')
    assert closed == [True]
    assert not runtime._playback_lock.locked()
    assert not runtime._tts_lock.locked()
