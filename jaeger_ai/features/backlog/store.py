"""Backlog store: one SQLite file (``~/.jaeger/backlog.sqlite3``), the source of truth.

Tasks: id, title, detail, source, status (open/in_progress/needs_ok/done),
priority (P0/P1/P2), worker (ares/muse/rackpc/grokbot/any named caller),
handoff id + thread (hub handoff made by ``assign``), timestamps.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from jaeger_ai.core.sqlite_connection import ClosingConnection

STATUSES = ("open", "in_progress", "needs_ok", "done")
PRIORITIES = ("P0", "P1", "P2")
WORKERS = ("ares", "muse", "rackpc", "grokbot", "hermes", "openclaw")
WORKER_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
FIELDS = ("title", "detail", "source", "status", "priority", "worker")
MAX = {"title": 300, "detail": 8000, "source": 300}


class BacklogError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def default_path() -> Path:
    raw = os.environ.get("JAEGER_BACKLOG_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        from jaeger_ai.core.instance.instance import operator_state_root
        return operator_state_root() / "backlog.sqlite3"
    except Exception:  # noqa: BLE001
        return Path.home() / ".jaeger" / "backlog.sqlite3"


def _clean(field: str, value):
    if field in MAX:
        if not isinstance(value, str):
            raise BacklogError(f"{field} must be text")
        value = value.strip()
        if field == "title" and not value:
            raise BacklogError("title is required")
        if len(value) > MAX[field]:
            raise BacklogError(f"{field} too long (max {MAX[field]})")
        return value
    if field == "status":
        if value not in STATUSES:
            raise BacklogError(f"status must be one of {', '.join(STATUSES)}")
        return value
    if field == "priority":
        value = str(value).upper()
        if value not in PRIORITIES:
            raise BacklogError(f"priority must be one of {', '.join(PRIORITIES)}")
        return value
    if field == "worker":
        if value in (None, ""):
            return ""
        value = str(value).strip().lower()
        if not WORKER_RE.match(value):
            raise BacklogError("worker must be a caller name like ares, muse, rackpc or grokbot")
        return value
    raise BacklogError(f"unknown field {field}")


class BacklogStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS backlog_tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
                    priority TEXT NOT NULL DEFAULT 'P1', worker TEXT NOT NULL DEFAULT '',
                    handoff_id TEXT, handoff_thread TEXT, import_key TEXT UNIQUE,
                    last_note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS backlog_handoff ON backlog_tasks(handoff_id);
                CREATE INDEX IF NOT EXISTS backlog_thread ON backlog_tasks(handoff_thread);
            """)
            columns = {row[1] for row in c.execute("PRAGMA table_info(backlog_tasks)")}
            if "handoff_result" not in columns:
                c.execute("ALTER TABLE backlog_tasks ADD COLUMN handoff_result TEXT")

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(r) -> dict:
        return dict(r) if r else None

    def get(self, task_id: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM backlog_tasks WHERE id=?", (str(task_id),)).fetchone()
        if not row:
            raise BacklogError("task not found", 404)
        return self._row(row)

    def list(self, status: str = "", priority: str = "", worker: str = "", q: str = "", limit: int = 500) -> list[dict]:
        sql, args = "SELECT * FROM backlog_tasks WHERE 1=1", []
        for col, val in (("status", status), ("priority", priority.upper() if priority else ""), ("worker", worker)):
            if val:
                vals = [v for v in str(val).split(",") if v]
                sql += f" AND {col} IN ({','.join('?' * len(vals))})"
                args += vals
        if q:
            sql += " AND (title LIKE ? OR detail LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        sql += (" ORDER BY CASE status WHEN 'needs_ok' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'open' THEN 2 ELSE 3 END,"
                " priority, updated_at DESC LIMIT ?")
        args.append(max(1, min(int(limit), 2000)))
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def add(self, title: str, detail: str = "", source: str = "", status: str = "open", priority: str = "P1",
            worker: str = "", import_key: str | None = None) -> dict:
        data = {"title": title, "detail": detail or "", "source": source or "", "status": status or "open",
                "priority": priority or "P1", "worker": worker or ""}
        data = {k: _clean(k, v) for k, v in data.items()}
        now = time.time()
        tid = "bl-" + uuid.uuid4().hex[:10]
        with self._lock, self._conn() as c:
            if import_key:
                hit = c.execute("SELECT id FROM backlog_tasks WHERE import_key=?", (import_key,)).fetchone()
                if hit:
                    return {**self._row(c.execute("SELECT * FROM backlog_tasks WHERE id=?", (hit[0],)).fetchone()), "existing": True}
            c.execute("INSERT INTO backlog_tasks(id,title,detail,source,status,priority,worker,import_key,created_at,updated_at)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (tid, data["title"], data["detail"], data["source"], data["status"], data["priority"],
                       data["worker"], import_key, now, now))
        return self.get(tid)

    def update(self, task_id: str, **changes) -> dict:
        extra = {k: changes.pop(k) for k in ("handoff_id", "handoff_thread", "last_note", "handoff_result") if k in changes}
        bad = set(changes) - set(FIELDS)
        if bad:
            raise BacklogError(f"unknown field(s): {', '.join(sorted(bad))}")
        clean = {k: _clean(k, v) for k, v in changes.items()}
        clean.update({k: (str(v)[:500] if v is not None else None) for k, v in extra.items()})
        self.get(task_id)
        if clean:
            clean["updated_at"] = time.time()
            cols = ", ".join(f"{k}=?" for k in clean)
            with self._lock, self._conn() as c:
                c.execute(f"UPDATE backlog_tasks SET {cols} WHERE id=?", (*clean.values(), task_id))
        return self.get(task_id)

    def by_handoff(self, handoff_id: str | None = None, thread: str | None = None) -> dict | None:
        with self._conn() as c:
            row = None
            if handoff_id:
                row = c.execute("SELECT * FROM backlog_tasks WHERE handoff_id=?", (handoff_id,)).fetchone()
            if row is None and thread:
                row = c.execute("SELECT * FROM backlog_tasks WHERE handoff_thread=?", (thread,)).fetchone()
        return self._row(row)

    def counts(self) -> dict:
        with self._conn() as c:
            return {r[0]: r[1] for r in c.execute("SELECT status, count(*) FROM backlog_tasks GROUP BY status")}


