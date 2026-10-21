"""Loopback HTTP triggers — Hermes-style inbound routines.

A subscribed POST creates an approval-bound Gateway task proposal, never a turn.
GitHub event payloads are recognised when the path is ``/github`` or
the body looks like a GitHub webhook.

Bind is loopback-only. Optional shared secret via
``Authorization: Bearer …`` or ``X-Hub-Signature-256`` is accepted
when configured. Subscription admission additionally requires a configured secret;
empty-secret loopback requests cannot admit work. Existing credentials are untouched.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from jaeger_ai.contract.webhooks import FILTER_TOKEN_PATTERN, MAX_EVENT_BODY_BYTES, SUBSCRIPTION_ID_PATTERN

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8793


def _summarise_github(payload: dict[str, Any]) -> tuple[str, str]:
    repo = ""
    try:
        repo = str((payload.get("repository") or {}).get("full_name") or "")
    except Exception:  # noqa: BLE001
        repo = ""
    action = str(payload.get("action") or "")
    if "pull_request" in payload:
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or ""
        title = pr.get("title") or ""
        user = ((pr.get("user") or {}).get("login") or "")
        head = f"{repo} PR #{number}: {title} ({action} by {user})".strip()
        return head, (
            f"GitHub pull_request {action} on {repo} #{number}: {title}. "
            f"Author {user}. Review whether this needs a board card or a reply."
        )
    if "issue" in payload:
        issue = payload.get("issue") or {}
        number = issue.get("number") or ""
        title = issue.get("title") or ""
        return (
            f"{repo} issue #{number}: {title}",
            f"GitHub issue {action} on {repo} #{number}: {title}.",
        )
    if "commits" in payload or payload.get("ref"):
        after = str(payload.get("after") or payload.get("head_commit", {}).get("id") or "")[:12]
        return (
            f"{repo} push {after}".strip(),
            f"GitHub push on {repo} ref {payload.get('ref')}.",
        )
    return (f"{repo or 'GitHub'} event {action}".strip(),
            json.dumps(payload)[:800])


def interpret(path: str, body: dict[str, Any] | None, *, raw: str = "") -> dict[str, str]:
    """Turn an HTTP request into ``{action, title, prompt}``.

    ``action`` is ``board`` (default) or ``turn``.
    """
    payload = body if isinstance(body, dict) else {}
    action = str(payload.get("action") or "board").strip().lower()
    if action not in {"board", "turn"}:
        action = "board"
    title = str(payload.get("title") or payload.get("name") or "").strip()
    prompt = str(payload.get("prompt") or payload.get("text") or "").strip()
    githubish = (
        path.rstrip("/").endswith("/github")
        or "pull_request" in payload
        or "issue" in payload
        or payload.get("zen") is not None
        or "repository" in payload
    )
    if githubish and not (title and prompt):
        g_title, g_prompt = _summarise_github(payload)
        title = title or g_title
        prompt = prompt or g_prompt
    if not title:
        title = f"webhook {path}"
    if not prompt:
        prompt = raw[:800] if raw else title
    return {"action": action, "title": title, "prompt": prompt}


class _Handler(BaseHTTPRequestHandler):
    server_version = "JaegerWebhook/1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # HTTP paths, query strings and provider text can contain secrets.
        print("[jaeger-webhook] request completed", flush=True)

    def _unauthorized(self) -> None:
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":false,"error":"unauthorized"}')

    def _ok(self, payload: dict[str, Any]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path in {"/", "/health", "/hook", "/github"}:
            self._ok({"ok": True, "service": "jaeger-webhook"})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        secret = getattr(self.server, "webhook_secret", "") or ""
        try:
            length = int(self.headers.get('Content-Length') or '0')
            if not 0 <= length <= MAX_EVENT_BODY_BYTES:
                raise ValueError()
        except ValueError:
            self.send_error(413, 'Unsupported event size')
            return
        raw_bytes = self.rfile.read(length)
        auth = self.headers.get('Authorization') or ''
        bearer = auth[7:] if auth.lower().startswith('bearer ') else ''
        signature = self.headers.get('X-Hub-Signature-256') or ''
        authenticated = bool(secret) and (
            hmac.compare_digest(bearer.encode(), secret.encode())
            or hmac.compare_digest(signature.encode(), ('sha256=' + hmac.new(secret.encode(), raw_bytes, hashlib.sha256).hexdigest()).encode()))
        if secret and not authenticated:
            self._unauthorized()
            return
        try:
            body = json.loads(raw_bytes) if raw_bytes else {}
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self._ok({'ok': False, 'status': 'rejected', 'reason': 'invalid_json'})
            return
        path = urlparse(self.path).path
        match = re.fullmatch(rf'/(?:hook|github)/({SUBSCRIPTION_ID_PATTERN})', path)
        if not match or secret and secret in match[1]:
            self._ok({'ok': False, 'status': 'rejected', 'reason': 'subscription_required'})
            return
        def safe(value):
            # Redact every provider string we project, not just prompt/title.
            return str(value).replace(secret, '[redacted]') if secret else str(value)
        interpreted = interpret(path, body)
        provider = 'github' if self.headers.get('X-GitHub-Event') else 'generic'
        sender = body.get('sender')
        if isinstance(sender, dict):
            sender = sender.get('login')
        event = {'subscription_id': match[1], 'provider': provider,
                 'delivery_id': safe(self.headers.get('X-Jaeger-Delivery-Id') or self.headers.get('X-GitHub-Delivery') or body.get('delivery_id') or ''),
                 'event_type': safe(self.headers.get('X-GitHub-Event') or self.headers.get('X-Jaeger-Event') or ''),
                 'sender': safe(sender or ''), 'title': safe(interpreted['title']), 'prompt': safe(interpreted['prompt']),
                 'authenticated': authenticated}
        if any(re.fullmatch(FILTER_TOKEN_PATTERN, event[key]) is None for key in ('delivery_id', 'event_type', 'sender')):
            self._ok({'ok': False, 'status': 'rejected', 'reason': 'invalid_event_identity'})
            return
        callback = getattr(self.server, 'webhook_callback', None)
        try:
            result = callback(event) if callable(callback) else {'ok': False, 'status': 'unavailable'}
        except Exception:
            # The callback may have committed before response/publish failure.
            result = {'ok': False, 'status': 'admission_unknown', 'error': 'Inspect original subscription delivery; do not generate a new identity'}
        self._ok(result)


def serve(
    callback: Any,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    secret: str = "",
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, int(port)), _Handler)
    httpd.webhook_callback = callback  # type: ignore[attr-defined]
    httpd.webhook_secret = secret  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=httpd.serve_forever, name="jaeger-webhook", daemon=True,
    )
    thread.start()
    return httpd


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "interpret",
    "serve",
]
