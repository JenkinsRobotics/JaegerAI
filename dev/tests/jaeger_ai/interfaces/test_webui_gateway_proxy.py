"""The WebUI overlay maps browser routes onto the audited gateway routes.

The browser cannot reach loopback :8810, so every session, stream and
approval call goes through this proxy. If a path maps wrongly the UI fails
in a way that looks like an empty account rather than a broken route, which
is the failure mode the console was built to avoid.

Routes asserted here were read out of ``core/gateway/server.py``'s router
registrations — not assumed. ``/health`` in particular is NOT ``/v1/health``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

OVERLAY = pathlib.Path(__file__).resolve().parents[4] / "integrations/hermes_webui/jaeger_sessions.py"


def _load():
    spec = importlib.util.spec_from_file_location("jaeger_sessions_overlay", OVERLAY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def overlay(monkeypatch):
    mod = _load()
    calls = []
    monkeypatch.setattr(mod, "_proxy",
                        lambda h, m, p, b=None: calls.append((m, p)) or True)
    monkeypatch.setattr(mod, "_proxy_stream",
                        lambda h, sid, q: calls.append(("STREAM", f"/v1/sessions/{sid}/stream{q}")) or True)
    monkeypatch.setattr(mod, "_body_bytes", lambda h: b"{}")
    mod._calls = calls
    return mod


def _route(mod, path, method="GET"):
    return mod.route(SimpleNamespace(), urlparse(path), method)


@pytest.mark.parametrize(("path", "method", "expected"), [
    ("/api/jaeger/sessions", "GET", ("GET", "/v1/sessions")),
    ("/api/jaeger/sessions?profile=jaeger", "GET", ("GET", "/v1/sessions?profile=jaeger")),
    ("/api/jaeger/sessions", "POST", ("POST", "/v1/sessions")),
    ("/api/jaeger/sessions/abc", "GET", ("GET", "/v1/sessions/abc")),
    ("/api/jaeger/sessions/abc", "DELETE", ("DELETE", "/v1/sessions/abc")),
    ("/api/jaeger/sessions/abc/turns", "POST", ("POST", "/v1/sessions/abc/turns")),
    ("/api/jaeger/sessions/abc/cancel", "POST", ("POST", "/v1/sessions/abc/cancel")),
    ("/api/jaeger/sessions/abc/reconcile", "POST", ("POST", "/v1/sessions/abc/reconcile")),
    ("/api/jaeger/sessions/abc/handoff", "POST", ("POST", "/v1/sessions/abc/handoff")),
    ("/api/jaeger/sessions/abc/requests/r1", "GET", ("GET", "/v1/sessions/abc/requests/r1")),
    ("/api/jaeger/approvals/ap_1", "POST", ("POST", "/v1/approvals/ap_1")),
])
def test_routes_map_to_audited_gateway_paths(overlay, path, method, expected):
    assert _route(overlay, path, method) is True
    assert overlay._calls[-1] == expected


def test_health_uses_the_real_route_not_v1_health(overlay):
    """The gateway serves /health; /v1/health 404s."""
    assert _route(overlay, "/api/jaeger/gateway/health") is True
    assert overlay._calls[-1] == ("GET", "/health")


def test_stream_is_proxied_by_the_streaming_path(overlay):
    """SSE must not go through the buffering unary proxy."""
    assert _route(overlay, "/api/jaeger/sessions/abc/stream") is True
    assert overlay._calls[-1] == ("STREAM", "/v1/sessions/abc/stream")


def test_stream_forwards_the_resume_cursor(overlay):
    assert _route(overlay, "/api/jaeger/sessions/abc/stream?last_event_id=42") is True
    assert overlay._calls[-1][1].endswith("?last_event_id=42")


def test_unrelated_paths_are_declined(overlay):
    """Returning False lets the WebUI's own handlers run."""
    assert _route(overlay, "/api/models") is False
    assert overlay._calls == []


def test_gateway_base_honours_the_configured_url(monkeypatch, overlay):
    monkeypatch.setenv("JAEGER_GATEWAY_URL", "http://127.0.0.1:9999/")
    assert overlay.gateway_base() == "http://127.0.0.1:9999"


def test_agents_overlay_chains_to_sessions():
    """The sessions overlay must be reachable from the mounted hook."""
    src = (OVERLAY.parent / "jaeger_agents.py").read_text(encoding="utf-8")
    assert "from api.jaeger_sessions import route" in src


def test_overlay_is_installed_by_the_webui_build():
    build = (OVERLAY.parents[2] / "scripts/prepare-hermes-webui.py").read_text(encoding="utf-8")
    assert "jaeger_sessions.py" in build
    assert "jaeger_gateway_console.js" in build
