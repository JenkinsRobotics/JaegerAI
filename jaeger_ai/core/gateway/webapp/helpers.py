"""Response helpers for the web app handlers (replaces the Hermes helpers)."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

MAX_BODY_BYTES = 20 * 1024 * 1024
_REQUEST_BODY_CONSUMED_ATTR = "_jg_body_consumed"
_CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)

CSP = ("default-src 'self' https://*.cloudflareaccess.com; object-src 'none'; frame-ancestors 'none'; "
       "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://static.cloudflareinsights.com blob:; "
       "worker-src blob: 'self' https://cdn.jsdelivr.net; "
       "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
       "img-src 'self' data: https: blob:; font-src 'self' data: https://fonts.gstatic.com; media-src 'self' data: blob:; "
       "connect-src 'self' http://127.0.0.1:* http://localhost:* http://ipc.localhost https://127.0.0.1:* https://localhost:* "
       "ws://127.0.0.1:* ws://localhost:* https://cdn.jsdelivr.net; frame-src 'self' http://127.0.0.1:8797 http://127.0.0.1:8798; "
       "manifest-src 'self' https://*.cloudflareaccess.com; base-uri 'self'; form-action 'self'")


def _security_headers(handler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "same-origin")
    handler.send_header("Content-Security-Policy", CSP)
    handler.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)")


def flush_pending_auth_cookies(handler) -> None:
    for cookie in getattr(handler, "_pending_set_cookies", None) or []:
        handler.send_header("Set-Cookie", cookie)
    handler._pending_set_cookies = []


def j(handler, payload, status: int = 200, extra_headers: dict | None = None, *, pretty: bool = True) -> bool:
    body = json.dumps(payload, indent=2 if pretty else None, default=str, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    if "gzip" in (handler.headers.get("Accept-Encoding") or "") and len(body) > 1024:
        body = gzip.compress(body, compresslevel=4)
        handler.send_header("Content-Encoding", "gzip")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _security_headers(handler)
    flush_pending_auth_cookies(handler)
    for k, v in (extra_headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)
    handler._jg_responded = True
    return True


def bad(handler, msg, status: int = 400) -> bool:
    return j(handler, {"error": msg}, status=status)


def require(body: dict, *keys: str) -> None:
    missing = [k for k in keys if not (isinstance(body, dict) and body.get(k) not in (None, ""))]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")


def _sanitize_error(e: Exception) -> str:
    return re.sub(r'(?:(?:/[a-zA-Z0-9_.-]+)+|(?:[A-Z]:\\[^\s]+))', '<path>', str(e))


def _redact_text(text: str) -> str:
    try:
        from jaeger_ai.core.redaction import redact_text
        return redact_text(text)
    except Exception:  # noqa: BLE001
        return text


def safe_resolve(root: Path, requested: str) -> Path:
    resolved = (root / requested).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def mark_request_body_consumed(handler) -> None:
    setattr(handler, _REQUEST_BODY_CONSUMED_ATTR, True)


def reset_request_body_consumed(handler) -> None:
    setattr(handler, _REQUEST_BODY_CONSUMED_ATTR, False)
    handler._json_body_bytes = None


def consume_unread_request_body(handler, *, max_bytes: int | None = None) -> None:
    if getattr(handler, _REQUEST_BODY_CONSUMED_ATTR, False):
        return
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        handler.close_connection = True
        return
    if length > (max_bytes or MAX_BODY_BYTES):
        handler.close_connection = True
        return
    if length:
        handler.rfile.read(length)
    mark_request_body_consumed(handler)


def read_raw(handler) -> bytes:
    cached = getattr(handler, "_json_body_bytes", None)
    if cached is not None:
        return cached
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > MAX_BODY_BYTES:
        handler.close_connection = True
        raise ValueError(f"Request body too large ({length} bytes)")
    raw = handler.rfile.read(length) if length else b""
    mark_request_body_consumed(handler)
    handler._json_body_bytes = raw or b"{}"
    return handler._json_body_bytes


def read_body(handler) -> dict:
    raw = read_raw(handler)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc
    return data if isinstance(data, dict) else {}
