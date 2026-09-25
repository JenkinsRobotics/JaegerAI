"""Missing speech assets must produce a host-visible error, not thread exit."""
import importlib.util
import sys
from types import SimpleNamespace

import pytest
from jaeger_agent.core import engine


@pytest.mark.parametrize('language', ['a', 'b'])
def test_english_requires_packaged_language_model(monkeypatch, language):
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec',
                        lambda name: None if name == 'en_core_web_sm' else original(name))
    with pytest.raises(RuntimeError, match='en_core_web_sm'):
        engine.tts_mod.build().load(language=language)


def test_package_downloader_exit_is_a_runtime_failure(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    def pipeline(**kwargs):
        raise SystemExit(1)
    monkeypatch.setitem(sys.modules, 'kokoro', SimpleNamespace(KPipeline=pipeline))
    with pytest.raises(RuntimeError, match='language assets'):
        engine.tts_mod.build().load()
