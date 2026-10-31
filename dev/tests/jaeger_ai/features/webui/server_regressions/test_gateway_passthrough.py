"""WebUI (:8790) relays today's Gateway routes through one allowlist, with the webui caller's auth."""
from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

import api.jaeger_agents as jaeger_agents
import api.jaeger_sessions as js
from jaeger_ai.core.gateway.caller_auth import client_headers

CASES = [
    ("GET", "/v1/activity?limit=5&agent_id=codex", None),
    ("POST", "/v1/handoffs/h-1/check", {"state": "passed"}),
    ("GET", "/v1/approvals/counts", None),
    ("GET", "/v1/approvals/ap-1/events?format=json", None),
    ("POST", "/v1/approvals/batch", {"ids": ["a", "b"], "decision": "approve"}),
    ("POST", "/v1/approvals/requests", {"source": "widget", "title": "t", "risk": "low"}),
    ("POST", "/v1/approvals/ap-1/decide", {"decision": "deny", "reason": "no"}),
    ("POST", "/v1/approvals/ap-1/viewed", {}),
    ("GET", "/v1/notifications?category=approvals", None),
    ("PATCH", "/v1/notifications", {"quiet_hours": {"start": "22:00", "end": "07:00"}}),
    ("GET", "/v1/push/queue", None),
    ("GET", "/v1/push/subscriptions", None),
    ("GET", "/v1/push/vapid-public-key", None),
    ("POST", "/v1/push/subscriptions", {"endpoint": "https://push.example/x"}),
    ("POST", "/v1/push/test", {}),
    ("POST", "/v1/push/job-events", {"job_id": "j1", "state": "stuck"}),
    ("DELETE", "/v1/push/subscriptions/sub_1", None),
]
NOT_PROXIED = [("GET", "/v1/approvals/inbox"), ("POST", "/v1/approvals/inbox/batch"),
               ("POST", "/v1/approvals/inbox/x/decide"), ("GET", "/v1/widgets"), ("GET", "/v1/machine/health"),
               ("GET", "/v1/robots"), ("GET", "/v1/providers/cli"), ("GET", "/v1/resources"),
               ("POST", "/v1/activity"), ("DELETE", "/v1/notifications")]


@pytest.fixture
def gateway(monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def _any(self):
            n = int(self.headers.get("Content-Length") or 0)
            seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                         "body": json.loads(self.rfile.read(n) or b"null") if n else None})
            out = json.dumps({"ok": True, "path": self.path}).encode()
            self.send_response(207 if self.command == "PATCH" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        do_GET = do_POST = do_PATCH = do_DELETE = _any

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(js, "gateway_base", lambda: f"http://127.0.0.1:{srv.server_port}")
    yield seen
    srv.shutdown()


class _Handler:
    def __init__(self, method, body):
        self.command = method
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO(b"")
        self.client_address = ("127.0.0.1", 1)
        self._json_body_bytes = json.dumps(body).encode() if body is not None else None

    def send_response(self, s):
        self.status = s

    def send_header(self, k, v):
        self.headers[k] = v

    def end_headers(self):
        pass


@pytest.mark.parametrize("method,url,body", CASES)
def test_new_gateway_routes_pass_through_with_auth(gateway, method, url, body):
    h = _Handler(method, body)
    assert jaeger_agents.route(h, urlparse(url), method) is True  # the WebUI's mounted dispatch hook
    got = gateway[-1]
    assert got["method"] == method and got["path"] == url  # path + query intact
    assert got["auth"] and got["auth"] == client_headers("webui")["Authorization"]
    if method in ("POST", "PATCH"):
        assert got["body"] == body
    assert h.status == (207 if method == "PATCH" else 200)  # gateway status relayed
    assert json.loads(h.wfile.getvalue())["path"] == url


@pytest.mark.parametrize("method,path", NOT_PROXIED)
def test_webui_owned_or_unserved_routes_are_not_in_the_allowlist(method, path):
    assert not js.passthrough_match(path, method)


def test_allowlist_routes_exist_on_the_gateway(tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    g = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
    served = {(r.method, r.resource.canonical) for r in g.app.router.routes() if r.resource}
    import re
    for method, url, _ in CASES:
        path = urlparse(url).path
        assert any(m == method and re.fullmatch(re.sub(r"\\\{[^}]+\\\}|\{[^}]+\}", "[^/]+", re.escape(c).replace(r"\{", "{").replace(r"\}", "}")), path)
                   for m, c in served), (method, path)
