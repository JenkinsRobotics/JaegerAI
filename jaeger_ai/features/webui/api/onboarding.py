"""Hermes Web UI -- first-run onboarding helpers."""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from api.auth import is_auth_enabled
from api.config import (DEFAULT_MODEL, DEFAULT_WORKSPACE, _FALLBACK_MODELS, _HERMES_FOUND, _PROVIDER_DISPLAY, _PROVIDER_MODELS, _get_config_path, get_available_models, get_config, load_settings, reload_config, save_settings, verify_hermes_imports)
from api.paths import _atomic_write_text
from api.providers import _write_env_file  # shared impl with _ENV_LOCK (#1164)
from api.workspace import get_last_workspace, load_workspaces

logger = logging.getLogger(__name__)








def _load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values











# ── Provider endpoint probe (#1499) ─────────────────────────────────────────




class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow HTTP redirects on the probe path.

    `urllib.request.urlopen` follows redirects by default — without this
    handler, a probe at `http://example.com/v1/models` could be redirected
    to `http://internal-service:8080/admin`, surfacing internal HTTP services
    to whatever the probe targets next.  The probe is already gated behind
    WebUI auth and the local-network check, so the threat model is
    "authenticated user enumerating internal services" — same as `curl`
    from their browser DevTools.  Disabling redirects tightens defaults
    without breaking any legitimate use case (a self-hosted /models endpoint
    that 3xx-redirects is itself misconfigured).  Redirects surface to the
    caller as `unreachable` (mapped from `HTTPError(3xx)` in the probe).
    Reviewer-flagged in PR #1501 (#1499 + #1500).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # tell urllib to NOT follow; raises HTTPError(3xx) instead




































