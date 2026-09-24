"""The WebUI has one execution path: the Gateway. Every other path is isolated."""

from types import SimpleNamespace

import pytest
from api import gateway_chat, routes

ENV = "JAEGER_LEGACY_PATHS"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (ENV, "HERMES_WEBUI_CHAT_BACKEND", "JAEGER_GATEWAY_URL", "HERMES_WEBUI_GATEWAY_URL"):
        monkeypatch.delenv(name, raising=False)


def test_default_backend_is_the_gateway():
    assert gateway_chat.webui_chat_backend_mode({}, {}) == "gateway"
    assert gateway_chat.webui_gateway_chat_enabled({}, {}) is True


def test_in_process_backend_needs_the_explicit_switch():
    assert gateway_chat.webui_chat_backend_mode({}, {ENV: "1"}) == "legacy"
    # An explicit gateway selection still wins over the switch.
    assert gateway_chat.webui_chat_backend_mode(
        {}, {ENV: "1", "JAEGER_GATEWAY_URL": "http://127.0.0.1:8810"}
    ) == "gateway"


@pytest.mark.parametrize("profile", ["hermes", "openclaw", "roundtable"])
def test_native_profile_runner_is_refused_without_the_switch(profile, monkeypatch):
    called = []
    monkeypatch.setattr(routes, "_start_native_profile_run", lambda *a, **k: called.append(1) or {})
    result = routes._start_run(
        SimpleNamespace(profile=profile), msg="hi", attachments=[], workspace="/w",
        model="m", model_provider=None, normalized_model=None, source="webui", route="r",
    )
    assert result["_status"] == 409 and result["code"] == "legacy_path_isolated"
    assert called == []


def test_native_profile_runner_runs_when_reenabled(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    monkeypatch.setattr(routes, "_start_native_profile_run", lambda *a, **k: {"stream_id": "s"})
    result = routes._start_run(
        SimpleNamespace(profile="hermes"), msg="hi", attachments=[], workspace="/w",
        model="m", model_provider=None, normalized_model=None, source="webui", route="r",
    )
    assert result == {"stream_id": "s"}


@pytest.mark.parametrize("path,handler", [
    ("/api/btw", "_handle_btw"),
    ("/api/background", "_handle_background"),
    ("/api/chat", "_handle_chat_sync"),
    ("/api/session/compress", "_handle_session_compress"),
    ("/api/session/handoff-summary", "_handle_handoff_summary"),
])
def test_in_process_agent_endpoints_are_isolated(path, handler, monkeypatch):
    sent = []
    ran = []
    monkeypatch.setattr(routes, "_csrf_exempt_path", lambda _p: True)
    monkeypatch.setattr(routes, "read_body", lambda _h: {})
    monkeypatch.setattr(routes, handler, lambda *a, **k: ran.append(handler) or True)
    monkeypatch.setattr(routes, "j", lambda h, payload, status=200, **k: sent.append((status, payload)))
    handled = routes.handle_post(SimpleNamespace(), SimpleNamespace(path=path, query=""))
    assert handled is True
    assert ran == [] and sent and sent[0][0] == 409
    assert sent[0][1]["code"] == "legacy_path_isolated"


def test_isolated_helper_lets_the_path_run_when_reenabled(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    sent = []
    monkeypatch.setattr(routes, "j", lambda *a, **k: sent.append(1))
    assert routes._isolated_legacy_path(SimpleNamespace(), "x") is False
    assert sent == []
