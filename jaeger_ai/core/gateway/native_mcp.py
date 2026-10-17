"""Gateway transport to Jaeger's native MCP HTTP server.

The Gateway's live native-chat, readiness-probe and cancel paths reach the
Jaeger agent through this minimal MCP JSON-RPC client. It used to live inside
the legacy Hermes-WebUI REST adapter (``core/frameworks/jaeger.py``); it is
owned by the Gateway now, and that adapter imports it from here.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from jaeger_ai.contract.ports import MCP_HTTP_URL
from jaeger_ai.core.frameworks.resilience import CircuitBreaker, timeout_setting


def mcp_api_key() -> str:
    """Credential for Jaeger's own MCP HTTP server (resolved per attempt).

    MCP HTTP accepts only the ``mcp`` and ``jaegerd`` caller tokens
    (``interfaces/mcp_server.MCP_INBOUND_CALLERS``); jaegerd presents its own
    so the relayed turn is attributed to jaegerd, not to an outside MCP agent.
    The legacy ARES host key in the Hermes profile is never a candidate: the
    server rejects it, which failed every native and specialist turn."""
    key = os.environ.get("JAEGERS_MCP_API_KEY", "").strip()
    if key:
        return key
    from jaeger_ai.core.gateway.caller_auth import client_token
    return client_token("jaegerd") or ""


MCP_URL = MCP_HTTP_URL
MCP_HOST_HEADER = os.environ.get("JAEGERS_MCP_HOST", "127.0.0.1:8792")
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
        return exc.code in {502, 503, 504}
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
            "Host": self.host_header,
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
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

    def list_tools(self) -> list[dict]:
        """Discover names without executing a possibly stateful chat request."""
        with self._lock:
            tools = []
            cursor = None
            seen = set()
            for _ in range(32):
                request_id = self._next_id()
                body = json.dumps({
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/list",
                    "params": {"cursor": cursor} if cursor else {},
                }).encode("utf-8")
                req = urllib.request.Request(self.base_url, data=body, headers=self._headers(), method="POST")
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    data = resp.read(1_048_577)
                if len(data) > 1_048_576:
                    raise RuntimeError("MCP catalog exceeds size limit")
                messages = self._parse_sse(data)
                reply = next((m for m in messages if m.get("id") == request_id), None)
                if reply is None or reply.get("error"):
                    raise RuntimeError("MCP tool discovery failed")
                result = reply.get("result", {})
                page = result.get("tools")
                if not isinstance(page, list) or not all(isinstance(t, dict) for t in page):
                    raise RuntimeError("Invalid MCP tool catalog")
                tools.extend(page)
                cursor = result.get("nextCursor")
                if not cursor:
                    return tools
                if not isinstance(cursor, str) or cursor in seen:
                    raise RuntimeError("Invalid MCP catalog cursor")
                seen.add(cursor)
            raise RuntimeError("MCP catalog exceeds page limit")

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


def current_mcp_client() -> MCPClient:
    """Build a client with the latest credential instead of import-time state."""
    return MCPClient(MCP_URL, mcp_api_key(), MCP_HOST_HEADER)
