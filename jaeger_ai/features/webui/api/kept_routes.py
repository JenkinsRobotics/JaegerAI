"""The WebUI's own ``/api/*`` surface: the only legacy routes still served.

The React UI (``jaeger_ai/interfaces/ui``) talks to the Gateway through the
``/v1/*`` proxy. The routes below are the remaining ``/api/*`` endpoints that
something in this repo actually calls; every other ``/api/*`` path (the
Hermes WebUI surface) answers ``410 Gone``. Measured 2026-11-11 from the UI
source, the in-repo callers and ``~/.jaeger/logs/legacy-api-hits.json``.

Callers:
* UI (``interfaces/ui/src``): terminal, runtime/models, providers, models,
  default-model, notes, jaeger/{voice/capability,tts,transcribe,gateway/health},
  handoffs, git, file, file/raw, list, connect-apps, checkpoints,
  remote/connection-info.
* Login page and ``features/remote_access/service.py``: auth/*.
* ``features/remote_access/service.py``: jaeger/sessions*.
* ``features/webui/service/service.py`` identity probe: settings.
* Health probes: health. Browser CSP reports: csp-report.
"""
from __future__ import annotations

EXACT: frozenset[str] = frozenset({
    "/api/runtime/models",
    "/api/providers",
    "/api/models",
    "/api/default-model",
    "/api/jaeger/voice/capability",
    "/api/jaeger/tts",
    "/api/jaeger/transcribe",
    "/api/jaeger/gateway/health",
    "/api/file",
    "/api/file/raw",
    "/api/list",
    "/api/remote/connection-info",
    "/api/settings",
    "/api/health",
    "/api/csp-report",
})

PREFIXES: tuple[str, ...] = (
    "/api/terminal/",
    "/api/notes/",
    "/api/handoffs",
    "/api/git/",
    "/api/connect-apps",
    "/api/checkpoints/",
    "/api/auth/",
    "/api/jaeger/sessions",
)


def is_kept(path: str) -> bool:
    """True when ``path`` is served; non-``/api/`` paths are always served."""
    path = (path or "").split("?", 1)[0]
    if not path.startswith("/api/"):
        return True
    path = path.rstrip("/") or path
    return path in EXACT or any(path.startswith(p) for p in PREFIXES)
