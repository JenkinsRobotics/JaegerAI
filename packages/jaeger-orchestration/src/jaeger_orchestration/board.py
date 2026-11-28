"""SQLite WAL Kanban Task Board & Native One-Shot Reminders (JROS patterns).

Zero external daemons; pure Python stdlib + SQLite WAL:
- ``KanbanBoard``: multi-step work cards across ``backlog``, ``todo``,
  ``in_progress``, ``review``, and ``done`` columns with priorities, tags,
  and Markdown board rendering.
- ``OneShotReminderStore``: native ``in_minutes`` / ``at_iso`` one-shot
  reminders ("remind me in 10 minutes") with no cron arithmetic required.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as _dt
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable
import uuid

KANBAN_COLUMNS: tuple[str, ...] = ("backlog", "todo", "in_progress", "review", "done")


@dataclass(frozen=True)
class BoardCard:
    card_id: str
    title: str
    column: str
    priority: int
    tags: tuple[str, ...]
    notes: str
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "tags": list(self.tags)}


@dataclass(frozen=True)
class OneShotReminder:
    reminder_id: str
    message: str
    due_at: float
    status: str  # "pending" | "fired" | "cancelled"
    created_at: float
    fired_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        due_iso = _dt.datetime.fromtimestamp(self.due_at).isoformat(timespec="seconds")
        return {**asdict(self), "due_iso": due_iso}


class KanbanBoard:
    """Embedded SQLite WAL Kanban board for planning and tracking multi-step tasks."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kanban_cards (
                    card_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    col TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 2,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _validate_col(column: str) -> str:
        c = (column or "todo").strip().lower()
        if c not in KANBAN_COLUMNS:
            raise ValueError(f"invalid column {column!r}; expected one of {KANBAN_COLUMNS}")
        return c

    def _row_to_card(self, row: tuple[Any, ...]) -> BoardCard:
        try:
            tags = tuple(str(t) for t in json.loads(row[4] or "[]"))
        except json.JSONDecodeError:
            tags = ()
        return BoardCard(
            card_id=str(row[0]),
            title=str(row[1]),
            column=str(row[2]),
            priority=int(row[3]),
            tags=tags,
            notes=str(row[5] or ""),
            created_at=float(row[6]),
            updated_at=float(row[7]),
        )

    def create_card(
        self,
        title: str,
        *,
        column: str = "todo",
        priority: int = 2,
        tags: Iterable[str] = (),
        notes: str = "",
    ) -> BoardCard:
        clean = (title or "").strip()
        if not clean or len(clean) > 200:
            raise ValueError("title must be 1-200 characters")
        col = self._validate_col(column)
        prio = max(1, min(int(priority or 2), 4))
        clean_tags = [str(t).strip()[:40] for t in tags if str(t).strip()][:10]
        now = time.time()
        cid = f"card_{uuid.uuid4().hex[:8]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kanban_cards (card_id, title, col, priority, tags_json, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, clean, col, prio, json.dumps(clean_tags), (notes or "")[:4000], now, now),
            )
        return BoardCard(cid, clean, col, prio, tuple(clean_tags), (notes or "")[:4000], now, now)

    def move_card(self, card_id: str, column: str, *, notes: str | None = None) -> BoardCard:
        col = self._validate_col(column)
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT card_id, title, col, priority, tags_json, notes, created_at, updated_at FROM kanban_cards WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"card not found: {card_id}")
            new_notes = str(notes)[:4000] if notes is not None else str(row[5] or "")
            conn.execute(
                "UPDATE kanban_cards SET col = ?, notes = ?, updated_at = ? WHERE card_id = ?",
                (col, new_notes, now, card_id),
            )
            return self._row_to_card((row[0], row[1], col, row[3], row[4], new_notes, row[6], now))

    def delete_card(self, card_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM kanban_cards WHERE card_id = ?", (card_id,))
            return cur.rowcount > 0

    def list_cards(self, *, column: str | None = None, limit: int = 100) -> list[BoardCard]:
        cap = max(1, min(int(limit or 100), 500))
        with self._lock, self._connect() as conn:
            if column:
                col = self._validate_col(column)
                rows = conn.execute(
                    "SELECT card_id, title, col, priority, tags_json, notes, created_at, updated_at "
                    "FROM kanban_cards WHERE col = ? ORDER BY priority ASC, updated_at DESC LIMIT ?",
                    (col, cap),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT card_id, title, col, priority, tags_json, notes, created_at, updated_at "
                    "FROM kanban_cards ORDER BY priority ASC, updated_at DESC LIMIT ?",
                    (cap,),
                ).fetchall()
        return [self._row_to_card(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        cards = self.list_cards(limit=200)
        grouped: dict[str, list[dict[str, Any]]] = {col: [] for col in KANBAN_COLUMNS}
        for c in cards:
            grouped.setdefault(c.column, []).append(c.to_dict())
        return {
            "ok": True,
            "columns": grouped,
            "counts": {col: len(grouped[col]) for col in KANBAN_COLUMNS},
            "total": len(cards),
        }

    def render_markdown(self) -> str:
        s = self.summary()
        lines = ["# Jaeger Task Board", ""]
        for col in KANBAN_COLUMNS:
            items = s["columns"][col]
            lines.append(f"## {col.replace('_', ' ').title()} ({len(items)})")
            if not items:
                lines.append("_Empty_")
            for c in items:
                tag_str = f" `{'` `'.join(c['tags'])}`" if c["tags"] else ""
                lines.append(f"- [P{c['priority']}] **{c['title']}** (`{c['card_id']}`){tag_str}")
            lines.append("")
        return "\n".join(lines).strip()


class OneShotReminderStore:
    """Native one-shot reminder store supporting ``in_minutes`` or ISO ``at_iso``."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oneshot_reminders (
                    reminder_id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    fired_at REAL
                )
                """
            )

    def schedule(
        self,
        message: str,
        *,
        in_minutes: float | None = None,
        at_iso: str | None = None,
        now: float | None = None,
    ) -> OneShotReminder:
        clean = (message or "").strip()
        if not clean or len(clean) > 400:
            raise ValueError("message must be 1-400 characters")
        cur_ts = float(now if now is not None else time.time())
        if in_minutes is not None:
            mins = float(in_minutes)
            if mins <= 0 or mins > 60 * 24 * 365:
                raise ValueError("in_minutes must be > 0 and <= 525600")
            due_at = cur_ts + mins * 60.0
        elif at_iso and at_iso.strip():
            raw = at_iso.strip()
            cleaned = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                dt = _dt.datetime.fromisoformat(cleaned)
            except ValueError as exc:
                raise ValueError(f"invalid ISO datetime: {at_iso!r}") from exc
            due_at = dt.timestamp()
        else:
            raise ValueError("provide either in_minutes or at_iso")

        rid = f"rem_{uuid.uuid4().hex[:8]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO oneshot_reminders (reminder_id, message, due_at, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (rid, clean, due_at, cur_ts),
            )
        return OneShotReminder(rid, clean, due_at, "pending", cur_ts, None)

    def list_reminders(self, *, status: str | None = "pending", limit: int = 50) -> list[OneShotReminder]:
        cap = max(1, min(int(limit or 50), 200))
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT reminder_id, message, due_at, status, created_at, fired_at "
                    "FROM oneshot_reminders WHERE status = ? ORDER BY due_at ASC LIMIT ?",
                    (status, cap),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT reminder_id, message, due_at, status, created_at, fired_at "
                    "FROM oneshot_reminders ORDER BY due_at ASC LIMIT ?",
                    (cap,),
                ).fetchall()
        return [
            OneShotReminder(str(r[0]), str(r[1]), float(r[2]), str(r[3]), float(r[4]), float(r[5]) if r[5] is not None else None)
            for r in rows
        ]

    def claim_due(self, *, now: float | None = None) -> list[OneShotReminder]:
        """Atomically mark all due pending reminders as ``fired`` and return them."""
        cur_ts = float(now if now is not None else time.time())
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT reminder_id, message, due_at, status, created_at, fired_at "
                "FROM oneshot_reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
                (cur_ts,),
            ).fetchall()
            if not rows:
                return []
            ids = [str(r[0]) for r in rows]
            conn.executemany(
                "UPDATE oneshot_reminders SET status = 'fired', fired_at = ? WHERE reminder_id = ?",
                [(cur_ts, rid) for rid in ids],
            )
        return [OneShotReminder(str(r[0]), str(r[1]), float(r[2]), "fired", float(r[4]), cur_ts) for r in rows]

    def cancel(self, reminder_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE oneshot_reminders SET status = 'cancelled' WHERE reminder_id = ? AND status = 'pending'",
                (reminder_id,),
            )
            return cur.rowcount > 0


__all__ = [
    "BoardCard",
    "KANBAN_COLUMNS",
    "KanbanBoard",
    "OneShotReminder",
    "OneShotReminderStore",
]
