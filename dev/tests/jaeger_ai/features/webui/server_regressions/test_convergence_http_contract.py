"""Wire-level characterization using real dispatch and JSON serialization.

Service health and session-backend inputs are deterministic; these probes open
no ports and invoke no external providers. Full server wiring and SSE still
need separate tests.
"""
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from api import auth, routes


class Handler:
    def __init__(self, method, path):
        self.command = method
        self.path = path
        self.headers = {"Content-Length": "2", "Content-Type": "application/json"}
        self.rfile = io.BytesIO(b"{}")
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 12345)
        self.response_headers = {}
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name.lower()] = value

    def end_headers(self):
        pass


def payload(handler):
    headers = handler.response_headers
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    body = handler.wfile.getvalue()
    assert int(headers["content-length"]) == len(body)
    return json.loads(body)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutating_dispatch_rejects_csrf_before_service_execution(monkeypatch, method):
    monkeypatch.setattr(routes, "_check_csrf", lambda handler: False)
    monkeypatch.setattr(routes, "_csrf_exempt_path", lambda path: False)
    monkeypatch.setattr(routes, "_csrf_rejection_error", lambda handler: "Cross-origin request rejected")
    monkeypatch.setattr(routes, "read_body", lambda handler: pytest.fail("must reject before reading body"))
    handler = Handler(method, "/api/mcp/servers/example")
    getattr(routes, "handle_" + method.lower())(handler, urlparse(handler.path))
    assert handler.status == 403
    assert payload(handler) == {"error": "Cross-origin request rejected"}


@pytest.mark.parametrize("health,status", [("ok", 200), ("blocked", 503)])
def test_health_dispatch_preserves_status_and_response_shape(monkeypatch, health, status):
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **k: False)
    monkeypatch.setattr(routes, "_streams_lock_health", lambda: {"status": health, "active_streams": 0})
    monkeypatch.setattr(routes, "_run_lifecycle_health", lambda: {"active_runs": 0, "runs": []})
    monkeypatch.setattr(routes, "_accept_loop_health", lambda handler: {"status": "ok"})
    monkeypatch.setattr(routes, "SESSIONS", {})
    handler = Handler("GET", "/health")
    routes.handle_get(handler, urlparse(handler.path))
    body = payload(handler)
    assert handler.status == status
    assert body["status"] == ("ok" if status == 200 else "degraded")
    assert set(body) == {
        "status", "sessions", "active_streams", "active_runs", "runs",
        "last_run_finished_at", "server_started_at", "uptime_seconds", "accept_loop",
    }
    assert body["sessions"] == body["active_streams"] == body["active_runs"] == 0
    assert body["runs"] == []
    assert body["last_run_finished_at"] is None
    assert isinstance(body["server_started_at"], (float, int))
    assert isinstance(body["uptime_seconds"], (float, int))


@pytest.fixture
def authentication_required(monkeypatch):
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "ensure_trusted_auth_session", lambda handler: None)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_api_auth_rejection_preserves_framing(authentication_required, method):
    handler = Handler(method, "/api/jaeger/sessions")
    assert auth.check_auth(handler, urlparse(handler.path)) is False
    assert handler.status == 401
    assert handler.response_headers["content-type"] == "application/json"
    body = handler.wfile.getvalue()
    assert int(handler.response_headers["content-length"]) == len(body)
    assert json.loads(body) == {"error": "Authentication required"}


def test_page_auth_redirect_preserves_query(authentication_required):
    handler = Handler("GET", "/?session=example&view=chat")
    assert auth.check_auth(handler, urlparse(handler.path)) is False
    assert handler.status == 302
    target = urlparse(handler.response_headers["location"])
    assert target.path == "login"
    assert parse_qs(target.query) == {"next": [handler.path]}
    assert handler.response_headers["content-length"] == "0"
    assert handler.wfile.getvalue() == b""


def test_profile_auth_denial_preserves_error_schema(authentication_required, monkeypatch):
    monkeypatch.setattr(auth, "ensure_trusted_auth_session", lambda handler: {"username": "test"})
    monkeypatch.setattr(auth, "trusted_session_allows_active_profile", lambda session: False)
    handler = Handler("GET", "/api/session")
    assert auth.check_auth(handler, urlparse(handler.path)) is False
    assert handler.status == 403
    body = handler.wfile.getvalue()
    assert int(handler.response_headers["content-length"]) == len(body)
    assert json.loads(body) == {"error": "Profile access forbidden"}
