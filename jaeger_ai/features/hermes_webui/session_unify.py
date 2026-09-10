"""Backup, classify, and import WebUI/Jaeger KEEP sessions onto :8790.

Does not merge agent transcripts into one SQLite. Copies KEEP rows from
Hermes ``state.db`` + the WebUI JSON catalog into the vendor HERMES_HOME
used by Jaeger WebUI, and tombstones junk in Jaeger ``sessions.db``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from jaeger_ai.features.hermes_webui.profile_layout import (
    PROFILE_DISPLAY_NAMES,
    ensure_agent_state_schema,
    profile_display_name,
)

NUDGE_PREFIX = "SYSTEM NUDGE:"
_JUNK_MARKERS = (
    "check word",
    "verification",
    "hold the",
    "reply exactly",
    "you are a member of a real group chat",
    "bounded checkword",
    "route_ok",
    "are you working",
    "canonical deployment facts supplied by the roundtable",
)
ALWAYS_KEEP = {
    "dispatcher",
    "960f4565",
    "b8349b0769d3",
    "b392eea6",
    "76c4ddbe5faa",
    "grants-edit-20260907",
}
ROLLBACK_MIN_KEEP = 6

# Profile / role badges for the single conversation library (Grok-Bot model).
# Origin/source remain surface tags (webui/tui/…); profile_badge is the role.
_PROFILE_BADGES = {
    "jaeger": PROFILE_DISPLAY_NAMES["jaeger"],
    "dispatcher": PROFILE_DISPLAY_NAMES["jaeger"],
    "hermes": PROFILE_DISPLAY_NAMES["default"],
    "default": PROFILE_DISPLAY_NAMES["default"],
    "roundtable": PROFILE_DISPLAY_NAMES["roundtable"],
    "openclaw": PROFILE_DISPLAY_NAMES["openclaw"],
    "ares": "ARES",
}
# Surface origins that must never become profile keys when falling back.
_SURFACE_ONLY = frozenset({
    "webui", "tui", "app", "cli", "acp",
    "telegram", "discord", "imessage", "slack", "weixin", "email", "matrix",
    "cron", "webhook", "mcp", "voice", "kanban", "worker", "completions",
    "probe", "deepthink", "claude", "codex", "grok", "gemini", "unknown",
})


def normalize_session_profile(value: object) -> str | None:
    """Return a durable profile key, or None if ``value`` is empty/not a profile."""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in ("jaeger", "dispatcher"):
        return "jaeger"
    if raw in ("default", "hermes", "hermes-agent", "hermes_agent"):
        return "hermes"
    if raw == "roundtable" or raw.startswith("roundtable-") or raw.startswith("roundtable:"):
        return "roundtable"
    if raw == "openclaw" or raw.startswith("openclaw-") or raw.startswith("openclaw:"):
        return "openclaw"
    if raw == "ares" or raw.startswith("ares-") or raw.startswith("ares:"):
        return "ares"
    if raw in _SURFACE_ONLY:
        return None
    # Profile-shaped slug (named Hermes profile folder).
    if raw.replace("-", "").replace("_", "").isalnum() and raw[0].isalpha():
        return raw
    return None


def infer_session_profile(
    session_id: str,
    explicit: object = None,
    *,
    origin: object = None,
    source: object = None,
) -> str:
    """Infer the durable profile key for a session (first-writer stamp input)."""
    if explicit not in (None, ""):
        key = normalize_session_profile(explicit)
        if key:
            return key
    sid = str(session_id or "").strip().lower()
    if sid in ("dispatcher", "jaeger"):
        return "jaeger"
    if sid in ("default", "hermes"):
        return "hermes"
    if sid == "roundtable" or sid.startswith("roundtable-") or sid.startswith("roundtable:"):
        return "roundtable"
    if sid == "openclaw" or sid.startswith("openclaw-") or sid.startswith("openclaw:"):
        return "openclaw"
    if sid.startswith("ares-") or sid.startswith("ares:"):
        return "ares"
    for candidate in (origin, source):
        key = normalize_session_profile(candidate)
        if key:
            return key
    return "jaeger"


def profile_badge_for_session(
    session_id: str = "",
    *,
    profile: object = None,
    origin: object = None,
    source: object = None,
) -> str:
    """Map session_id + profile/origin/source → display badge (not surface origin)."""
    key = normalize_session_profile(profile) if profile not in (None, "") else None
    if not key:
        key = infer_session_profile(session_id, origin=origin, source=source)
    if key in _PROFILE_BADGES:
        return _PROFILE_BADGES[key]
    # Named Hermes profile folder (or unknown slug): reuse display-name helper.
    if key in PROFILE_DISPLAY_NAMES:
        return PROFILE_DISPLAY_NAMES[key]
    return profile_display_name(key) if key else PROFILE_DISPLAY_NAMES["jaeger"]


def is_system_nudge(text: str) -> bool:
    return str(text or "").lstrip().startswith(NUDGE_PREFIX)


def is_conversational_stop(text: str) -> bool:
    blob = " ".join(str(text or "").lower().split())
    return any(
        token in blob
        for token in (
            "we are discussing",
            "just talk",
            "text discussion",
            "stop it yourself",
            "can you stop",
            "i just want to see",
        )
    ) or blob.strip() in {"stop", "stop.", "we are discussing stop"}


def title_from_text(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped and not is_system_nudge(stripped):
            return stripped[:80]
    return ""


def is_junk(*, session_id: str, title: str = "", preview: str = "", messages: int = 0) -> tuple[bool, str]:
    sid = str(session_id or "")
    if sid in ALWAYS_KEEP:
        return False, "always-keep"
    if sid.startswith("roundtable-hermes:") and messages >= 2:
        return False, "roundtable"
    if messages <= 0:
        return True, "empty"
    blob = f"{sid} {title} {preview}".lower()
    if "verification" in sid.lower() or sid.startswith("ares-"):
        return True, "verification-id"
    if any(marker in blob for marker in _JUNK_MARKERS):
        return True, "checkword"
    return False, "keep"


def freeze_sources(dest: Path, files: list[Path]) -> dict[str, Any]:
    """Copy existing files into dest. Never deletes sources."""
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing: list[str] = []
    for src in files:
        src = src.expanduser()
        if not src.exists():
            missing.append(str(src))
            continue
        target = dest / src.name
        if src.is_dir():
            shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
            wal, shm = Path(str(src) + "-wal"), Path(str(src) + "-shm")
            if wal.exists():
                shutil.copy2(wal, dest / wal.name)
            if shm.exists():
                shutil.copy2(shm, dest / shm.name)
        copied.append(str(src))
    (dest / "manifest.json").write_text(
        json.dumps({"copied": copied, "missing": missing, "ts": time.time()}, indent=2),
        encoding="utf-8",
    )
    return {"dest": str(dest), "copied": copied, "missing": missing}


def _session_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "id" not in cols:
            return []
        extra = []
        for name in ("title", "source", "started_at", "ended_at", "message_count"):
            extra.append(name if name in cols else f"NULL AS {name}")
        query = f"SELECT id, {', '.join(extra)} FROM sessions"
        rows = []
        for row in conn.execute(query):
            rows.append({k: row[k] for k in row.keys()})
        return rows
    finally:
        conn.close()


def _json_catalog(webui_sessions: Path) -> list[dict[str, Any]]:
    index = webui_sessions / "_index.json"
    if index.is_file():
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, dict):
            payload = payload.get("sessions") or payload.get("items") or []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
    rows = []
    if webui_sessions.is_dir():
        for path in webui_sessions.glob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data.setdefault("session_id", path.stem)
                rows.append(data)
    return rows


def reconcile_keep(
    *,
    hermes_state_db: Path,
    webui_sessions: Path,
    jaeger_sessions_db: Path | None = None,
) -> dict[str, Any]:
    """Union Hermes state.db + JSON catalog (+ optional Jaeger ids). JSON-only would drop roundtable."""
    state_rows = _session_rows(hermes_state_db)
    catalog = _json_catalog(webui_sessions)
    by_id: dict[str, dict[str, Any]] = {}
    for row in state_rows:
        sid = str(row.get("id") or "")
        if sid:
            by_id[sid] = {
                "id": sid,
                "title": row.get("title") or "",
                "preview": row.get("title") or "",
                "messages": int(row.get("message_count") or 0),
                "source": "state.db",
            }
    for row in catalog:
        sid = str(row.get("session_id") or row.get("id") or "")
        if not sid:
            continue
        existing = by_id.get(sid, {"id": sid, "title": "", "preview": "", "messages": 0, "source": "json"})
        existing["title"] = existing["title"] or str(row.get("title") or "")
        existing["preview"] = existing["preview"] or str(row.get("title") or row.get("preview") or "")
        existing["messages"] = max(int(existing["messages"] or 0), int(row.get("message_count") or row.get("user_message_count") or 0))
        existing["source"] = "both" if sid in {r.get("id") for r in state_rows} else "json"
        by_id[sid] = existing
    if jaeger_sessions_db and jaeger_sessions_db.exists():
        conn = sqlite3.connect(f"file:{jaeger_sessions_db}?mode=ro", uri=True)
        try:
            for sid, title, preview, n in conn.execute(
                "SELECT id, title, preview, "
                "(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) FROM sessions s"
            ):
                if sid not in by_id:
                    by_id[str(sid)] = {
                        "id": str(sid),
                        "title": title or "",
                        "preview": preview or "",
                        "messages": int(n or 0),
                        "source": "jaeger",
                    }
        finally:
            conn.close()
    keep, archive = [], []
    for item in by_id.values():
        junk, reason = is_junk(
            session_id=item["id"],
            title=item.get("title") or "",
            preview=item.get("preview") or "",
            messages=int(item.get("messages") or 0),
        )
        item["reason"] = reason
        item["profile_badge"] = profile_badge_for_session(item["id"])
        (archive if junk else keep).append(item)
    keep.sort(key=lambda row: (-int(row.get("messages") or 0), row["id"]))
    return {
        "keep": keep,
        "archive": archive,
        "state_only": sum(1 for row in state_rows if row["id"] not in {c.get("session_id") or c.get("id") for c in catalog}),
        "catalog_only": sum(1 for row in catalog if (row.get("session_id") or row.get("id")) not in {r["id"] for r in state_rows}),
        "rollback": len(keep) < ROLLBACK_MIN_KEEP,
    }


def _copy_table_rows(src: sqlite3.Connection, dest: sqlite3.Connection, table: str, where_sql: str, params: tuple[Any, ...]) -> int:
    src_cols = [row[1] for row in src.execute(f"PRAGMA table_info({table})")]
    dest_cols = [row[1] for row in dest.execute(f"PRAGMA table_info({table})")]
    shared = [c for c in src_cols if c in dest_cols]
    if not shared:
        return 0
    rows = src.execute(f"SELECT {', '.join(shared)} FROM {table} {where_sql}", params).fetchall()
    if not rows:
        return 0
    placeholders = ",".join("?" * len(shared))
    dest.executemany(
        f"INSERT OR IGNORE INTO {table} ({', '.join(shared)}) VALUES ({placeholders})",
        rows,
    )
    return len(rows)


def import_keep(
    *,
    hermes_state_db: Path,
    webui_sessions: Path,
    vendor_agent_home: Path,
    vendor_webui_state: Path,
    keep_ids: list[str],
) -> dict[str, Any]:
    """Copy KEEP transcripts into the :8790 vendor stores. Never deletes sources."""
    ensure_agent_state_schema(vendor_agent_home)
    dest_db = vendor_agent_home / "state.db"
    imported_sessions = 0
    imported_messages = 0
    if hermes_state_db.exists() and keep_ids:
        src = sqlite3.connect(f"file:{hermes_state_db}?mode=ro", uri=True)
        dest = sqlite3.connect(str(dest_db))
        try:
            dest.execute("BEGIN")
            src_tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            dest_tables = {row[0] for row in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            src_sess = {row[1]: row[2] for row in src.execute("PRAGMA table_info(sessions)")}
            dest_sess = {row[1]: row[2] for row in dest.execute("PRAGMA table_info(sessions)")}
            for col, typ in src_sess.items():
                if col not in dest_sess:
                    dest.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ or 'TEXT'}")
            if "messages" in src_tables and "messages" not in dest_tables:
                sql = src.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
                ).fetchone()
                if sql and sql[0]:
                    dest.execute(sql[0])
            qmarks = ",".join("?" * len(keep_ids))
            imported_sessions = _copy_table_rows(src, dest, "sessions", f"WHERE id IN ({qmarks})", tuple(keep_ids))
            if "messages" in src_tables:
                imported_messages = _copy_table_rows(
                    src, dest, "messages", f"WHERE session_id IN ({qmarks})", tuple(keep_ids)
                )
            dest.execute(
                "UPDATE sessions SET source=COALESCE(NULLIF(source,''), 'webui') "
                "WHERE source IS NULL OR source=''"
            )
            dest.commit()
        finally:
            src.close()
            dest.close()
    sidecar_dir = vendor_webui_state / "sessions"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    copied_json = 0
    index_rows = []
    for sid in keep_ids:
        src_json = webui_sessions / f"{sid}.json"
        if src_json.is_file():
            shutil.copy2(src_json, sidecar_dir / src_json.name)
            copied_json += 1
            try:
                index_rows.append(json.loads(src_json.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                index_rows.append({"session_id": sid})
        else:
            index_rows.append({"session_id": sid, "title": sid, "source_tag": "webui"})
    (sidecar_dir / "_index.json").write_text(json.dumps(index_rows, indent=2), encoding="utf-8")
    return {
        "sessions": imported_sessions,
        "messages": imported_messages,
        "json": copied_json,
        "keep": len(keep_ids),
        "vendor_state_db": str(dest_db),
        "rollback": len(keep_ids) < ROLLBACK_MIN_KEEP,
    }


def stamp_ended_at(state_db: Path, session_id: str, *, ended_at: float | None = None) -> bool:
    """Close a WebUI session after reconcile. Never invents cancellation of native work."""
    if not state_db.exists() or not session_id:
        return False
    conn = sqlite3.connect(str(state_db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "ended_at" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN ended_at REAL")
        conn.execute(
            "UPDATE sessions SET ended_at=COALESCE(ended_at, ?) WHERE id=?",
            (ended_at or time.time(), session_id),
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def close_reconciled_webui_session(session_id: str) -> None:
    home = Path.home()
    for path in (
        home / ".jaeger_ai" / "hermes-webui-agent" / "state.db",
        home / ".hermes" / "state.db",
    ):
        try:
            stamp_ended_at(path, session_id)
        except sqlite3.Error:
            continue


def backfill_jaeger_titles(store) -> int:
    updated = 0
    rows = store._conn.execute(
        "SELECT id, title, preview FROM sessions WHERE title IS NULL OR title=''"
    ).fetchall()
    for session_id, _title, preview in rows:
        title = title_from_text(preview or "")
        if not title:
            hist = store.history(session_id)
            for msg in hist:
                if msg.get("role") == "user":
                    title = title_from_text(msg.get("text") or "")
                    if title:
                        break
        if title and store.set_title(session_id, title):
            updated += 1
    return updated
