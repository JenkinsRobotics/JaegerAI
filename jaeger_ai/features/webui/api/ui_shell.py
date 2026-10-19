"""Serving glue for the new UI build (jaeger_ai/interfaces/ui/dist).

``/`` and ``/index.html`` serve the new main screen and ``/assets/*`` its
hashed bundle (built with base ``./``). The old WebUI shell moves to
``/legacy`` and is only served when ``JAEGER_WEBUI_LEGACY=1``. Without a
build on disk, ``/`` keeps serving the old shell so nothing goes blank.
``JAEGER_WEBUI_UI_DIST`` overrides the build directory.

While a build is active, ``/sw.js`` and ``/static/sw.js`` answer a kill-switch
worker so browsers (iOS home-screen installs especially) drop the old shell's
service worker and its caches, and the PWA manifest under ``/static/`` keeps
its ``application/manifest+json`` type. Without a build nothing here changes.
"""
from __future__ import annotations

import os
from pathlib import Path

_DIST_DEFAULT = Path(__file__).resolve().parents[3] / "interfaces" / "ui" / "dist"
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


def legacy_enabled() -> bool:
    return str(os.environ.get("JAEGER_WEBUI_LEGACY") or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _static_root() -> Path:
    try:
        from api import config as api_config  # the WebUI's own static root
        return Path(api_config.get_static_root()).resolve()
    except Exception:  # noqa: BLE001 — standalone import (tests) uses the package copy
        return _STATIC_DEFAULT.resolve()


def _serve_static_manifest(handler, path: str) -> bool:
    root = _static_root()
    target = (root / path[len("/static/"):]).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _not_found(handler)
    if not target.is_file():
        return _not_found(handler)
    return _send(handler, target, "no-cache", "application/manifest+json; charset=utf-8")


def _not_found(handler) -> bool:
    body = b'{"error": "not found"}'
    handler.send_response(404)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def serve(handler, parsed) -> bool | str:
    """True = handled; "legacy" = caller renders the old shell; False = not ours."""
    path = parsed.path or "/"
    if path == "/legacy" or path.startswith("/legacy/"):
        return "legacy" if legacy_enabled() else _not_found(handler)
    root = dist_root()
    if root is None:
        return False
    if path in ("/", "/index.html"):
        return _send(handler, root / "index.html", _NO_STORE)
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
    return False


__all__ = ["KILL_SWITCH_SW", "dist_root", "legacy_enabled", "serve"]
