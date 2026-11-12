"""In-app OAuth flow implementations for onboarding.

The browser receives only WebUI-local flow metadata (flow_id, user_code,
verification_uri, high-level status). Provider device/auth codes and OAuth
tokens stay server-side and are persisted to the active Hermes profile's
``auth.json`` credential_pool.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def auth_json_path() -> Path:
    from jaeger_ai.core.runtime.profile_paths import hermes_profile_root

    return hermes_profile_root() / "auth.json"
















def resolve_runtime_provider_with_anthropic_env_lock(resolver, *args, **kwargs):
    """Resolve runtime credentials under the Anthropic onboarding env lock.

    Request paths must resolve Anthropic env fallbacks per outbound request,
    not cache ANTHROPIC_TOKEN or ANTHROPIC_API_KEY across onboarding. Sharing
    the process-env lock prevents a chat stream from observing one stale
    Anthropic env value while onboarding has already cleared the other.
    """
    from api.streaming import _ENV_LOCK

    with _ENV_LOCK:
        return resolver(*args, **kwargs)




def _get_active_hermes_home() -> Path:
    """Return the active Hermes profile home directory, falling back to ~/.hermes when profile resolution fails."""
    try:
        from api.profiles import get_active_hermes_home

        return Path(get_active_hermes_home())
    except Exception as exc:
        # Per Opus advisor on stage-296: log the silent fallback so a corrupt
        # profile state ending up writing tokens to ~/.hermes (instead of the
        # active profile) is observable in logs rather than failing silently.
        logger.warning(
            "Falling back to ~/.hermes for OAuth credential storage: "
            "active-profile resolution failed: %s",
            exc,
        )
        from jaeger_ai.core.runtime.profile_paths import hermes_profile_root

        return hermes_profile_root()


# ── legacy auth.json helpers ────────────────────────────────────────────────

def _read_auth_json(auth_path: Path | None = None) -> dict[str, Any]:
    """Read auth.json and return parsed dict, or an empty compatible store."""
    path = auth_path or auth_json_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse %s: %s", path, exc)
            return {}
    return {}


def read_auth_json():
    """Public wrapper for streaming credential self-heal code."""
    return _read_auth_json()




def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string ending in Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")








# ── Anthropic / Claude Code credential linking ─────────────────────────────

















# ── Codex protocol ──────────────────────────────────────────────────────────

def _json_request(url: str, payload: dict[str, Any], *, form: bool = False) -> dict[str, Any]:
    """POST a JSON or form-encoded payload to url and return the parsed JSON response."""
    if form:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": content_type, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))




































