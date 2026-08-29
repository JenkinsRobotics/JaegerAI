"""Loopback HTTP gateway for the Jaeger-owned ARES-derived WebUI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bridge_client import BridgeClient, WebBridgeError

STATIC_ROOT = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000


class WebHandler(BaseHTTPRequestHandler):
    server_version = "JaegerWeb/0.1"

    @property
    def bridge(self) -> BridgeClient:
        return self.server.bridge  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            routes = {
                "/api/health": self.bridge.health,
                "/api/identity": lambda: self.bridge.query("identity"),
                "/api/models": lambda: self.bridge.query("model_catalog"),
                "/api/tools": lambda: self.bridge.query("list_tools"),
                "/api/heartbeat": lambda: self.bridge.query("heartbeat"),
                "/api/schedules": lambda: self.bridge.query("list_schedules"),
            }
            if parsed.path in routes:
                return self._json(routes[parsed.path]())
            if parsed.path == "/api/sessions":
                query = parse_qs(parsed.query)
                limit = min(max(int(query.get("limit", [50])[0]), 1), 200)
                return self._json(self.bridge.query("list_sessions", {"limit": limit}))
            if parsed.path == "/api/session":
                session_id = str(parse_qs(parsed.query).get("id", [""])[0]).strip()
                if not session_id:
                    return self._json({"error": "id is required"}, HTTPStatus.BAD_REQUEST)
                return self._json(self.bridge.query("load_session", {"id": session_id, "resume": False}))
            return self._static(parsed.path)
        except (WebBridgeError, ValueError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/session/new":
                return self._json(self.bridge.command("new_session", {"old_id": body.get("old_id")}))
            if parsed.path == "/api/chat":
                text = str(body.get("message") or "").strip()
                session = str(body.get("session_id") or "").strip()
                if not text or not session:
                    return self._json({"error": "message and session_id are required"}, HTTPStatus.BAD_REQUEST)
                events: list[dict[str, Any]] = []
                result = self.bridge.turn(text, session, events.append)
                return self._json({**result, "events": events, "session_id": session})
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (WebBridgeError, ValueError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in target.parents or not target.is_file():
            target = STATIC_ROOT / "index.html"
        raw = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[jaeger-web] {self.address_string()} {fmt % args}", flush=True)


class JaegerWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], instance: str | None = None) -> None:
        super().__init__(address, WebHandler)
        self.bridge = BridgeClient(instance)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Jaeger-owned browser UI")
    parser.add_argument("--host", default=os.environ.get("JAEGER_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JAEGER_WEB_PORT", "8790")))
    parser.add_argument("--instance", default=os.environ.get("JAEGER_INSTANCE_NAME") or None)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Jaeger WebUI binds to loopback only; use Tailscale Serve for remote access")
    server = JaegerWebServer((args.host, args.port), args.instance)
    print(f"[jaeger-web] http://{args.host}:{args.port} · instance={server.bridge.instance}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
