"""Restricted path from the OpenClaw VM to loopback Ollama.

The daemon listens on 127.0.0.1 only. This proxy may also bind the VM
bridge address, on a different port. It never binds 0.0.0.0. It forwards
only model calls, and a non-loopback peer must present the MCP caller token.
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import request as urlrequest

from jaeger_ai.contract.ports import CONTAINER_HOST, LOOPBACK, OLLAMA_PORT

DAEMON_HOST = f"{LOOPBACK}:{OLLAMA_PORT}"
PROXY_PORT = 11435
_WILDCARDS = frozenset({"0.0.0.0", "::", ""})
_LOOPBACKS = frozenset({LOOPBACK, "localhost", "::1"})
ALLOWED_PATHS = frozenset({
    "/api/chat",
    "/api/generate",
    "/api/tags",
    "/api/embeddings",
    "/api/embed",
    "/v1/chat/completions",
    "/v1/embeddings",
    "/v1/models",
})


def daemon_listen() -> str:
    return DAEMON_HOST


def proxy_bind_hosts(bridge_host: str | None = None) -> tuple[str, ...]:
    hosts = [LOOPBACK]
    bridge = (bridge_host if bridge_host is not None else CONTAINER_HOST).strip()
    if bridge not in _WILDCARDS and bridge != LOOPBACK:
        hosts.append(bridge)
    return tuple(hosts)


def bridge_request_allowed(*, method: str, path: str, peer_host: str) -> bool:
    if method.upper() not in {"GET", "POST"}:
        return False
    clean = path.split("?", 1)[0]
    if len(clean) > 1:
        clean = clean.rstrip("/")
    if clean not in {item.rstrip("/") for item in ALLOWED_PATHS}:
        return False
    if peer_host in _LOOPBACKS:
        return True
    bridge = CONTAINER_HOST.strip()
    if not bridge or bridge in _WILDCARDS:
        return False
    prefix = bridge.rsplit(".", 1)[0] + "."
    return peer_host == bridge or peer_host.startswith(prefix)


def bridge_authorized(peer_host: str, authorization: str | None) -> bool:
    """Loopback is the host itself. The VM must present the MCP caller token."""
    if peer_host in _LOOPBACKS:
        return True
    presented = _bearer(authorization)
    expected = _mcp_token()
    if not presented or not expected:
        return False
    return hmac.compare_digest(
        hashlib.sha256(presented.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def _bearer(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _mcp_token() -> str | None:
    try:
        from jaeger_ai.core.gateway.caller_auth import client_token
        return client_token("mcp")
    except Exception:
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _proxy(self) -> None:
        peer = self.client_address[0]
        if not bridge_request_allowed(method=self.command, path=self.path, peer_host=peer):
            self._send(403, b'{"error":"model path refused"}')
            return
        if not bridge_authorized(peer, self.headers.get("Authorization")):
            self._send(401, b'{"error":"model bridge token required"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        forwarded = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "authorization", "content-length", "connection"}
        }
        req = urlrequest.Request(
            f"http://{DAEMON_HOST}{self.path}",
            data=body,
            headers=forwarded,
            method=self.command,
        )
        try:
            with urlrequest.urlopen(req, timeout=120) as resp:
                payload = resp.read()
                content_type = resp.headers.get("Content-Type", "application/json")
                status = resp.status
        except urlerror.HTTPError as exc:
            payload = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            status = exc.code
        except (OSError, urlerror.URLError):
            self._send(502, b'{"error":"ollama unavailable"}')
            return
        self._send(status, payload, content_type=content_type)

    def _send(self, status: int, payload: bytes, *, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(bridge_host: str | None = None) -> int:
    """Bind the proxy. Returns 0 when loopback is listening."""
    bound = 0
    for host in proxy_bind_hosts(bridge_host):
        try:
            httpd = ThreadingHTTPServer((host, PROXY_PORT), _Handler)
        except OSError as exc:
            print(f"[ollama-bridge] {host}:{PROXY_PORT} not bound ({exc})", file=sys.stderr)
            continue
        threading.Thread(target=httpd.serve_forever, name=f"ollama-bridge-{host}", daemon=True).start()
        print(f"[ollama-bridge] {host}:{PROXY_PORT} -> {DAEMON_HOST}", flush=True)
        bound += 1
    if bound == 0:
        return 1
    threading.Event().wait()
    return 0


def main(argv: list[str] | None = None) -> int:
    del argv
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
