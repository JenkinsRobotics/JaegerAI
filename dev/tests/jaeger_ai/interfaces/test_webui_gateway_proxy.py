"""The WebUI overlay maps browser routes onto the audited gateway routes.

The browser cannot reach loopback :33418, so every session, stream and
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

OVERLAY = (
    pathlib.Path(__file__).resolve().parents[4]
    / "jaeger_ai/features/webui/api/jaeger_sessions.py"
)


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
    ("/v1/sessions/abc", "PATCH", ("PATCH", "/v1/sessions/abc")),
    ("/api/jaeger/sessions/abc/turns", "POST", ("POST", "/v1/sessions/abc/turns")),
    ("/api/jaeger/sessions/abc/cancel", "POST", ("POST", "/v1/sessions/abc/cancel")),
    ("/api/jaeger/sessions/abc/reconcile", "POST", ("POST", "/v1/sessions/abc/reconcile")),
    ("/api/jaeger/sessions/abc/handoff", "POST", ("POST", "/v1/sessions/abc/handoff")),
    ("/api/jaeger/sessions/abc/requests/r1", "GET", ("GET", "/v1/sessions/abc/requests/r1")),
    ("/api/jaeger/approvals/ap_1", "POST", ("POST", "/v1/approvals/ap_1")),
    ("/api/jaeger/approvals", "GET", ("GET", "/v1/approvals")),
    ("/v1/approvals", "GET", ("GET", "/v1/approvals")),
    ("/api/jaeger/runtime/frameworks", "GET", ("GET", "/v1/runtime/frameworks")),
    ("/api/jaeger/runtime/models", "GET", ("GET", "/v1/runtime/models")),
    ("/api/jaeger/runtime/capabilities", "GET", ("GET", "/v1/runtime/capabilities")),
    ("/api/jaeger/sessions/abc/attachments", "GET", ("GET", "/v1/sessions/abc/attachments")),
    ("/api/jaeger/sessions/abc/attachments", "POST", ("POST", "/v1/sessions/abc/attachments")),
    ("/v1/sessions/agent-native%3Ajaeger/messages?limit=50", "GET",
     ("GET", "/v1/sessions/agent-native%3Ajaeger/messages?limit=50")),
    ("/api/jaeger/sessions/abc/messages?before=9&limit=20", "GET", ("GET", "/v1/sessions/abc/messages?before=9&limit=20")),
    ("/v1/sessions/abc/events", "GET", ("GET", "/v1/sessions/abc/events")),
    ("/v1/sessions/abc/attachments/upload", "POST", ("POST", "/v1/sessions/abc/attachments/upload")),
    ("/v1/sessions/abc/ide/0123456789ab", "POST", ("POST", "/v1/sessions/abc/ide/0123456789ab")),
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
    assert _route(overlay, "/api/not-a-jaeger-route") is False
    assert overlay._calls == []


def test_gateway_base_honours_the_configured_url(monkeypatch, overlay):
    monkeypatch.setenv("JAEGER_GATEWAY_URL", "http://127.0.0.1:9999/")
    assert overlay.gateway_base() == "http://127.0.0.1:9999"


def test_agents_overlay_chains_to_sessions():
    """The sessions overlay must be reachable from the mounted hook."""
    src = (OVERLAY.parent / "jaeger_agents.py").read_text(encoding="utf-8")
    assert "from api.jaeger_sessions import route" in src


def test_backend_proxy_remains_without_the_retired_console_frontend():
    root = OVERLAY.parents[4]
    assert OVERLAY.is_file()
    assert not (root / "jaeger_ai/assets/jaeger_gateway_console.js").exists()
    assert (root / "jaeger_ai/interfaces/ui/src").is_dir()


def test_global_event_stream_uses_the_session_stream_pump(monkeypatch):
    mod = _load()
    seen = []
    monkeypatch.setattr(mod, "_proxy_stream",
                        lambda h, sid, q, upstream_path=None: seen.append((sid, q, upstream_path)) or True)
    assert _route(mod, "/api/jaeger/events/stream?last_event_id=5") is True
    assert seen == [("*", "?last_event_id=5", "/v1/events/stream")]


def test_connect_apps_proxy_routes_live_in_the_agents_overlay(monkeypatch):
    import importlib.util
    import pathlib
    import sys as _sys

    root = pathlib.Path(__file__).resolve().parents[4] / "jaeger_ai/features/webui"
    _sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location("_ja", root / "api/jaeger_agents.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        _sys.path.pop(0)
    calls = []
    monkeypatch.setattr(mod, "_proxy", lambda h, m, p, b=None, **k: calls.append((m, p)) or True)
    monkeypatch.setattr(mod, "_sessions_route", lambda *a: False, raising=False)
    handler = SimpleNamespace(_json_body_bytes=b'{"confirm": true}')
    for path, method in (("/api/connect-apps", "GET"), ("/api/connect-apps/vscode/state?refresh=1", "GET"),
                         ("/api/connect-apps/vscode/install", "POST")):
        assert mod.route(handler, urlparse(path), method) is True
    assert calls == [("GET", "/v1/connect-apps"), ("GET", "/v1/connect-apps/vscode/state?refresh=1"),
                     ("POST", "/v1/connect-apps/vscode/install")]


def test_session_control_query_and_global_stream_use_canonical_routes(overlay, monkeypatch):
    assert _route(overlay, '/v1/sessions/owned?view=control')
    assert overlay._calls[-1] == ('GET', '/v1/sessions/owned?view=control')
    calls = []
    monkeypatch.setattr(overlay, '_proxy_stream', lambda h, sid, query, **kwargs: calls.append((sid, kwargs['upstream_path'])) or True)
    assert _route(overlay, '/v1/events/stream')
    assert calls == [('*', '/v1/events/stream')]


def test_skills_and_schedule_controls_stay_on_gateway_owner(overlay):
    assert _route(overlay, '/v1/runtime/skills?q=owned')
    assert _route(overlay, '/v1/schedules?include_deleted=1')
    assert _route(overlay, '/v1/schedules/history?job_id=owned')
    assert _route(overlay, '/v1/control-operations/owned')
    assert ('GET', '/v1/runtime/skills?q=owned') in overlay._calls


def test_tasks_mutations_forward_only_supported_existing_actions(monkeypatch):
    root = pathlib.Path(__file__).resolve().parents[4] / "jaeger_ai/features/webui"
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location("_task_proxy", root / "api/jaeger_agents.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    calls = []
    monkeypatch.setattr(mod, "_proxy", lambda h, m, p, b=None, **k: calls.append((m, p, b)) or True)
    monkeypatch.setattr(mod, "_sessions_route", lambda *a: False, raising=False)
    handler = SimpleNamespace(_json_body_bytes=b'{"expected_updated_at":42}')
    for method, suffix in (("PATCH", "owned"), ("POST", "owned/approve"), ("POST", "owned/cancel")):
        assert mod.route(handler, urlparse('/v1/tasks/' + suffix), method)
    assert calls == [(m, '/v1/tasks/' + s, handler._json_body_bytes) for m, s in (("PATCH", "owned"), ("POST", "owned/approve"), ("POST", "owned/cancel"))]
    assert not mod.route(handler, urlparse('/v1/tasks/owned/delete'), 'POST')


def test_template_and_specialist_settings_proxy_preserves_owner_contract(overlay):
    assert _route(overlay, '/v1/agents/native%3Aowned/messages/search?q=literal%25&before=50')
    assert overlay._calls[-1] == ('GET', '/v1/agents/native%3Aowned/messages/search?q=literal%25&before=50')
    assert _route(overlay, '/v1/runtime/diagnostics')
    assert overlay._calls[-1] == ('GET', '/v1/runtime/diagnostics')
    assert _route(overlay, '/v1/runtime/tools?q=owned')
    assert overlay._calls[-1] == ('GET', '/v1/runtime/tools?q=owned')
    assert _route(overlay, '/v1/agents/native%3Aowned/knowledge')
    assert _route(overlay, '/v1/agents/native%3Aowned/knowledge', 'PATCH')
    assert overlay._calls[-1] == ('PATCH', '/v1/agents/native%3Aowned/knowledge')
    assert _route(overlay, '/v1/agent-templates')
    assert _route(overlay, '/v1/agents/native%3Aowned/configuration')
    assert _route(overlay, '/v1/agents/native%3Aowned/configuration', 'PATCH')
    assert overlay._calls[-3:] == [('GET', '/v1/agent-templates'), ('GET', '/v1/agents/native%3Aowned/configuration'), ('PATCH', '/v1/agents/native%3Aowned/configuration')]
    assert not _route(overlay, '/v1/agents/native%3Aowned%2Fother/configuration', 'PATCH')


def test_workflow_routes_use_gateway_and_reject_unadvertised_mutations(overlay):
    assert _route(overlay, '/v1/workflows')
    assert _route(overlay, '/v1/workflows/owned')
    assert _route(overlay, '/v1/workflows', 'POST')
    for action in ('save','archive','restore','propose'):
        assert _route(overlay, '/v1/workflows/owned/'+action, 'POST')
    assert not _route(overlay, '/v1/workflows/owned/delete', 'POST')
    assert not _route(overlay, '/v1/workflows/owned', 'DELETE')


def test_channel_status_proxy_does_not_accept_lifecycle_mutations(overlay):
    assert _route(overlay,'/v1/channels')
    assert overlay._calls[-1]==('GET','/v1/channels')
    assert not _route(overlay,'/v1/channels/telegram/new-token','POST')


def test_file_skill_and_proposal_reads_preserve_identity_and_query(overlay):
    for path in ('/v1/sessions/owned/files', '/v1/sessions/owned/files/att_owned', '/v1/runtime/skills/detail?name=owned&category=fixture', '/v1/task-submissions/owned-nonce?session_id=owned'):
        assert _route(overlay,path)
        assert overlay._calls[-1]==('GET',path)
    assert not _route(overlay,'/v1/sessions/owned/files/att_owned','DELETE')


def test_mcp_lifecycle_proxy_only_known_transitions(overlay):
    for action in ('disconnect','reconnect'):
        path='/v1/runtime/mcp/owned/'+action
        assert _route(overlay,path,'POST')
        assert overlay._calls[-1]==('POST',path)
    assert not _route(overlay,'/v1/runtime/mcp/owned/install','POST')


def test_notification_proxy_preserves_read_and_preference_method(overlay):
    assert _route(overlay,'/v1/notifications')
    assert _route(overlay,'/v1/notifications','PATCH')
    assert overlay._calls[-2:]==[('GET','/v1/notifications'),('PATCH','/v1/notifications')]
    assert not _route(overlay,'/v1/notifications','DELETE')


def test_channel_controls_proxy_preserves_known_actions(overlay):
    for action in ('bind','connect','disconnect'):
        path='/v1/channels/telegram/'+action
        assert _route(overlay,path,'POST')
        assert overlay._calls[-1]==('POST',path)
    assert not _route(overlay,'/v1/channels/telegram/new-token','POST')
