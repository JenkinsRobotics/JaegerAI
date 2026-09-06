#!/usr/bin/env python3
"""Jaeger MCP-to-REST adapter for Hermes WebUI gateway mode.

Translates Hermes WebUI REST API calls into MCP tool calls to the Jaeger
agent gateway, so the WebUI can chat with Jaeger through gateway profiles.

Supports both /v1/chat/completions (SSE streaming) and /v1/runs APIs.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Any
import urllib.request
import urllib.error
from pathlib import Path
from .resilience import CircuitBreaker, timeout_setting
from .native_runs import Runs, RunsHTTP, jaeger_turn, jaeger_reconcile, profile_key

# ── Config ──────────────────────────────────────────────────────────────────

MCP_GATEWAY_URL = os.environ.get("JAEGERS_MCP_URL", "http://127.0.0.1:8811/mcp")
def _profile_secret(name: str) -> str:
    """Read a local profile secret without baking credentials into source."""
    direct = os.environ.get(name, "").strip()
    if direct:
        return direct
    env_path = Path.home() / ".hermes" / "profiles" / "jaeger" / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


MCP_API_KEY = os.environ.get("JAEGERS_MCP_API_KEY", "").strip() or _profile_secret("MCP_ARES_HOST_API_KEY")
MCP_HOST_HEADER = os.environ.get("JAEGERS_MCP_HOST", "127.0.0.1:8811")
ADAPTER_PORT = int(os.environ.get("JAEGERS_ADAPTER_PORT", "8642"))
REQUEST_TIMEOUT = timeout_setting("JAEGERS_ADAPTER_REQUEST_TIMEOUT")


def _is_transient_http(exc: BaseException) -> bool:
    """True when a retry may succeed (dropped socket, gateway blip, 502/503/504)."""
    if isinstance(exc, (
        ConnectionError,
        TimeoutError,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
        http.client.BadStatusLine,
    )):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {400, 404, 502, 503, 504}
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return _is_transient_http(exc.reason)
    return isinstance(exc, urllib.error.URLError)


# ── MCP Client ──────────────────────────────────────────────────────────────

class MCPClient:
    """Minimal MCP JSON-RPC client with SSE session management."""

    def __init__(self, base_url: str, api_key: str, host_header: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.host_header = host_header
        self._session_id: str | None = None
        self._lock = threading.RLock()
        self._req_id = 0
        self._circuit = CircuitBreaker()

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _headers(self, extra: dict | None = None) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "Host": self.host_header,
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        if extra:
            h.update(extra)
        return h

    def _parse_sse(self, raw: bytes) -> list[dict]:
        if raw.lstrip().startswith(b"{"):
            return [json.loads(raw)]
        results = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("data: "):
                payload = line[6:]
                try:
                    results.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
        return results

    def initialize(self) -> dict:
        with self._lock:
            body = json.dumps({
                "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "jaeger-bridge-adapter", "version": "0.1"},
                }
            }).encode("utf-8")
            req = urllib.request.Request(self.base_url, data=body, headers=self._headers(), method="POST")
            # Only the handshake is bounded; this is not a deadline on tool work.
            open_kwargs = {"timeout": 15.0}
            with urllib.request.urlopen(req, **open_kwargs) as resp:
                session_id = resp.getheader("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                data = resp.read()
                results = self._parse_sse(data)
                return results[0] if results else {}

    def _execute_call(self, name: str, arguments: dict[str, Any]) -> dict:
        body = json.dumps({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
            "params": {"name": name, "arguments": arguments}
        }).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=body, headers=self._headers(), method="POST")
        open_kwargs = {} if REQUEST_TIMEOUT is None else {"timeout": REQUEST_TIMEOUT}
        with urllib.request.urlopen(req, **open_kwargs) as resp:
            data = resp.read()
            results = self._parse_sse(data)
            if results:
                if results[0].get("error"):
                    raise RuntimeError(f"MCP error: {results[0]['error']}")
                return results[0].get("result", results[0])
            raise RuntimeError("MCP returned no response")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        with self._lock:
            if not self._session_id:
                self.initialize()
            try:
                return self._execute_call(name, arguments)
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    print(f"[jaeger-bridge] MCP session error ({err.code}), re-initializing session...")
                    self._session_id = None
                    try:
                        self.initialize()
                        return self._execute_call(name, arguments)
                    except Exception as retry_err:
                        print(f"[jaeger-bridge] MCP re-initialize failed: {retry_err}")
                        raise
                raise

    def chat(self, message: str, session_id: str | None = None) -> dict:
        """Run one chat turn on a fresh MCP session.

        A shared session plus a process-wide lock made Round 2 of a
        Roundtable drop with 'Remote end closed connection without response'
        whenever Round 1 (or another client) still held the MCP transport.
        """
        args = {"message": message}
        if session_id:
            args["session_id"] = session_id
        last_error: Exception | None = None
        self._circuit.check()
        for attempt in range(3):
            worker = MCPClient(self.base_url, self.api_key, self.host_header)
            try:
                worker.initialize()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not _is_transient_http(exc) or attempt == 2:
                    self._circuit.failure()
                    raise
                print(f"[jaeger-bridge] MCP handshake attempt {attempt + 1} failed ({exc}); retrying")
                time.sleep(0.4 * (attempt + 1))
                continue
            try:
                result = worker._execute_call("chat", args)
                self._circuit.success()
                return result
            except Exception as exc:
                if _is_transient_http(exc):
                    self._circuit.failure()
                # Once dispatched, a timeout/disconnect is ambiguous: no replay.
                raise
        raise last_error or RuntimeError("MCP chat failed")

    def agent_info(self) -> dict:
        return self.call_tool("agent_info", {})


# ── In-memory run store ────────────────────────────────────────────────────

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()

mcp_client = MCPClient(MCP_GATEWAY_URL, MCP_API_KEY, MCP_HOST_HEADER)
_native_runs = None
_native_lock = threading.Lock()

# Initialize on demand. A stopped MCP backend must not prevent the adapter
# from starting its HTTP listener or recovering when the backend returns.


# ── REST API Server ────────────────────────────────────────────────────────

class RunHandler(RunsHTTP, BaseHTTPRequestHandler):
    """Handles REST API that Hermes WebUI gateway mode expects."""

    protocol_version = "HTTP/1.1"

    def native_key(self):
        return profile_key("jaeger")

    def native_runs(self):
        global _native_runs
        with _native_lock:
            if _native_runs is None:
                root = Path(__file__).resolve().parents[3] / ".jaeger_ai/shared/webui-runs/jaeger"
                _native_runs = Runs(root, jaeger_turn, reconciler=jaeger_reconcile)
            return _native_runs

    def do_GET(self):
        if os.environ.get("JAEGERS_ADAPTER_NATIVE_RUNS", "true").lower() in {"1", "true"} and self.native_route("GET"):
            return
        if self.path in ("/health", "/v1/health", "/health/detailed"):
            self._send_json(200, {"ok": True, "status": "ready"})
        elif self.path == "/v1/capabilities":
            self._send_json(200, {
                "streaming": True,
                "models": [{"id": "jaeger", "name": "Jaeger Local", "provider": "jaeger"}],
                "approval": False,
            })
        elif re.match(r"^/v1/runs/([\w-]+)(?:/events)?$", self.path):
            run_id = re.match(r"^/v1/runs/([\w-]+)", self.path).group(1)
            self._handle_get_events(run_id)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if os.environ.get("JAEGERS_ADAPTER_NATIVE_RUNS", "true").lower() in {"1", "true"} and self.native_route("POST"):
            return
        if self.path == "/v1/runs":
            self._handle_create_run()
        elif self.path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif re.match(r"^/v1/runs/([\w-]+)/cancel$", self.path):
            run_id = self.path.split("/")[-2]
            with _runs_lock:
                if run_id in _runs:
                    _runs[run_id]["status"] = "cancelled"
            self._send_json(200, {"run_id": run_id, "status": "cancelled"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Hermes-Session-Id, X-Hermes-Session-Key")
        self.end_headers()

    def _handle_chat_completions(self):
        """OpenAI-compatible chat endpoint, honoring the requested stream mode."""
        headers_sent = False
        try:
            headers_sent = self._write_chat_completion()
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger-bridge] chat handler error: {exc}")
            if not headers_sent:
                try:
                    self._send_json(500, {"error": str(exc)})
                except Exception:  # noqa: BLE001
                    pass

    def _write_chat_completion(self) -> bool:
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}

        messages = body.get("messages", [])
        # Extract the last user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    user_msg = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                else:
                    user_msg = str(content)
                break

        session_id = self.headers.get("X-Hermes-Session-Id", "")

        wants_stream = body.get("stream") is True

        # MCP currently returns a completed response, so perform that bounded
        # request first and then encode it using the response contract selected
        # by the caller.  In particular, WebUI's non-stream gateway probe must
        # receive JSON rather than an unsolicited SSE body.
        result_holder = {"done": False, "text": "", "error": ""}

        def _run_chat():
            try:
                result = mcp_client.chat(user_msg, session_id or None)
                text = ""
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text += item.get("text", "")
                    elif isinstance(content, str):
                        text = content
                    if result.get("isError"):
                        result_holder["error"] = text or "MCP tool error"
                        result_holder["done"] = True
                        return
                else:
                    text = str(result)
                result_holder["text"] = text
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                result_holder["done"] = True

        thread = threading.Thread(target=_run_chat, daemon=True)
        thread.start()
        model_name = "jaeger"
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        if not wants_stream:
            thread.join(timeout=REQUEST_TIMEOUT)
            if not result_holder["done"]:
                result_holder["error"] = "Jaeger gateway request timed out"
            text = (
                f"Error: {result_holder['error']}"
                if result_holder["error"]
                else result_holder["text"]
            )
            self._send_json(200, {
                "id": chunk_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
            return True

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b": thinking\n\n")
            self.wfile.flush()

            deadline = (time.monotonic() + REQUEST_TIMEOUT) if REQUEST_TIMEOUT else None
            while not result_holder["done"]:
                thread.join(timeout=2.0)
                if not result_holder["done"]:
                    if deadline and time.monotonic() > deadline:
                        result_holder["error"] = "Jaeger gateway request timed out"
                        break
                    self.wfile.write(b": thinking\n\n")
                    self.wfile.flush()

            if result_holder["error"]:
                error_chunk = {
                    "id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()),
                    "model": model_name, "choices": [{"index": 0, "delta": {"content": f"Error: {result_holder['error']}"}, "finish_reason": None}]
                }
                self.wfile.write(f"data: {json.dumps(error_chunk)}\n\n".encode())
                self.wfile.flush()
            elif result_holder["done"]:
                text = result_holder["text"]
                chunk = {
                    "id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()),
                    "model": model_name, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()

            final = {
                "id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model_name, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return True
        return True

    def _handle_create_run(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}

        message = body.get("input") or body.get("message") or ""
        if isinstance(message, list):
            message = " ".join(
                p.get("content", "") if isinstance(p, dict) else str(p)
                for p in message
            )
        session_id = body.get("session_id") or ""

        run_id = uuid.uuid4().hex[:16]

        with _runs_lock:
            _runs[run_id] = {
                "id": run_id, "status": "running", "input": message,
                "session_id": session_id, "created_at": time.time(),
                "result": "", "error": "",
            }

        def _run_chat():
            try:
                result = mcp_client.chat(message, session_id or None)
                text = ""
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text += item.get("text", "")
                    elif isinstance(content, str):
                        text = content
                    if result.get("isError"):
                        with _runs_lock:
                            _runs[run_id]["status"] = "failed"
                            _runs[run_id]["error"] = text or "MCP tool error"
                        return
                else:
                    text = str(result)
                with _runs_lock:
                    _runs[run_id]["status"] = "completed"
                    _runs[run_id]["result"] = text
            except Exception as e:
                with _runs_lock:
                    _runs[run_id]["status"] = "failed"
                    _runs[run_id]["error"] = str(e)

        threading.Thread(target=_run_chat, daemon=True).start()
        self._send_json(200, {"run_id": run_id, "status": "running", "session_id": session_id})

    def _handle_get_events(self, run_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        while True:
            with _runs_lock:
                run = _runs.get(run_id)
                if not run:
                    self.wfile.write(b"data: {\"event\": \"error\", \"message\": \"run not found\"}\n\n")
                    break
                status = run["status"]
                result = run.get("result", "")
                error = run.get("error", "")

            if status == "completed":
                self.wfile.write(f"data: {json.dumps({'event': 'message.delta', 'delta': result})}\n\n".encode())
                self.wfile.write(f"data: {json.dumps({'event': 'run.completed', 'run_id': run_id})}\n\n".encode())
                break
            elif status == "failed":
                self.wfile.write(f"data: {json.dumps({'event': 'run.failed', 'error': error})}\n\n".encode())
                break
            elif status == "cancelled":
                self.wfile.write(f"data: {json.dumps({'event': 'run.cancelled'})}\n\n".encode())
                break
            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
            time.sleep(0.5)
        self.wfile.flush()

    def _send_json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        body = json.dumps(data).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[jaeger-bridge] {args[0]}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", ADAPTER_PORT), RunHandler)
    print(f"[jaeger-bridge] REST adapter listening on :{ADAPTER_PORT}")
    print(f"[jaeger-bridge] MCP gateway: {MCP_GATEWAY_URL}")
    print(f"[jaeger-bridge] Endpoints: /v1/runs, /v1/chat/completions, /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[jaeger-bridge] Shutting down")
        server.shutdown()
