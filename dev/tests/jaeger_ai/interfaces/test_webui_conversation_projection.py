import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.fixture
def projection(monkeypatch):
    path = (
        Path(__file__).resolve().parents[4]
        / 'jaeger_ai/features/webui/api/jaeger_conversation.py'
    )
    spec = importlib.util.spec_from_file_location('jaeger_conversation_projection_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profiles = ModuleType('api.profiles')
    profiles.get_active_profile_name = lambda: 'jaeger'
    monkeypatch.setitem(sys.modules, 'api.profiles', profiles)
    return module, profiles

