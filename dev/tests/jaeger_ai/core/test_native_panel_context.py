"""Isolated profile-precondition contract; no live WebUI or operator state."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_SOURCE = Path(__file__).resolve().parents[4] / "jaeger_ai/features/webui/api/native_panel_context.py"


def _module():
    spec = importlib.util.spec_from_file_location("native_panel_context_fixture", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_header_is_a_precondition_and_never_a_selector():
    replies = []
    with patch.dict("sys.modules", {
        "api": SimpleNamespace(),
        "api.profiles": SimpleNamespace(get_active_profile_name=lambda: "jaeger"),
        "api.helpers": SimpleNamespace(j=lambda handler, data, status: replies.append((data, status))),
    }):
        module = _module()
        assert module.check_profile(SimpleNamespace(headers={}))
        assert module.check_profile(SimpleNamespace(headers={"X-Jaeger-Expected-Profile": "jaeger"}))
        assert not module.check_profile(SimpleNamespace(headers={"X-Jaeger-Expected-Profile": "other"}))
        assert replies[0][1] == 409
        assert module.active_profile() == "jaeger"


def test_context_exposes_no_session_or_gateway_credentials():
    with patch.dict("sys.modules", {
        "api": SimpleNamespace(),
        "api.profiles": SimpleNamespace(get_active_profile_name=lambda: "jaeger"),
        "api.auth": SimpleNamespace(is_auth_enabled=lambda: True),
    }):
        assert _module().context(SimpleNamespace()) == {"profile": "jaeger", "auth_enabled": True}
