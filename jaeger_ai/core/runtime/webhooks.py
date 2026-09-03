"""Loopback HTTP triggers — Hermes-style inbound routines.

A POST on 127.0.0.1 drops a kanban card or fires a synthetic turn.
GitHub event payloads are recognised when the path is ``/github`` or
the body looks like a GitHub webhook.

Bind is loopback-only. Optional shared secret via
``Authorization: Bearer …`` or ``X-Hub-Signature-256`` is accepted
when configured; empty secret means loopback is enough.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

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
        print(f"[jaeger-webhook] {fmt % args}", flush=True)

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
        if secret:
            auth = self.headers.get("Authorization") or ""
            token = auth.split(" ", 1)[-1] if auth else ""
            hub = self.headers.get("X-Hub-Signature-256") or ""
            if token != secret and secret not in hub:
                self._unauthorized()
                return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(max(0, min(length, 1_000_000))).decode("utf-8", "replace")
        body: dict[str, Any] | None
        try:
            parsed = json.loads(raw) if raw.strip() else {}
            body = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            body = {"prompt": raw}
        interpreted = interpret(urlparse(self.path).path, body, raw=raw)
        callback = getattr(self.server, "webhook_callback", None)
        result: dict[str, Any] = {"ok": True, **interpreted}
        if callable(callback):
            try:
                extra = callback(interpreted) or {}
                if isinstance(extra, dict):
                    result.update(extra)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc), **interpreted}
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
