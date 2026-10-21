"""Serve only the canonical shared UI. A missing build never selects an old frontend."""
from __future__ import annotations

import os
from pathlib import Path

_DIST_DEFAULT = Path.home() / ".cache/jaeger/ui-rebuild-mainscreen/dist"
_MIME = {
    ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".json": "application/json", ".woff2": "font/woff2", ".ico": "image/x-icon",
    ".map": "application/json", ".webp": "image/webp",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}
_NO_STORE = "no-cache, no-store"
_STATIC_DEFAULT = Path(__file__).resolve().parents[1] / "static"

#: Replaces the old shell's worker. It deletes every cache, unregisters itself
#: and reloads open windows so they fetch the new UI from the network.
KILL_SWITCH_SW = b"""/* Jaeger: retire the old WebUI service worker (new UI build active). */
self.addEventListener('install', () => { self.skipWaiting(); });
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try { const keys = await caches.keys(); await Promise.all(keys.map((k) => caches.delete(k))); } catch (e) {}
    try { await self.clients.claim(); } catch (e) {}
    try { await self.registration.unregister(); } catch (e) {}
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    await Promise.all(wins.map((c) => (c.navigate ? c.navigate(c.url) : null)).filter(Boolean)).catch(() => {});
  })());
});
self.addEventListener('fetch', () => {});
"""


def dist_root() -> Path | None:
    root = Path(os.environ.get("JAEGER_WEBUI_UI_DIST") or _DIST_DEFAULT).expanduser()
    return root.resolve() if (root / "index.html").is_file() else None


def _send(handler, path: Path, cache: str, ctype: str | None = None) -> bool:
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype or _MIME.get(path.suffix.lower(), "application/octet-stream"))
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _session_csrf_token(handler) -> str | None:
    """The CSRF token for this browser's verified session cookie, else None."""
    try:
        from api.auth import csrf_token_for_session, is_auth_enabled, parse_cookie, verify_session
    except Exception:  # noqa: BLE001 — no auth module: nothing to hand out
        return None
    if not is_auth_enabled():
        return None
    cookie = parse_cookie(handler)
    if not cookie or not verify_session(cookie):
        return None
    return csrf_token_for_session(cookie)


def _send_index(handler, index: Path) -> bool:
    """index.html, carrying the session CSRF token as a meta tag (no inline
    script, so CSP is unchanged). The UI echoes it in ``X-Hermes-CSRF-Token``
    on unsafe requests, which ``routes._check_csrf`` requires for cookie auth."""
    import html as _html

    token = _session_csrf_token(handler)
    if not token:
        return _send(handler, index, _NO_STORE)
    body = index.read_bytes()
    meta = f'<meta name="jaeger-csrf" content="{_html.escape(token, quote=True)}">'.encode()
    lower = body.lower()
    at = lower.find(b"<head>")
    body = body[: at + 6] + meta + body[at + 6:] if at >= 0 else meta + body
    handler.send_response(200)
    handler.send_header("Content-Type", _MIME[".html"])
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", _NO_STORE)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _send_kill_switch(handler) -> bool:
    body = KILL_SWITCH_SW
    handler.send_response(200)
    handler.send_header("Content-Type", "text/javascript; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", _NO_STORE)
    handler.send_header("Service-Worker-Allowed", "/")
    # Browsers honour Clear-Site-Data only on secure origins (the Tailscale
    # https front door); on plain http://127.0.0.1 it is ignored. Either way it
    # only clears HTTP/CacheStorage caches, never cookies or storage.
    handler.send_header("Clear-Site-Data", '"cache"')
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _serve_static_manifest(handler, path: str) -> bool:
    root = dist_root()
    if root is None or path not in ("/static/manifest.json", "/static/manifest.webmanifest"):
        return _not_found(handler)
    manifest = root / "manifest.webmanifest"
    if not manifest.is_file():
        return _not_found(handler)
    return _send(handler, manifest, "no-cache", "application/manifest+json; charset=utf-8")


def _root_file(root: Path, path: str) -> Path | None:
    """A regular file directly in the build root, or None. One path segment,
    no dotfiles, no HTML (index.html is only ever served as ``/``)."""
    name = path[1:]
    if not name or "/" in name or "\\" in name or name.startswith(".") or name.lower().endswith((".html", ".htm")):
        return None
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        return None
    index = root / "index.html"
    if index.is_file() and target.samefile(index):
        return None
    return target


def _not_found(handler) -> bool:
    body = b'{"error": "not found"}'
    handler.send_response(404)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def serve(handler, parsed) -> bool:
    """True means handled; False leaves backend API routing unchanged."""
    path = parsed.path or "/"
    if path == "/legacy" or path.startswith("/legacy/"):
        return _not_found(handler)
    root = dist_root()
    if root is None:
        if path in ("/", "/index.html") or path.startswith("/session/"):
            body = b'{"error":"Canonical shared UI build missing. Build interfaces/ui and set JAEGER_WEBUI_UI_DIST."}'
            handler.send_response(503)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", _NO_STORE)
            handler.end_headers()
            handler.wfile.write(body)
            return True
        return False
    if path in ("/", "/index.html") or (path.startswith("/session/") and path.count("/") == 2):
        return _send_index(handler, root / "index.html")
    if path in ("/sw.js", "/static/sw.js"):
        return _send_kill_switch(handler)
    if path == "/static/manifest.json" or (path.startswith("/static/") and path.endswith(".webmanifest")):
        return _serve_static_manifest(handler, path)
    if path.startswith("/assets/"):
        target = (root / path.lstrip("/")).resolve()
        try:
            target.relative_to(root / "assets")
        except ValueError:
            return _not_found(handler)
        if not target.is_file():
            return _not_found(handler)
        return _send(handler, target, "public, max-age=31536000, immutable")
    if path == "/manifest.json" and (root / "manifest.webmanifest").is_file():
        return _send(handler, root / "manifest.webmanifest", "no-cache")
    target = _root_file(root, path)
    if target is not None:
        return _send(handler, target, "no-cache")
    return False


__all__ = ["KILL_SWITCH_SW", "dist_root", "serve"]
