#!/usr/bin/env python3
"""Jaeger MCP-to-REST adapter for Hermes WebUI gateway mode.

Translates Hermes WebUI REST API calls into MCP tool calls to the Jaeger
agent gateway, so the WebUI can chat with Jaeger through gateway profiles.

Supports both /v1/chat/completions (SSE streaming) and /v1/runs APIs.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler
from .ingress import ProfileHTTPServer
from typing import Any
import urllib.request
import urllib.error
from pathlib import Path
from .native_runs import Runs, RunsHTTP, jaeger_reconcile, jaeger_turn, profile_key

# ── Config ──────────────────────────────────────────────────────────────────

from jaeger_ai.core.gateway.native_mcp import (  # transport owned by the Gateway
    MCP_HOST_HEADER,
    MCP_URL,
    REQUEST_TIMEOUT,
    MCPClient,
    _is_transient_http,
    mcp_api_key,
)

ADAPTER_PORT = int(os.environ.get("JAEGERS_ADAPTER_PORT", "8642"))
ADAPTER_HOST = os.environ.get("JAEGERS_ADAPTER_HOST", "127.0.0.1")


# ── In-memory run store ────────────────────────────────────────────────────

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()

def current_mcp_client() -> MCPClient:
    """Build a client with the latest credential instead of import-time state."""
    return MCPClient(MCP_URL, mcp_api_key(), MCP_HOST_HEADER)
_native_runs = None
_native_lock = threading.Lock()


def dispatcher_turn(run, workspace=None):
    from jaeger_ai.features.dispatcher.store import DispatcherStore
    from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
    store = DispatcherStore(jaeger_bridge().layout)
    store.repair_projections()
    run.native_session = store.route(run.session, run.message)
    return jaeger_turn(run, workspace)

# Initialize on demand. A stopped MCP backend must not prevent the adapter
# from starting its HTTP listener or recovering when the backend returns.


# ── REST API Server ────────────────────────────────────────────────────────

class RunHandler(RunsHTTP, BaseHTTPRequestHandler):
    """Handles REST API that Hermes WebUI gateway mode expects."""

    protocol_version = "HTTP/1.1"

    def native_key(self):
        return profile_key("jaeger")

    def create_native_run(self, body):
        from jaeger_ai.features.dispatcher.store import DispatcherStore
        from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
        binding = DispatcherStore(jaeger_bridge().layout).overview()['dispatcher_session']
        if binding and (body.get('session_id') or self.headers.get('X-Hermes-Session-Id')) == binding:
            body = {**body, 'session_id': 'dispatcher'}
        return super().create_native_run(body)

    def native_capabilities(self):
        value = super().native_capabilities()
        value['features'].update(model_override=True, workspace_override=True,
                                 structured_input=True, dispatcher=True, focus_sessions=True,
                                 memory_read=True, skill_inventory=True)
        return value

    def native_route(self, method):
        from urllib.parse import urlsplit
        path = urlsplit(self.path).path
        if path.startswith('/v1/dispatcher/conversation'):
            if not self.profile_authorized():
                return True
            from .conversation import Conversation
            from jaeger_ai.features.dispatcher.store import DispatcherStore
            from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
            try:
                bridge = jaeger_bridge()
                conversation = Conversation(DispatcherStore(bridge.layout), self.native_runs(),
                    lambda: bridge.query('dispatcher_conversation', timeout_s=10))
                action = path.removeprefix('/v1/dispatcher/conversation').strip('/')
                if method == 'GET' and not action:
                    result = conversation.snapshot()
                elif method == 'POST' and action in {'bind', 'send', 'cancel', 'approval', 'reconcile'}:
                    body = self.read_json_body()
                    if action == 'bind':
                        result = {'session_id': conversation.store.bind_dispatcher(body.get('session_id'))}
                    else:
                        result = conversation.start(body) if action == 'send' else conversation.control(action, body)
                else:
                    raise KeyError('Route not found')
                self.native_json(200, result)
            except (KeyError, ValueError, RuntimeError, OSError) as exc:
                self.native_json(404 if isinstance(exc, KeyError) else 400 if isinstance(exc, ValueError)
                                 else 409 if isinstance(exc, RuntimeError) else 503, {'error': str(exc)})
            return True
        queries = {'/v1/dispatcher/skills': 'list_skills',
                   '/v1/dispatcher/memory': 'dispatcher_memory',
                   '/v1/dispatcher/models': 'model_picker'}
        if path != '/v1/dispatcher' and path != '/v1/dispatcher/bind' and path not in queries:
            return super().native_route(method)
        if not self.profile_authorized():
            return True
        from jaeger_ai.features.dispatcher.store import DispatcherStore
        from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
        try:
            bridge = jaeger_bridge()
            store = DispatcherStore(bridge.layout)
            if method == 'GET' and path in queries:
                result = bridge.query(queries[path], timeout_s=10)
            elif method == 'GET' and path == '/v1/dispatcher':
                result = store.overview()
            elif method == 'POST' and path == '/v1/dispatcher/bind':
                result = {'session_id': store.bind_dispatcher(self.read_json_body().get('session_id'))}
            else:
                self.native_json(405, {'error': 'Method not supported'})
                return True
            self.native_json(200, result)
        except ValueError as exc:
            self.native_json(400, {'error': str(exc)})
        except (OSError, RuntimeError) as exc:
            self.native_json(503, {'error': str(exc)})
        return True

    def native_runs(self):
        global _native_runs
        with _native_lock:
            if _native_runs is None:
                from jaeger_ai.contract.frameworks import backend_protocol
                from jaeger_ai.core.instance.instance import operator_state_root
                root = operator_state_root() / "shared/webui-runs/jaeger"
                protocol = backend_protocol("jaeger")
                _native_runs = Runs(
                    root, protocol.turn, reconciler=protocol.reconciler)
            return _native_runs

    def do_GET(self):
        if os.environ.get("JAEGERS_ADAPTER_NATIVE_RUNS", "true").lower() in {"1", "true"} and self.native_route("GET"):
            return
        if self.path in ("/health", "/v1/health", "/health/detailed"):
            # Health no longer triggers a session mirror: the WebUI catalog is
            # a read-only projection of the Gateway's store, and a health probe
            # must never write session truth anywhere.
            self._send_json(200, {"ok": True, "status": "ready"})
        elif self.path == "/v1/capabilities":
            self._send_json(200, {
                "streaming": True,
                "models": [{"id": "jaeger", "name": "Jaeger Local", "provider": "jaeger"}],
                "approval": False,
            })
        elif re.match(r"^/v1/runs/([\w-]+)(?:/events)?$", self.path):
            if not self.profile_authorized():
                return
            run_id = re.match(r"^/v1/runs/([\w-]+)", self.path).group(1)
            self._handle_get_events(run_id)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if os.environ.get("JAEGERS_ADAPTER_NATIVE_RUNS", "true").lower() in {"1", "true"} and self.native_route("POST"):
            return
        if not self.legacy_post_authorized():
            return
        if self.path == "/v1/runs":
            self._handle_create_run()
        elif self.path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif re.match(r"^/v1/runs/([\w-]+)/(?:cancel|stop)$", self.path):
            run_id = self.path.split("/")[-2]
            with _runs_lock:
                exists = run_id in _runs
            self._send_json(501 if exists else 404, {
                'error': 'Legacy Jaeger cannot confirm native cancellation; work may still be running.' if exists else 'Run not found',
                'error_category': 'unsupported_control' if exists else 'not_found'})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.native_json(403, {'error': 'Use the authenticated WebUI server proxy'})

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
        body = getattr(self, '_request_body', None)
        if body is None:  # Direct internal callers; HTTP ingress already parsed.
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
                result = current_mcp_client().chat(user_msg, session_id or None)
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
        body = self._request_body

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
                result = current_mcp_client().chat(message, session_id or None)
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
        body = json.dumps(data).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[jaeger-bridge] {args[0]}")


if __name__ == "__main__":
    server = ProfileHTTPServer((ADAPTER_HOST, ADAPTER_PORT), RunHandler)
    print(f"[jaeger-bridge] REST adapter listening on {ADAPTER_HOST}:{ADAPTER_PORT}")
    print(f"[jaeger-bridge] Native MCP: {MCP_URL}")
    print(f"[jaeger-bridge] Endpoints: /v1/runs, /v1/chat/completions, /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[jaeger-bridge] Shutting down")
        server.shutdown()
