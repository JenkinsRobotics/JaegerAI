"""Loopback HTTP gateway for the Jaeger-owned ARES-derived WebUI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bridge_client import BridgeClient, WebBridgeError

STATIC_ROOT = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000


class ApprovalBroker:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: dict[str, dict[str, Any]] = {}

    def request(self, frame: dict[str, Any]) -> str:
        request_id = str(frame.get("id") or uuid.uuid4().hex)
        with self._condition:
            self._pending[request_id] = {**frame, "id": request_id, "created_at": time.time(), "answer": None}
            self._condition.notify_all()
            deadline = time.monotonic() + 120
            while self._pending[request_id]["answer"] is None and time.monotonic() < deadline:
                self._condition.wait(timeout=1)
            answer = str(self._pending[request_id].get("answer") or "deny")
            self._pending.pop(request_id, None)
            return answer

    def list(self) -> list[dict[str, Any]]:
        with self._condition:
            return [{key: value for key, value in row.items() if key != "answer"} for row in self._pending.values()]

    def respond(self, request_id: str, answer: str) -> bool:
        if answer not in {"once", "always", "deny"}:
            raise ValueError("answer must be once, always, or deny")
        with self._condition:
            if request_id not in self._pending:
                return False
            self._pending[request_id]["answer"] = answer
            self._condition.notify_all()
            return True


class ChatBroker:
    def __init__(self, bridge: BridgeClient, approvals: ApprovalBroker) -> None:
        self.bridge = bridge
        self.approvals = approvals
        self._condition = threading.Condition()
        self._runs: dict[str, dict[str, Any]] = {}

    def start(self, text: str, session: str) -> str:
        run_id = uuid.uuid4().hex
        with self._condition:
            self._runs[run_id] = {"events": [], "done": False, "session_id": session}
        threading.Thread(target=self._worker, args=(run_id, text, session), daemon=True, name=f"jaeger-web-{run_id[:8]}").start()
        return run_id

    def _worker(self, run_id: str, text: str, session: str) -> None:
        try:
            result = self.bridge.turn(text, session, lambda frame: self.push(run_id, frame), self.approvals.request)
            self.push(run_id, {"type": "reply", **result, "session_id": session})
        except Exception as exc:  # noqa: BLE001
            self.push(run_id, {"type": "reply", "text": "", "error": str(exc), "session_id": session})
        finally:
            with self._condition:
                self._runs[run_id]["done"] = True
                self._condition.notify_all()

    def push(self, run_id: str, frame: dict[str, Any]) -> None:
        with self._condition:
            self._runs[run_id]["events"].append(frame)
            self._condition.notify_all()

    def stream(self, run_id: str, index: int) -> tuple[list[dict[str, Any]], bool]:
        with self._condition:
            if run_id not in self._runs:
                raise ValueError("chat stream not found")
            if len(self._runs[run_id]["events"]) <= index and not self._runs[run_id]["done"]:
                self._condition.wait(timeout=10)
            run = self._runs[run_id]
            return list(run["events"][index:]), bool(run["done"])


class WebHandler(BaseHTTPRequestHandler):
    server_version = "JaegerWeb/0.1"

    @property
    def bridge(self) -> BridgeClient:
        return self.server.bridge  # type: ignore[attr-defined]

    @property
    def approvals(self) -> ApprovalBroker:
        return self.server.approvals  # type: ignore[attr-defined]

    @property
    def chats(self) -> ChatBroker:
        return self.server.chats  # type: ignore[attr-defined]

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
                "/api/approvals": self.approvals.list,
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
            if parsed.path == "/api/chat/stream":
                query = parse_qs(parsed.query)
                return self._sse(str(query.get("id", [""])[0]))
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
            if parsed.path == "/api/chat/start":
                text = str(body.get("message") or "").strip()
                session = str(body.get("session_id") or "").strip()
                if not text or not session:
                    return self._json({"error": "message and session_id are required"}, HTTPStatus.BAD_REQUEST)
                return self._json({"stream_id": self.chats.start(text, session), "session_id": session})
            if parsed.path == "/api/approvals/respond":
                ok = self.approvals.respond(str(body.get("id") or ""), str(body.get("answer") or "deny"))
                return self._json({"ok": ok}, HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND)
            if parsed.path == "/api/settings":
                return self._json(self.bridge.command("settings_set", body))
            if parsed.path == "/api/models/select":
                return self._json(self.bridge.command("configure_model", body))
            if parsed.path == "/api/schedules":
                return self._json(self.bridge.command("create_schedule", body))
            if parsed.path.startswith("/api/schedules/"):
                action = parsed.path.rsplit("/", 1)[-1]
                command = {"pause": "pause_schedule", "resume": "resume_schedule", "cancel": "cancel_schedule"}.get(action)
                if not command:
                    return self._json({"error": "unknown schedule action"}, HTTPStatus.NOT_FOUND)
                return self._json(self.bridge.command(command, body))
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

    def _sse(self, run_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        index = 0
        while True:
            events, done = self.chats.stream(run_id, index)
            for frame in events:
                payload = json.dumps(frame, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                index += 1
            self.wfile.flush()
            if done and not events:
                self.wfile.write(b"event: done\ndata: {}\n\n")
                self.wfile.flush()
                return

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
        self.approvals = ApprovalBroker()
        self.chats = ChatBroker(self.bridge, self.approvals)


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
