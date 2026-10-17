"""Notes and Joplin external sources API routes and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen

from .config import get_config
from .helpers import j, _redact_text
from .route_mcp import (
    _mcp_runtime_status_by_name,
    _mcp_safe_display_text,
    _mcp_tools_from_registry,
    _mcp_tools_from_runtime_status,
    _server_summary,
)


def _webui_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _external_notes_sources_enabled(config_data: dict | None = None) -> bool:
    """Return whether the third-party notes drawer is explicitly enabled.

    The Memory panel is a primary surface, so this power-user drawer stays
    default-off unless a deployment opts in through config or environment.
    """
    env_value = os.getenv("HERMES_WEBUI_EXTERNAL_NOTES_SOURCES", "")
    if env_value:
        return _webui_truthy(env_value)
    cfg = config_data if isinstance(config_data, dict) else get_config()
    if not isinstance(cfg, dict):
        return False
    return _webui_truthy(
        cfg.get("webui_external_notes_sources")
        or cfg.get("external_notes_sources")
        or cfg.get("notes_sources_drawer")
    )


_NOTES_SOURCE_SERVER_HINTS = {
    "joplin", "obsidian", "notion", "llm-wiki", "llmwiki", "wiki",
    "notes", "note", "knowledge", "kb", "readwise", "logseq",
}
_NOTES_SOURCE_TOOL_HINTS = {
    "note", "notes", "notebook", "page", "pages", "wiki", "knowledge",
    "search_notes", "get_note", "list_notes", "read_note",
}
_NOTES_SOURCE_CONFIGURED_TOOL_HINTS = {
    "joplin": [
        {"name": "search_notes", "description": "Search Joplin notes by keyword."},
        {"name": "list_notes", "description": "List notes from a Joplin notebook."},
        {"name": "get_note", "description": "Read a specific Joplin note by ID."},
    ],
    "obsidian": [
        {"name": "search_notes", "description": "Search Obsidian notes by keyword."},
        {"name": "read_note", "description": "Read a specific Obsidian note or file."},
    ],
    "notion": [
        {"name": "search_pages", "description": "Search Notion pages or databases."},
        {"name": "get_page", "description": "Read a specific Notion page."},
    ],
    "llm-wiki": [
        {"name": "query_knowledge_base", "description": "Query the LLM Wiki knowledge base."},
        {"name": "read_page", "description": "Read a specific wiki page."},
    ],
    "llmwiki": [
        {"name": "query_knowledge_base", "description": "Query the LLM Wiki knowledge base."},
        {"name": "read_page", "description": "Read a specific wiki page."},
    ],
}


def _note_source_label(name: str) -> str:
    labels = {
        "joplin": "Joplin",
        "obsidian": "Obsidian",
        "notion": "Notion",
        "llm-wiki": "LLM Wiki",
        "llmwiki": "LLM Wiki",
        "readwise": "Readwise",
        "logseq": "Logseq",
    }
    lowered = str(name or "").strip().lower()
    return labels.get(lowered, str(name or "").replace("_", " ").replace("-", " ").title())


def _looks_like_notes_source(server_name: str, tool_rows: list[dict]) -> bool:
    server_l = str(server_name or "").lower()
    if any(hint in server_l for hint in _NOTES_SOURCE_SERVER_HINTS):
        return True
    for tool in tool_rows:
        haystack = " ".join([
            str(tool.get("name") or ""),
            str(tool.get("description") or ""),
        ]).lower()
        if any(hint in haystack for hint in _NOTES_SOURCE_TOOL_HINTS):
            return True
    return False


def _configured_note_tool_hints(server_name: str) -> list[dict]:
    """Return safe expected note-tool hints for configured known sources."""
    server_l = str(server_name or "").strip().lower()
    hints = _NOTES_SOURCE_CONFIGURED_TOOL_HINTS.get(server_l)
    if hints is None:
        if any(hint in server_l for hint in ("wiki", "knowledge", "kb")):
            hints = [
                {"name": "search", "description": "Search this configured knowledge source."},
                {"name": "read", "description": "Read an item from this configured knowledge source."},
            ]
        elif any(hint in server_l for hint in ("note", "notes")):
            hints = [
                {"name": "search_notes", "description": "Search this configured notes source."},
                {"name": "read_note", "description": "Read a note from this configured notes source."},
            ]
        else:
            hints = []
    return [
        {
            "name": _mcp_safe_display_text(row.get("name") or "", limit=96),
            "description": _mcp_safe_display_text(row.get("description") or "", limit=180),
            "inferred": True,
        }
        for row in hints
        if isinstance(row, dict)
    ]


def _notes_sources_from_mcp_inventory(server_summaries: dict, tools: list[dict]) -> list[dict]:
    """Build a safe notes/knowledge-source inventory from MCP servers/tools.

    Some WebUI deployments can read ``mcp_servers`` from config before their
    local runtime/tool registry has hydrated MCP tool metadata. Still show
    configured note/knowledge servers (for example Joplin) in that case so the
    drawer reflects connection/configuration state instead of appearing empty.
    """
    by_server: dict[str, list[dict]] = {}
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        server = str(tool.get("server") or "").strip()
        if not server:
            continue
        by_server.setdefault(server, []).append(tool)

    if isinstance(server_summaries, dict):
        for server, summary in server_summaries.items():
            server_name = str(server or "").strip()
            if not server_name or server_name in by_server:
                continue
            if _looks_like_notes_source(server_name, []):
                by_server.setdefault(server_name, [])

    sources = []
    for server, tool_rows in by_server.items():
        if not _looks_like_notes_source(server, tool_rows):
            continue
        summary = server_summaries.get(server, {"name": server}) if isinstance(server_summaries, dict) else {"name": server}
        safe_tools = []
        tool_source = "runtime"
        for tool in tool_rows[:8]:
            desc = _mcp_safe_display_text(tool.get("description") or "", limit=180)
            desc = re.sub(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", "[REDACTED]", desc)
            safe_tools.append({
                "name": _mcp_safe_display_text(tool.get("name") or "", limit=96),
                "description": desc,
            })
        if not safe_tools:
            safe_tools = _configured_note_tool_hints(server)
            if safe_tools:
                tool_source = "configured_hint"
        sources.append({
            "name": server,
            "label": _note_source_label(server),
            "enabled": bool(summary.get("enabled", True)),
            "active": bool(summary.get("active")),
            "status": summary.get("status") or "unknown",
            "tool_count": len(safe_tools),
            "tool_source": tool_source,
            "tools": safe_tools,
        })
    sources.sort(key=lambda row: (not row.get("active"), row.get("label", "")))
    return sources


def _notes_configured_server(source: str) -> dict:
    cfg = get_config()
    servers = cfg.get("mcp_servers", {}) if isinstance(cfg, dict) else {}
    if not isinstance(servers, dict):
        return {}
    source_l = str(source or "").strip().lower()
    for name, server_cfg in servers.items():
        if str(name or "").strip().lower() == source_l and isinstance(server_cfg, dict):
            return server_cfg
    return {}


def _joplin_connection_from_config() -> tuple[str, str]:
    cfg = _notes_configured_server("joplin")
    env = cfg.get("env", {}) if isinstance(cfg, dict) else {}
    if not isinstance(env, dict):
        env = {}
    url = str(env.get("JOPLIN_URL") or os.environ.get("JOPLIN_URL") or "http://127.0.0.1:41184").rstrip("/")
    token = str(env.get("JOPLIN_TOKEN") or os.environ.get("JOPLIN_TOKEN") or "")
    return url, token


def _joplin_api_get(path: str, params: dict | None = None) -> dict:
    """Call the local Joplin Web Clipper API without logging credentials."""
    base_url, token = _joplin_connection_from_config()
    if not token:
        raise ValueError("Joplin token is not configured")
    safe_path = "/" + str(path or "").lstrip("/")
    query = dict(params or {})
    # Joplin Web Clipper builds can reject header-only auth on /search even when
    # they accept it elsewhere. Keep the Authorization header for defense in
    # depth and add the query token only for /search compatibility.
    if safe_path == "/search":
        query["token"] = token
    url = f"{base_url}{safe_path}?{urlencode(query)}"
    request = Request(url, headers={"Authorization": f"token {token}"})
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise ValueError(f"Joplin API returned HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        # A bare socket-connect TimeoutError from urlopen(timeout=8) is NOT
        # always URLError-wrapped, so catch it explicitly here. Otherwise it
        # propagates past handle_notes_search's `except ValueError` to the
        # request dispatch, where the consolidated client-disconnect handler
        # (#3210) would swallow it as a fake disconnect — silent empty response,
        # no log. Convert it to a normal "not reachable" ValueError instead.
        raise ValueError("Joplin API is not reachable") from None
    try:
        data = json.loads(raw)
    except Exception:
        raise ValueError("Joplin API returned invalid JSON") from None
    return data if isinstance(data, dict) else {}


def _note_snippet(body: str, query: str = "", *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    if not text:
        return ""
    q = str(query or "").strip().lower()
    if q:
        idx = text.lower().find(q)
        if idx > 40:
            text = "…" + text[max(0, idx - 60):]
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _joplin_search_notes(query: str, *, limit: int = 20) -> list[dict]:
    query = str(query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 20), 50))
    data = _joplin_api_get("/search", {
        "query": query,
        "type": "note",
        "fields": "id,title,body,parent_id,updated_time",
        "limit": limit,
    })
    rows = data.get("items") if isinstance(data, dict) else []
    results = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        note_id = _mcp_safe_display_text(row.get("id") or "", limit=64)
        if not note_id:
            continue
        title = _mcp_safe_display_text(row.get("title") or "Untitled", limit=180)
        body = str(row.get("body") or "")
        results.append({
            "id": note_id,
            "title": title,
            "snippet": _mcp_safe_display_text(_note_snippet(body, query), limit=260),
            "parent_id": _mcp_safe_display_text(row.get("parent_id") or "", limit=64),
            "updated_time": row.get("updated_time"),
            "source": "joplin",
        })
    return results


def _joplin_get_note(note_id: str) -> dict:
    note_id = str(note_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", note_id):
        raise ValueError("Invalid Joplin note id")
    data = _joplin_api_get(f"/notes/{note_id}", {
        "fields": "id,title,body,parent_id,updated_time,created_time",
    })
    if not data.get("id"):
        raise ValueError("Joplin note not found")
    body = str(data.get("body") or "")
    if len(body) > 50_000:
        body = body[:50_000].rstrip() + "\n\n[Preview truncated at 50,000 characters]"
    return {
        "id": _mcp_safe_display_text(data.get("id") or "", limit=64),
        "title": _mcp_safe_display_text(data.get("title") or "Untitled", limit=180),
        "body": _redact_text(body),
        "parent_id": _mcp_safe_display_text(data.get("parent_id") or "", limit=64),
        "updated_time": data.get("updated_time"),
        "created_time": data.get("created_time"),
        "source": "joplin",
    }


_JOPLIN_AI_RECALL_NOTE_PRIORITY = [
    ("CURRENT_CONTEXT_ID", "Current Context"),
    ("OPEN_ISSUES_ID", "Open Issues"),
    ("AGENT_MEMORY_ID", "Agent Memory"),
    ("CONVENTIONS_ID", "Conventions / Preferences"),
    ("INFRA_ID", "Infrastructure"),
    ("SERVICES_ID", "Services"),
]


def _script_path_from_config_value(path_value: Any) -> Path | None:
    """Return the likely recall script path from a string or argv-style hook."""
    if not path_value:
        return None
    try:
        if isinstance(path_value, (list, tuple)):
            candidates = [str(part).strip() for part in path_value if str(part).strip()]
        else:
            raw = str(path_value).strip()
            raw_path = Path(raw).expanduser()
            if raw and raw_path.exists():
                return raw_path
            candidates = shlex.split(raw)
        # Hooks commonly use either [python, /path/to/script.py] or the string
        # form "python /path/to/script.py". Prefer the first script-like argument
        # over the interpreter so AI-recent notes reflect the configured recall
        # source rather than "python3".
        for candidate in candidates:
            if candidate.endswith((".py", ".sh", ".bash")):
                return Path(candidate).expanduser()
        if candidates:
            return Path(candidates[-1]).expanduser()
        return None
    except Exception:
        return None


def _joplin_prefill_script_path() -> Path | None:
    cfg = get_config()
    if not isinstance(cfg, dict):
        return None
    # The browser notes drawer should mirror the WebUI-specific recall hook when
    # configured. Fall back to the legacy generic session prefill script only for
    # deployments that have not opted into WebUI dynamic recall.
    return _script_path_from_config_value(
        os.getenv("HERMES_WEBUI_PREFILL_MESSAGES_SCRIPT", "")
        or cfg.get("webui_prefill_messages_script")
        or cfg.get("prefill_messages_script")
    )


def _joplin_recall_note_refs(script_path: Path | None = None) -> list[dict]:
    """Find stable Joplin note IDs referenced by the configured recall script.

    This keeps the WebUI generic: it does not hard-code a user's note IDs, but
    can still surface the notes that the configured AI prefill/recall script is
    known to read for automatic context.
    """
    script_path = script_path or _joplin_prefill_script_path()
    if not script_path or not script_path.exists() or not script_path.is_file():
        return []
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    constants = {
        match.group(1): match.group(2)
        for match in re.finditer(r'(?m)^\s*([A-Z0-9_]+_ID)\s*=\s*["\']([A-Fa-f0-9]{16,64})["\']', text)
    }
    refs = []
    seen = set()
    for const_name, label in _JOPLIN_AI_RECALL_NOTE_PRIORITY:
        note_id = constants.get(const_name)
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        refs.append({
            "id": note_id,
            "label": label,
            "constant": const_name,
            "used_by": "ai_prefill",
            "used_reason": "automatic_recall",
        })
    return refs


def _joplin_recent_ai_notes(*, limit: int = 6) -> list[dict]:
    """Return safe Joplin notes that the configured AI recall path recently uses."""
    try:
        limit = max(1, min(int(limit or 6), 20))
    except Exception:
        limit = 6
    notes = []
    for ref in _joplin_recall_note_refs()[:limit]:
        try:
            data = _joplin_api_get(f"/notes/{ref['id']}", {
                "fields": "id,title,parent_id,updated_time,user_updated_time,created_time",
            })
        except Exception:
            continue
        note_id = _mcp_safe_display_text(data.get("id") or ref.get("id") or "", limit=64)
        if not note_id:
            continue
        notes.append({
            "id": note_id,
            "title": _mcp_safe_display_text(data.get("title") or ref.get("label") or "Untitled", limit=180),
            "label": _mcp_safe_display_text(ref.get("label") or "", limit=120),
            "parent_id": _mcp_safe_display_text(data.get("parent_id") or "", limit=64),
            "updated_time": data.get("user_updated_time") or data.get("updated_time"),
            "created_time": data.get("created_time"),
            "source": "joplin",
            "used_by": ref.get("used_by") or "ai_prefill",
            "used_reason": ref.get("used_reason") or "automatic_recall",
        })
    return notes


def handle_notes_sources_list(handler: Any) -> bool:
    """List note/knowledge MCP sources for the WebUI Notes drawer."""
    cfg = get_config()
    if not _external_notes_sources_enabled(cfg):
        return j(handler, {
            "enabled": False,
            "sources": [],
            "source": "disabled",
            "inventory_scope": "disabled_by_default",
            "attach_supported": False,
            "automatic_recall_unchanged": True,
            "recent_ai_notes": [],
        })
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    runtime = _mcp_runtime_status_by_name()
    server_summaries = {
        str(name): _server_summary(str(name), scfg, runtime.get(str(name)))
        for name, scfg in servers.items()
    }
    tools = _mcp_tools_from_runtime_status(runtime, server_summaries)
    source = "mcp_runtime_status"
    if not tools:
        tools = _mcp_tools_from_registry(server_summaries)
        source = "tool_registry" if tools else "none"
    return j(handler, {
        "enabled": True,
        "sources": _notes_sources_from_mcp_inventory(server_summaries, tools),
        "source": source,
        "inventory_scope": "already_known_runtime_only",
        "attach_supported": False,
        "automatic_recall_unchanged": True,
        "recent_ai_notes": _joplin_recent_ai_notes(limit=6),
    })


def handle_notes_search(handler: Any, parsed: Any) -> bool:
    if not _external_notes_sources_enabled():
        return j(handler, {"source": "disabled", "results": [], "error": "External notes sources are disabled."}, status=404)
    query = parse_qs(parsed.query or "")
    source = str(query.get("source", ["joplin"])[0] or "joplin").strip().lower()
    q = str(query.get("q", [""])[0] or "").strip()
    try:
        limit = int(query.get("limit", ["20"])[0] or 20)
    except Exception:
        limit = 20
    if source != "joplin":
        return j(handler, {"source": source, "results": [], "error": "Search is currently implemented for Joplin sources only."}, status=400)
    try:
        return j(handler, {"source": "joplin", "query": q, "results": _joplin_search_notes(q, limit=limit)})
    except ValueError as exc:
        return j(handler, {"source": "joplin", "query": q, "results": [], "error": str(exc)}, status=502)


def handle_notes_item(handler: Any, parsed: Any) -> bool:
    if not _external_notes_sources_enabled():
        return j(handler, {"source": "disabled", "error": "External notes sources are disabled."}, status=404)
    query = parse_qs(parsed.query or "")
    source = str(query.get("source", ["joplin"])[0] or "joplin").strip().lower()
    note_id = str(query.get("id", [""])[0] or "").strip()
    if source != "joplin":
        return j(handler, {"source": source, "error": "Preview is currently implemented for Joplin sources only."}, status=400)
    try:
        return j(handler, {"source": "joplin", "note": _joplin_get_note(note_id)})
    except ValueError as exc:
        return j(handler, {"source": "joplin", "error": str(exc)}, status=502)

