#!/usr/bin/env python3
"""Hermes WebUI runs-API adapter for the local OpenClaw gateway."""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler
from .ingress import ProfileHTTPServer
from pathlib import Path
from .resilience import CircuitBreaker, timeout_setting, failure_category
from .native_runs import Runs, RunsHTTP, profile_key

OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_ADAPTER_BASE_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN_FILE = Path(os.environ.get(
    "OPENCLAW_ADAPTER_TOKEN_FILE",
    str(Path.home() / ".ares/openclaw/gateway.token"),
))
ADAPTER_HOST = os.environ.get("OPENCLAW_ADAPTER_HOST", "0.0.0.0")
ADAPTER_PORT = int(os.environ.get("OPENCLAW_ADAPTER_PORT", "8644"))
REQUEST_TIMEOUT = timeout_setting("OPENCLAW_ADAPTER_REQUEST_TIMEOUT")
_circuit = CircuitBreaker()

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()
_native_runs = None
_native_lock = threading.Lock()


def chat_openclaw(message: str, session_id: str = "") -> str:
    _circuit.check()
    token = OPENCLAW_TOKEN_FILE.read_text(encoding="utf-8").strip()
    body = {
        "model": "openclaw/default",
        "messages": [{"role": "user", "content": message}],
        "stream": False,
    }
    if session_id:
        body["user"] = f"hermes:{session_id}"
    request = urllib.request.Request(
        f"{OPENCLAW_BASE_URL.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    open_kwargs = {} if REQUEST_TIMEOUT is None else {"timeout": REQUEST_TIMEOUT}
    try:
        with urllib.request.urlopen(request, **open_kwargs) as response:
            payload = json.loads(response.read())
    except (OSError, TimeoutError) as exc:
        if not isinstance(exc, urllib.error.HTTPError) or exc.code >= 500:
            _circuit.failure()
        raise  # A failed response is not authorization to execute the turn twice.
    _circuit.success()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("OpenClaw returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


class Handler(RunsHTTP, BaseHTTPRequestHandler):
    def native_key(self):
        return profile_key("openclaw")

    def native_runs(self):
        global _native_runs
        from .openclaw_native import openclaw_turn
        with _native_lock:
            if _native_runs is None:
                root = Path(__file__).resolve().parents[3] / ".jaeger_ai/shared/webui-runs/openclaw"
                _native_runs = Runs(root, openclaw_turn)
            return _native_runs

    def native_enabled(self):
        return os.environ.get("OPENCLAW_ADAPTER_NATIVE_RUNS", "").lower() in {"1", "true"}

    def native_capabilities(self):
        value = super().native_capabilities()
        value['features'].update(workspace_override=False, model_override=True)
        return value

    def do_GET(self):
        if self.native_enabled() and self.native_route("GET"):
            return
        if self.path in ("/health", "/v1/health", "/health/detailed"):
            self.send_json(200, {"ok": True, "status": "ready"})
            return
        if self.path == "/v1/capabilities":
            self.send_json(200, {
                "streaming": True,
                "models": [{"id": "openclaw", "name": "OpenClaw", "provider": "openclaw"}],
                "approval": False,
            })
            return
        match = re.match(r"^/v1/runs/([\w-]+)(?:/events)?$", self.path)
        if match:
            if not self.profile_authorized():
                return
            self.send_events(match.group(1))
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.native_enabled() and self.native_route("POST"):
            return
        if not self.legacy_post_authorized():
            return
        if self.path == "/v1/chat/completions":
            self.create_chat_completion()
            return
        if self.path == "/v1/runs":
            self.create_run()
            return
        match = re.match(r"^/v1/runs/([\w-]+)/(?:cancel|stop)$", self.path)
        if match:
            with _runs_lock:
                exists = match.group(1) in _runs
            self.send_json(501 if exists else 404, {
                'error': 'Legacy OpenClaw cannot confirm native cancellation; work may still be running.' if exists else 'Run not found',
                'error_category': 'unsupported_control' if exists else 'not_found'})
            return
        self.send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.native_json(403, {'error': 'Use the authenticated WebUI server proxy'})

    def create_chat_completion(self):
        """Serve Hermes' OpenAI-compatible fallback over the OpenClaw agent."""
        body = getattr(self, '_request_body', None)
        if body is None:  # Direct internal callers; HTTP ingress already parsed.
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        messages = body.get("messages") or []
        # The native session already contains earlier turns. Re-inserting the
        # entire WebUI transcript duplicates work and grows context each turn.
        message = next((item.get("content", "") for item in reversed(messages)
                        if isinstance(item, dict) and item.get("role") == "user"), "")
        session_id = str(self.headers.get("X-Hermes-Session-Id") or body.get("user") or "")
        if body.get("stream"):
            self.stream_chat_completion(message, session_id)
            return
        try:
            result = chat_openclaw(message, session_id)
        except Exception as exc:
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                detail = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            category = failure_category(exc)
            self.send_json(504 if category == "timeout" else 502,
                           {"error": {"message": detail, "type": category}})
            return
        self.send_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result}, "finish_reason": "stop"}],
        })

    def stream_chat_completion(self, message, session_id):
        """Relay actual upstream deltas, with prompt heartbeat and typed errors.

        This fallback deliberately does not advertise approvals. Native gateway
        pairing is required for that capability; an HTTP stream cannot supply it.
        """
        events = queue.Queue(maxsize=256)
        disconnected = threading.Event()

        def enqueue(value):
            while not disconnected.is_set():
                try:
                    events.put(value, timeout=.2)
                    return
                except queue.Full:
                    pass

        def read_upstream():
            try:
                _circuit.check()
                token = OPENCLAW_TOKEN_FILE.read_text().strip()
                request = urllib.request.Request(
                    f"{OPENCLAW_BASE_URL.rstrip('/')}/v1/chat/completions",
                    data=json.dumps({"model": "openclaw/default", "stream": True,
                        "messages": [{"role": "user", "content": message}],
                        **({"user": f"hermes:{session_id}"} if session_id else {})}).encode(),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    complete = False
                    for line in response:
                        if disconnected.is_set():
                            return
                        if not line.startswith(b"data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == b"[DONE]":
                            complete = True
                            break
                        data = json.loads(payload)
                        enqueue(data)
                    if not complete:
                        raise ConnectionError("OpenClaw stream ended without completion; native state may be unknown")
                _circuit.success()
            except Exception as exc:
                _circuit.failure()
                enqueue({"error": {"message": str(exc), "type": failure_category(exc)}})
            finally:
                enqueue(None)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        threading.Thread(target=read_upstream, daemon=True).start()
        try:
            while True:
                try:
                    event = events.get(timeout=1)
                except queue.Empty:
                    self.wfile.write(b": upstream pending\n\n")
                    self.wfile.flush()
                    continue
                if event is None:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    break
                self.write_event(event)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            disconnected.set()

    def create_run(self):
        body = self._request_body
        message = body.get("input") or body.get("message") or ""
        if isinstance(message, list):
            message = "\n".join(
                str(item.get("content", "")) if isinstance(item, dict) else str(item)
                for item in message
            )
        run_id = uuid.uuid4().hex
        session_id = str(body.get("session_id") or self.headers.get("X-Hermes-Session-Id") or "")
        with _runs_lock:
            _runs[run_id] = {"status": "running", "result": "", "error": ""}

        def run():
            try:
                result = chat_openclaw(str(message), session_id)
                with _runs_lock:
                    _runs[run_id].update(status="completed", result=result)
            except Exception as exc:
                detail = str(exc)
                if isinstance(exc, urllib.error.HTTPError):
                    detail = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
                with _runs_lock:
                    _runs[run_id].update(status="failed", error=detail)

        threading.Thread(target=run, daemon=True).start()
        self.send_json(200, {"run_id": run_id, "status": "running"})

    def send_events(self, run_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        while True:
            with _runs_lock:
                run = dict(_runs.get(run_id) or {})
            status = run.get("status")
            if not status:
                self.write_event({"event": "error", "message": "run not found"})
                return
            if status == "completed":
                self.write_event({"event": "message.delta", "delta": run.get("result", "")})
                self.write_event({"event": "run.completed", "run_id": run_id})
                return
            if status in ("failed", "cancelled"):
                self.write_event({"event": f"run.{status}", "error": run.get("error", "")})
                return
            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
            time.sleep(1)

    def write_event(self, data: dict):
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def send_json(self, status: int, data: dict):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[openclaw-adapter] {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"[openclaw-adapter] listening on {ADAPTER_HOST}:{ADAPTER_PORT}", flush=True)
    ProfileHTTPServer((ADAPTER_HOST, ADAPTER_PORT), Handler).serve_forever()
