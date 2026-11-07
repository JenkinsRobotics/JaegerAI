import sys
from types import SimpleNamespace

from jaeger_os.core.audio.aec import AECWrapper


def test_modern_swig_factory(monkeypatch):
    calls = []
    implementation = object()

    def create(*args):
        calls.append(args)
        return implementation

    monkeypatch.setitem(sys.modules, "speexdsp", SimpleNamespace(EchoCanceller=SimpleNamespace(create=create)))
    wrapper = AECWrapper()
    assert wrapper.enabled
    assert wrapper._impl is implementation
    assert calls == [(160, 3200, 16000)]


def test_original_swig_factory(monkeypatch):
    monkeypatch.setitem(sys.modules, "speexdsp", SimpleNamespace(EchoCanceller_create=lambda *args: object()))
    assert AECWrapper().enabled


def test_missing_factory_remains_disabled(monkeypatch):
    monkeypatch.setitem(sys.modules, "speexdsp", SimpleNamespace())
    assert not AECWrapper().enabled
