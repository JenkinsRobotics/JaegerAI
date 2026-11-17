"""The browser surface on 127.0.0.1:8790, hosted inside the Gateway process (R11).

Replaces the separate Hermes-fork WebUI service. Tailscale Serve keeps
proxying ``/`` to this port, so phone and remote access are unchanged. The
handler modules are synchronous (``send_response``/``wfile``), so they run in
a stdlib threading server on a daemon thread; Gateway calls go over loopback.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import jaeger_ai.core.gateway.webapp  # noqa: F401  (aliases ``api``)
from api.helpers import _CLIENT_DISCONNECT_ERRORS, j, read_body, reset_request_body_consumed

log = logging.getLogger("jaeger.webapp")
DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8790


def _gateway_proxy(handler, method: str, path: str, body: bytes | None = None) -> bool:
    from api.jaeger_sessions import _proxy
    return _proxy(handler, method, path, body)


def _same_origin(handler) -> bool:
    """Browser writes must come from this page (Origin/Sec-Fetch-Site), not another site."""
    site = (handler.headers.get("Sec-Fetch-Site") or "").lower()
    if site in ("cross-site",):
        return False
    origin = handler.headers.get("Origin")
    if not origin or origin == "null":
        return site in ("", "same-origin", "none")
    host = (handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "").lower()
    return urlparse(origin).netloc.lower() in {host, (handler.headers.get("Host") or "").lower()}


def handle_get(h, parsed) -> bool:
    from api.jaeger_browser import route as browser_route
    if browser_route(h, parsed, "GET"):
        return True
    from api.character_scenes import route as scene_route
    if scene_route(h, parsed):
        return True
    from api.jaeger_agents import route as agents_route
    if agents_route(h, parsed, "GET"):
        return True
    from api.jaeger_conversation import route as conversation_route
    if conversation_route(h, parsed, "GET"):
        return True
    path = parsed.path
    if path in ("/session/manifest.json", "/session/manifest.webmanifest"):
        from api.ui_shell import serve
        return serve(h, parsed._replace(path="/manifest.json"))
    from api.ui_shell import serve as serve_ui
    if serve_ui(h, parsed):
        return True
    from api import workspace_api
    if workspace_api.route(h, parsed, "GET"):
        return True
    from api import unified_api
    if unified_api.route(h, parsed, "GET", read_body, j):
        return True
    qs = ("?" + parsed.query) if parsed.query else ""
    if path == "/v1/dashboard":
        from api import dashboard_store
        return j(h, dashboard_store.read())
    if path in ("/v1/system/metrics", "/v1/system/status"):
        from api import system_metrics
        return j(h, system_metrics.metrics() if path.endswith("metrics") else system_metrics.status())
    if path == "/v1/first-run":
        return _gateway_proxy(h, "GET", "/v1/first-run")
    if path == "/v1/gateway-health":
        return _gateway_proxy(h, "GET", "/health")
    if path == "/v1/apps" or path.startswith("/v1/apps/"):
        return _gateway_proxy(h, "GET", path + qs)
    if path in ("/api/agents", "/v1/agents"):
        return _gateway_proxy(h, "GET", "/v1/agents" + qs)
    if path.startswith(("/api/agents/", "/v1/agents/")):
        suffix = path.split("/agents/", 1)[-1]
        if suffix and not suffix.endswith("/activate"):
            return _gateway_proxy(h, "GET", f"/v1/agents/{suffix}")
    return _retired_api(h, path)


_POST_ONLY = {"/api/default-model", "/api/jaeger/transcribe", "/api/jaeger/tts", "/api/jaeger/vision/describe",
              "/api/terminal/input", "/api/terminal/start", "/api/terminal/close"}


def _retired_api(h, path: str) -> bool:
    if path in _POST_ONLY and h.command == "GET":
        return False
    if path.startswith("/api/"):
        return j(h, {"error": "retired", "detail": "This legacy /api route was removed; use the Gateway /v1 API."}, status=410)
    return False


def handle_write(h, parsed) -> bool:
    method = h.command
    from api.jaeger_browser import route as browser_route
    if method == "POST" and browser_route(h, parsed, "POST"):
        return True
    if parsed.path != "/api/csp-report" and not _same_origin(h):
        return j(h, {"error": "Cross-origin request rejected"}, status=403)
    from api import unified_api
    if unified_api.route(h, parsed, method, read_body, j):
        return True
    from api.jaeger_agents import route as agents_route
    if agents_route(h, parsed, method):
        return True
    if method == "POST":
        from api.jaeger_conversation import route as conversation_route
        if conversation_route(h, parsed, "POST"):
            return True
        from api import workspace_api
        if workspace_api.route(h, parsed, "POST"):
            return True
    path = parsed.path
    if method == "PUT" and path == "/v1/dashboard":
        from api import dashboard_store
        try:
            return j(h, dashboard_store.write(read_body(h)))
        except ValueError as exc:
            return j(h, {"error": str(exc)}, status=400)
    if method != "POST":
        return _retired_api(h, path)
    raw = lambda: json.dumps(read_body(h) or {}).encode("utf-8")  # noqa: E731
    if path in ("/v1/first-run/setup", "/v1/first-run/skip"):
        return _gateway_proxy(h, "POST", path, raw())
    if path.startswith("/v1/apps/") and path.endswith(("/proposals", "/decision", "/rollback")):
        return _gateway_proxy(h, "POST", path, raw())
    if path.startswith(("/api/agents/", "/v1/agents/")) and path.endswith("/handoff"):
        return _gateway_proxy(h, "POST", "/v1/agents/" + path.split("/agents/", 1)[-1], raw())
    if path.startswith(("/api/approvals/", "/v1/approvals/")):
        return _gateway_proxy(h, "POST", "/v1/approvals/" + path.split("/approvals/", 1)[-1], raw())
    if path.startswith(("/api/sessions/", "/v1/sessions/")) and path.endswith("/handoff"):
        return _gateway_proxy(h, "POST", "/v1/sessions/" + path.split("/sessions/", 1)[-1], raw())
    if path in ("/api/agents", "/v1/agents"):
        return _gateway_proxy(h, "POST", "/v1/agents", raw())
    if path.startswith(("/api/agents/", "/v1/agents/")) and path.endswith("/activate"):
        return _gateway_proxy(h, "POST", "/v1/agents/" + path.split("/agents/", 1)[-1])
    return _retired_api(h, path)


class Handler(BaseHTTPRequestHandler):
    server_version = "JaegerWebApp/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; errors are logged below
        return

    def send_response(self, code, message=None):
        self._jg_sent_headers = set()
        super().send_response(code, message)

    def send_header(self, keyword, value):
        getattr(self, "_jg_sent_headers", set()).add(keyword.lower())
        super().send_header(keyword, value)

    def end_headers(self):
        """Every response carries the security headers (CSP, frame and permission policy)."""
        from api.helpers import CSP
        sent = getattr(self, "_jg_sent_headers", set())
        for name, value in (("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                            ("Referrer-Policy", "same-origin"), ("Content-Security-Policy", CSP),
                            ("Permissions-Policy", "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)")):
            if name.lower() not in sent:
                super().send_header(name, value)
        super().end_headers()

    def _run(self, fn) -> None:
        self._jg_responded = False
        reset_request_body_consumed(self)
        try:
            parsed = urlparse(self.path)
            from api.jaeger_signin import gate
            if not gate(self, parsed):
                return
            if fn(self, parsed) is False and not self._jg_responded:
                j(self, {"error": "not found"}, status=404)
        except _CLIENT_DISCONNECT_ERRORS:
            return
        except Exception as exc:  # noqa: BLE001
            if "was cut" in str(exc) or "retired" in str(exc):
                try:
                    return j(self, {"error": "retired", "detail": str(exc)}, status=410)
                except Exception:  # noqa: BLE001
                    return
            log.error("webapp %s %s failed\n%s", self.command, self.path, traceback.format_exc())
            try:
                if not self._jg_responded:
                    j(self, {"error": "Internal server error"}, status=500)
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                from api.helpers import consume_unread_request_body
                consume_unread_request_body(self)
            except Exception:  # noqa: BLE001
                self.close_connection = True

    def do_GET(self):
        self._run(handle_get)

    def do_HEAD(self):
        self._run(handle_get)

    def do_POST(self):
        self._run(handle_write)

    do_PUT = do_PATCH = do_DELETE = do_POST


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


_started: dict = {}


def _env_defaults() -> None:
    """Default WebUI state paths and labels, set once before the server binds."""
    from jaeger_ai.core.instance.instance import operator_state_root
    state = operator_state_root()
    os.environ.setdefault("JAEGER_WEBUI_AGENT_STATE", str(state / "webui-agent"))
    os.environ.setdefault("JAEGER_WEBUI_STATE_DIR", str(state / "hermes-webui-state"))
    os.environ.setdefault("JAEGER_WEBUI_BOT_NAME", "JaegerAI")
    os.environ.setdefault("JAEGER_WEBUI_WORKSPACE", str(Path.home() / "workspace"))
    os.environ.setdefault("JAEGER_OLLAMA_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("JAEGER_WEBUI_EXTENSION_DIR", str(Path(__file__).resolve().parents[3] / "assets"))
    if not os.environ.get("JAEGER_GATEWAY_URL"):
        from jaeger_ai.contract.ports import resolve_gateway_url
        os.environ["JAEGER_GATEWAY_URL"] = resolve_gateway_url()


def _bind_loop(host: str, port: int, ready: threading.Event) -> None:
    warned = False
    while True:
        try:
            srv = _Server((host, port), Handler)
            break
        except OSError as exc:
            if not warned:
                log.warning("webapp waiting for %s:%s (%s); retrying every 5 s", host, port, exc)
                warned = True
            time.sleep(5.0)
    _started[(host, port)] = srv
    log.info("webapp serving on http://%s:%s", host, port)
    print(f"[jaeger-gateway] Web app on http://{host}:{port}", flush=True)
    ready.set()
    try:
        from api.jaeger_agents import warm_kokoro_in_background
        warm_kokoro_in_background()
    except Exception:  # noqa: BLE001
        pass
    srv.serve_forever()


def start(host: str | None = None, port: int | None = None, wait: float = 0.0) -> threading.Event:
    """Serve the web app on a daemon thread. Binding retries in the background
    (the port may still be held by a stopping process); the returned event is
    set once it is listening."""
    host = host or os.environ.get("JAEGER_WEBAPP_HOST", DEFAULT_HOST)
    port = int(port or os.environ.get("JAEGER_WEBAPP_PORT") or DEFAULT_PORT)
    _env_defaults()
    ready = threading.Event()
    threading.Thread(target=_bind_loop, args=(host, port, ready), name=f"jaeger-webapp-{port}", daemon=True).start()
    if wait:
        ready.wait(wait)
    return ready


if __name__ == "__main__":  # standalone check: python -m jaeger_ai.core.gateway.webapp.server
    logging.basicConfig(level=logging.INFO)
    start()
    threading.Event().wait()
