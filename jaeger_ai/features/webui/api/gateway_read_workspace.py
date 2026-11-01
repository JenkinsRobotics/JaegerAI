"""Resolve Gateway-owned workspaces for read-only legacy WebUI routes."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def gateway_read_workspace(session_id: str) -> Path:
    """Return a live, profile-visible Gateway session workspace or raise KeyError."""
    from .jaeger_agents import gateway_base
    from .profiles import _profiles_match, get_active_profile_name
    from .workspace import resolve_trusted_workspace
    from jaeger_ai.core.gateway.caller_auth import client_headers

    if not session_id:
        raise KeyError(session_id)
    request = Request(
        f"{gateway_base()}/v1/sessions/{quote(session_id, safe='')}",
        headers={"Accept": "application/json", **client_headers("webui")},
    )
    try:
        with urlopen(request, timeout=5) as response:
            row = json.load(response)
    except Exception as exc:
        raise KeyError(session_id) from exc
    if (not isinstance(row, dict) or row.get("session_id") != session_id
            or not _profiles_match(row.get("profile"), get_active_profile_name())
            or not row.get("workspace")):
        raise KeyError(session_id)
    try:
        return resolve_trusted_workspace(row["workspace"])
    except (ValueError, OSError) as exc:
        raise KeyError(session_id) from exc