def status_from_message(kind: str, status_line: str = "") -> str | None:
    """Map a worker's hub reply onto a backlog status."""
    s = (status_line or "").lower()
    if kind == "status":
        return "needs_ok" if any(w in s for w in ("needs ok", "needs_ok", "approval", "blocked")) else "in_progress"
    if kind in ("result", "answer"):
        if s in ("timeout", "cancelled", "execution_unknown"):
            return "needs_ok"
        if any(w in s for w in ("fail", "error", "blocked", "needs ok", "needs_ok", "approval", "partial")):
            return "needs_ok"
        return "needs_ok" if s.startswith("needs") else "done"
    if kind == "question":
        return "needs_ok"
    return None


def sweep(store: BacklogStore, now: float, stale_after_s: float) -> list[dict]:
    """Return actionable flags without changing backlog state or reading live hub state."""
    if stale_after_s <= 0:
        raise ValueError("stale_after_s must be positive")
    with store._conn() as c:
        rows = [dict(row) for row in c.execute("SELECT * FROM backlog_tasks ORDER BY updated_at, id")]
    flagged = []
    for row in rows:
        reasons = []
        if row["status"] == "in_progress" and now - row["updated_at"] > stale_after_s:
            reasons.append("stale")
        words = " ".join(str(row.get(k) or "") for k in ("title", "detail", "last_note")).lower()
        if row["status"] == "needs_ok" or "needs matthew" in words or "waiting on matthew" in words:
            if row["status"] != "done":
                reasons.append("waiting_on_matthew")
        if row["status"] != "done" and ("blocked" in words or "blocker" in words):
            reasons.append("blocked")
        if row["status"] != "done" and row.get("handoff_result") in ("done", "failed", "cancelled", "denied"):
            reasons.append("finished_not_marked")
        if reasons:
            flagged.append({"task": row, "reasons": reasons})
    return flagged


def record_hub_message(store: BacklogStore, sender: str, message: dict) -> dict | None:
    """Idempotently mirror a peer hub handoff and its replies into backlog."""
    kind = message.get("kind")
    if kind == "task":
        refs = message.get("refs") or []
        linked = next((ref[8:] for ref in refs if isinstance(ref, str) and ref.startswith("backlog:")), None)
        task = None
        if linked:
            try:
                task = store.get(linked)
            except BacklogError:
                pass
        task = task or store.by_handoff(message.get("id"), message.get("thread"))
        if task is None:
            task = store.add((message.get("title") or "Hub handoff")[:300],
                             detail=(message.get("body") or "")[:8000], source=f"hub:{sender}",
                             status="in_progress", worker=message.get("to") or "")
        if task.get("handoff_id") != message.get("id"):
            task = store.update(task["id"], handoff_id=message.get("id"),
                                handoff_thread=message.get("thread"), status="in_progress")
        return task
    if kind in ("status", "question", "answer", "result"):
        task = store.by_handoff(message.get("reply_to"), message.get("thread"))
        if task is None or task["worker"] != sender:
            return None
        line = message.get("status_line") or ""
        state = status_from_message(kind, line)
        if state is None:
            return task
        # Same note shape as routes.on_message so both hooks agree on last_note.
        changes = {"last_note": (line or message.get("title") or kind)[:500]}
        if kind in ("result", "answer"):
            changes["handoff_result"] = "failed" if state == "needs_ok" else "done"
        if task["status"] != "done":
            changes["status"] = state
        changes = {key: value for key, value in changes.items() if task.get(key) != value}
        return store.update(task["id"], **changes) if changes else task
    return None
