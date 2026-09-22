"""Read-only external notes services used by the Notes drawer."""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


try:
    from jaeger_ai.features.webui.api.config import get_config
except Exception:
    def get_config(): return {}

try:
    from jaeger_ai.features.webui.api.mcp_config import list_servers
except Exception:
    def list_servers(): return []

try:
    from jaeger_ai.features.webui.api.helpers import _redact_text
except Exception:
    def _redact_text(text): return text


class NotesStoreError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled(config: dict | None = None) -> bool:
    environment = os.getenv("ARES_WEBUI_EXTERNAL_NOTES_SOURCES", "")
    if environment:
        return _truthy(environment)
    config = config if isinstance(config, dict) else get_config()
    return _truthy(
        config.get("webui_external_notes_sources")
        or config.get("external_notes_sources")
        or config.get("notes_sources_drawer")
    )


def _safe_text(value, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def list_sources() -> dict:

    config = get_config()
    if not enabled(config):
        return {
            "enabled": False,
            "sources": [],
            "source": "disabled",
            "inventory_scope": "disabled_by_default",
            "attach_supported": False,
            "automatic_recall_unchanged": True,
            "recent_ai_notes": [],
        }
    hints = ("joplin", "obsidian", "notion", "wiki", "notes", "knowledge", "readwise", "logseq")
    sources = []
    for server in list_servers().get("servers", []):
        name = str(server.get("name") or "")
        if not any(hint in name.lower() for hint in hints):
            continue
        sources.append(
            {
                "name": name,
                "label": name.replace("_", " ").replace("-", " ").title(),
                "enabled": bool(server.get("enabled", True)),
                "active": bool(server.get("active")),
                "status": server.get("status") or "unknown",
                "tool_count": 0,
                "tool_source": "configured_hint",
                "tools": [],
            }
        )
    sources.sort(key=lambda row: (not row["active"], row["label"]))
    return {
        "enabled": True,
        "sources": sources,
        "source": "configured_mcp_servers",
        "inventory_scope": "already_known_runtime_only",
        "attach_supported": False,
        "automatic_recall_unchanged": True,
        "recent_ai_notes": [],
    }


def _joplin_connection() -> tuple[str, str]:

    servers = get_config().get("mcp_servers", {})
    joplin = next(
        (
            value
            for name, value in servers.items()
            if str(name).strip().lower() == "joplin" and isinstance(value, dict)
        ),
        {},
    ) if isinstance(servers, dict) else {}
    environment = joplin.get("env", {}) if isinstance(joplin, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    base_url = str(
        environment.get("JOPLIN_URL")
        or os.environ.get("JOPLIN_URL")
        or "http://127.0.0.1:41184"
    ).rstrip("/")
    token = str(environment.get("JOPLIN_TOKEN") or os.environ.get("JOPLIN_TOKEN") or "")
    return base_url, token


def _joplin_get(path: str, params: dict | None = None) -> dict:
    base_url, token = _joplin_connection()
    if not token:
        raise NotesStoreError("Joplin token is not configured", 502)
    safe_path = "/" + str(path or "").lstrip("/")
    query = dict(params or {})
    if safe_path == "/search":
        query["token"] = token
    request = Request(
        f"{base_url}{safe_path}?{urlencode(query)}",
        headers={"Authorization": f"token {token}"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise NotesStoreError(f"Joplin API returned HTTP {exc.code}", 502) from None
    except (URLError, TimeoutError):
        raise NotesStoreError("Joplin API is not reachable", 502) from None
    try:
        data = json.loads(raw)
    except Exception:
        raise NotesStoreError("Joplin API returned invalid JSON", 502) from None
    return data if isinstance(data, dict) else {}


def search_notes(query: str, source: str = "joplin", limit: int = 20) -> dict:
    if not enabled():
        raise NotesStoreError("External notes sources are disabled.", 404)
    source = str(source or "joplin").strip().lower()
    if source != "joplin":
        raise NotesStoreError("Search is currently implemented for Joplin sources only.")
    query = str(query or "").strip()
    if not query:
        return {"source": "joplin", "query": query, "results": []}
    data = _joplin_get(
        "/search",
        {
            "query": query,
            "type": "note",
            "fields": "id,title,body,parent_id,updated_time",
            "limit": max(1, min(int(limit or 20), 50)),
        },
    )
    results = []
    for row in data.get("items", []) if isinstance(data.get("items"), list) else []:
        if not isinstance(row, dict):
            continue
        note_id = _safe_text(row.get("id"), 64)
        if not note_id:
            continue
        body = re.sub(r"\s+", " ", str(row.get("body") or "")).strip()
        results.append(
            {
                "id": note_id,
                "title": _safe_text(row.get("title") or "Untitled", 180),
                "snippet": _safe_text(body, 260),
                "parent_id": _safe_text(row.get("parent_id"), 64),
                "updated_time": row.get("updated_time"),
                "source": "joplin",
            }
        )
    return {"source": "joplin", "query": query, "results": results}


def get_note(note_id: str, source: str = "joplin") -> dict:

    if not enabled():
        raise NotesStoreError("External notes sources are disabled.", 404)
    source = str(source or "joplin").strip().lower()
    if source != "joplin":
        raise NotesStoreError("Preview is currently implemented for Joplin sources only.")
    note_id = str(note_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", note_id):
        raise NotesStoreError("Invalid Joplin note id", 502)
    data = _joplin_get(
        f"/notes/{note_id}",
        {"fields": "id,title,body,parent_id,updated_time,created_time"},
    )
    if not data.get("id"):
        raise NotesStoreError("Joplin note not found", 502)
    body = str(data.get("body") or "")
    if len(body) > 50_000:
        body = body[:50_000].rstrip() + "\n\n[Preview truncated at 50,000 characters]"
    return {
        "source": "joplin",
        "note": {
            "id": _safe_text(data.get("id"), 64),
            "title": _safe_text(data.get("title") or "Untitled", 180),
            "body": _redact_text(body),
            "parent_id": _safe_text(data.get("parent_id"), 64),
            "updated_time": data.get("updated_time"),
            "created_time": data.get("created_time"),
            "source": "joplin",
        },
    }
