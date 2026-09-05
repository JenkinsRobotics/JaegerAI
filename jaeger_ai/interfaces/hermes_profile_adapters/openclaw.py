#!/usr/bin/env python3
"""Hermes WebUI runs-API adapter for the local OpenClaw gateway."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_ADAPTER_BASE_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN_FILE = Path(os.environ.get(
    "OPENCLAW_ADAPTER_TOKEN_FILE",
    str(Path.home() / ".ares/openclaw/gateway.token"),
))
ADAPTER_HOST = os.environ.get("OPENCLAW_ADAPTER_HOST", "192.168.64.1")
ADAPTER_PORT = int(os.environ.get("OPENCLAW_ADAPTER_PORT", "8644"))
_request_timeout_setting = os.environ.get("OPENCLAW_ADAPTER_REQUEST_TIMEOUT", "").strip()
REQUEST_TIMEOUT = float(_request_timeout_setting) if _request_timeout_setting else None

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


def chat_openclaw(message: str, session_id: str = "") -> str:
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
    with urllib.request.urlopen(request, **open_kwargs) as response:
        payload = json.loads(response.read())
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("OpenClaw returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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
            self.send_events(match.group(1))
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self.create_chat_completion()
            return
        if self.path == "/v1/runs":
            self.create_run()
            return
        match = re.match(r"^/v1/runs/([\w-]+)/(?:cancel|stop)$", self.path)
        if match:
            with _runs_lock:
                if match.group(1) in _runs:
                    _runs[match.group(1)]["status"] = "cancelled"
            self.send_json(200, {"run_id": match.group(1), "status": "cancelled"})
            return
        self.send_json(404, {"error": "not found"})

    def create_chat_completion(self):
        """Serve Hermes' OpenAI-compatible fallback over the OpenClaw agent."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        messages = body.get("messages") or []
        message = "\n".join(
            str(item.get("content", "")) if isinstance(item, dict) else str(item)
            for item in messages
            if not isinstance(item, dict) or item.get("role") != "system"
        )
        session_id = str(self.headers.get("X-Hermes-Session-Id") or body.get("user") or "")
        try:
            result = chat_openclaw(message, session_id)
        except Exception as exc:
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                detail = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            self.send_json(502, {"error": {"message": detail}})
            return
        if body.get("stream"):
            completion_id = f"chatcmpl-{uuid.uuid4().hex}"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.write_event({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": result}, "finish_reason": None}],
            })
            self.write_event({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.send_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result}, "finish_reason": "stop"}],
        })

    def create_run(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
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
    ThreadingHTTPServer((ADAPTER_HOST, ADAPTER_PORT), Handler).serve_forever()
