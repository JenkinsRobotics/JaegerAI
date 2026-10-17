"""Serving glue for the new UI build (jaeger_ai/interfaces/ui/dist).

``/`` and ``/index.html`` serve the new main screen and ``/assets/*`` its
hashed bundle (built with base ``./``). The old WebUI shell moves to
``/legacy`` and is only served when ``JAEGER_WEBUI_LEGACY=1``. Without a
build on disk, ``/`` keeps serving the old shell so nothing goes blank.
``JAEGER_WEBUI_UI_DIST`` overrides the build directory.
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
}


def dist_root() -> Path | None:
    root = Path(os.environ.get("JAEGER_WEBUI_UI_DIST") or _DIST_DEFAULT).expanduser()
    return root.resolve() if (root / "index.html").is_file() else None


def legacy_enabled() -> bool:
    return str(os.environ.get("JAEGER_WEBUI_LEGACY") or "").strip().lower() in {"1", "true", "yes", "on"}


def _send(handler, path: Path, cache: str) -> bool:
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", _MIME.get(path.suffix.lower(), "application/octet-stream"))
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)
    return True


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
        return _send(handler, root / "index.html", "no-cache")
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


__all__ = ["dist_root", "legacy_enabled", "serve"]
