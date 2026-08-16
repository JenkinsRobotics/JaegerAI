"""Session search, browse, and inspection tool for Jaeger AI.

Provides feature parity with Hermes Agent's session_search tool, enabling
the agent to discover, count, search, and read conversations across both
ARES WebUI and local CLI / native session stores.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ares_session_dir() -> Path | None:
    """Locate the active ARES WebUI sessions directory."""
    env_dir = os.environ.get("ARES_SESSION_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        if p.exists() and p.is_dir():
            return p

    ares_home = os.environ.get("ARES_HOME", "").strip()
    if ares_home:
        p = Path(ares_home).expanduser() / "webui" / "sessions"
        if p.exists() and p.is_dir():
            return p

    default_p = Path.home() / ".ares" / "webui" / "sessions"
    if default_p.exists() and default_p.is_dir():
        return default_p

    return None


def _format_ts(ts: float | int | str | None) -> str:
    if ts is None:
        return "unknown"
    try:
        val = float(ts)
        # Handle milliseconds timestamp
        if val > 1e11:
            val /= 1000.0
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(val))
    except Exception:
        return str(ts)


def _load_ares_sessions_api() -> list[dict[str, Any]]:
    """Query the live ARES controller API for sessions if running."""
    import urllib.request

    env_port = os.environ.get("ARES_CONTROLLER_PORT", "").strip() or os.environ.get("ARES_PORT", "").strip()
    if env_port.lower() in {"none", "disabled", "off", "0"}:
        return []

    ports = []
    if env_port and env_port.isdigit():
        ports.append(int(env_port))
    else:
        for p in (8788, 8787):
            ports.append(p)

    for port in ports:
        url = f"http://127.0.0.1:{port}/api/sessions"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    if isinstance(payload, dict) and "sessions" in payload:
                        return payload["sessions"]
                    if isinstance(payload, list):
                        return payload
        except Exception:
            continue
    return []


def _load_ares_sessions_index() -> list[dict[str, Any]]:
    """Load session metadata index from ARES API or disk."""
    api_sessions = _load_ares_sessions_api()
    if api_sessions:
        return api_sessions

    sdir = _ares_session_dir()
    if not sdir:
        return []
    index_file = sdir / "_index.json"
    if not index_file.exists():
        return []
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
    except Exception as exc:
        logger.debug("Failed reading ARES _index.json: %s", exc)
    return []


def _load_native_jaeger_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """Load native Jaeger sessions from SQLite store if bound."""
    try:
        from jaeger_ai.core.sessions import get_store
        store = get_store()
        if store is not None:
            raw = store.list_sessions(limit=limit)
            results = []
            for r in raw:
                results.append({
                    "session_id": r.get("id"),
                    "title": r.get("title") or r.get("preview") or "Untitled",
                    "created_at": r.get("created_at"),
                    "last_active": r.get("last_active"),
                    "message_count": r.get("messages", 0),
                    "source_tag": "cli",
                    "is_cli_session": True,
                    "source_label": "Jaeger Native",
                })
            return results
    except Exception as exc:
        logger.debug("Failed reading native jaeger sessions: %s", exc)
    return []


def _classify_source(session: dict[str, Any]) -> str:
    """Classify a session as 'webui' or 'cli'."""
    is_cli = session.get("is_cli_session") is True
    raw_source = str(
        session.get("source_tag")
        or session.get("raw_source")
        or session.get("session_source")
        or session.get("source_label")
        or ("cli" if is_cli else "webui")
    ).strip().lower()

    if is_cli or raw_source in {"cli", "tui", "acp", "claude_code", "claude code", "external_agent"}:
        return "cli"
    return "webui"


def _read_ares_session_transcript(session_id: str) -> dict[str, Any] | None:
    """Read full transcript for an ARES session."""
    sdir = _ares_session_dir()
    if not sdir:
        return None

    target = sdir / f"{session_id}.json"
    if not target.exists():
        # Check if session_id has .json already
        target = sdir / session_id
    if not target.exists():
        return None

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)

        messages = []
        raw_msgs = (
            data.get("context_messages")
            or data.get("messages")
            or []
        )

        for m in raw_msgs:
            if isinstance(m, dict):
                role = m.get("role") or m.get("sender") or "unknown"
                text = m.get("content") or m.get("text") or ""
                ts = m.get("timestamp") or m.get("ts")
                messages.append({
                    "role": role,
                    "content": text,
                    "timestamp": _format_ts(ts),
                })

        return {
            "session_id": session_id,
            "title": data.get("title") or "Untitled",
            "source": _classify_source(data),
            "created_at": _format_ts(data.get("created_at")),
            "updated_at": _format_ts(data.get("updated_at")),
            "message_count": len(messages),
            "model": data.get("model"),
            "messages": messages,
        }
    except Exception as exc:
        logger.debug("Failed reading session file %s: %s", target, exc)
        return None


def _read_native_session_transcript(session_id: str) -> dict[str, Any] | None:
    """Read transcript from native Jaeger SQLite store."""
    try:
        from jaeger_ai.core.sessions import get_store
        store = get_store()
        if store is None:
            return None
        history = store.history(session_id)
        if not history:
            return None
        brain = store.brain(session_id)
        messages = [
            {
                "role": h.get("role"),
                "content": h.get("text"),
                "timestamp": _format_ts(h.get("ts")),
            }
            for h in history
        ]
        return {
            "session_id": session_id,
            "title": session_id,
            "source": "cli",
            "model": brain.get("model"),
            "message_count": len(messages),
            "messages": messages,
        }
    except Exception as exc:
        logger.debug("Failed reading native session %s: %s", session_id, exc)
        return None


def session_search(
    query: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search, browse, or read conversations across WebUI and CLI sessions.

    Calling modes:
      1. BROWSE (no query, no session_id):
         Lists recent sessions, broken down into WebUI and CLI counts,
         with titles, timestamps, and message counts.
      2. SEARCH (query provided):
         Searches titles and message text across past conversations.
      3. READ (session_id provided):
         Loads the full transcript history of a specific session.

    Args:
        query: Search string to match in conversation transcripts or titles.
        session_id: Specific session identifier to read transcript from.
        source: Filter by source type ('webui' or 'cli').
        limit: Maximum number of sessions to return in browse/search modes (default 50).

    Returns:
        A dictionary containing session counts, matching session list, or full transcript.
    """
    # ── MODE 3: READ SPECIFIC SESSION ──────────────────────────────────────
    if session_id and session_id.strip():
        sid = session_id.strip()
        # Try ARES sidecar first
        res = _read_ares_session_transcript(sid)
        if res is not None:
            return {"ok": True, "mode": "read", "session": res}
        # Try native Jaeger store
        res = _read_native_session_transcript(sid)
        if res is not None:
            return {"ok": True, "mode": "read", "session": res}
        return {
            "ok": False,
            "mode": "read",
            "error": f"Session '{sid}' not found in ARES or native session stores.",
        }

    # Gather sessions from both sources
    ares_sessions = _load_ares_sessions_index()
    native_sessions = _load_native_jaeger_sessions(limit=limit)

    # Merge by session_id
    seen_ids = set()
    combined: list[dict[str, Any]] = []

    for s in ares_sessions:
        sid = s.get("session_id") or ""
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        src = _classify_source(s)
        combined.append({
            "session_id": sid,
            "title": (s.get("title") or "Untitled").strip(),
            "source": src,
            "created_at": _format_ts(s.get("created_at")),
            "last_active": _format_ts(s.get("last_message_at") or s.get("updated_at") or s.get("created_at")),
            "timestamp_raw": float(s.get("last_message_at") or s.get("updated_at") or s.get("created_at") or 0),
            "message_count": int(s.get("message_count") or 0),
            "pinned": bool(s.get("pinned")),
            "archived": bool(s.get("archived")),
        })

    for s in native_sessions:
        sid = s.get("session_id") or ""
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        src = _classify_source(s)
        combined.append({
            "session_id": sid,
            "title": (s.get("title") or "Untitled").strip(),
            "source": src,
            "created_at": _format_ts(s.get("created_at")),
            "last_active": _format_ts(s.get("last_active") or s.get("created_at")),
            "timestamp_raw": float(s.get("last_active") or s.get("created_at") or 0),
            "message_count": int(s.get("message_count") or 0),
            "pinned": False,
            "archived": False,
        })

    # Sort newest first
    combined.sort(key=lambda x: x.get("timestamp_raw", 0), reverse=True)

    # Compute source breakdown
    webui_count = sum(1 for s in combined if s["source"] == "webui")
    cli_count = sum(1 for s in combined if s["source"] == "cli")
    total_count = len(combined)

    # Filter by source if requested
    if source and source.strip():
        req_source = source.strip().lower()
        filtered = [s for s in combined if s["source"] == req_source]
    else:
        filtered = combined

    # ── MODE 2: SEARCH QUERY ───────────────────────────────────────────────
    if query and query.strip():
        q = query.strip().lower()
        matches = []
        for s in filtered:
            # Check title
            title_match = q in s["title"].lower()
            snippet = None
            if not title_match:
                # Search transcript file
                transcript = _read_ares_session_transcript(s["session_id"])
                if transcript:
                    for m in transcript.get("messages", []):
                        content = str(m.get("content") or "")
                        if q in content.lower():
                            snippet = content[:150]
                            break
            if title_match or snippet is not None:
                match_entry = dict(s)
                if snippet:
                    match_entry["matched_snippet"] = snippet
                matches.append(match_entry)
                if len(matches) >= limit:
                    break

        return {
            "ok": True,
            "mode": "search",
            "query": query,
            "total_matches": len(matches),
            "summary": f"Found {len(matches)} session(s) matching '{query}'.",
            "sessions": matches[:limit],
        }

    # ── MODE 1: BROWSE ALL ────────────────────────────────────────────────
    summary = (
        f"Found {total_count} total sessions: {webui_count} WebUI sessions, "
        f"{cli_count} CLI sessions."
    )

    clean_sessions = [
        {
            "session_id": s["session_id"],
            "title": s["title"],
            "source": s["source"],
            "created_at": s["created_at"],
            "last_active": s["last_active"],
            "message_count": s["message_count"],
        }
        for s in filtered[:limit]
    ]

    return {
        "ok": True,
        "mode": "browse",
        "total_sessions": total_count,
        "webui_sessions_count": webui_count,
        "cli_sessions_count": cli_count,
        "summary": summary,
        "sessions": clean_sessions,
    }
