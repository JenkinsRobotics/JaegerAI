"""Memory 2.0: SQLite WAL Persistent Learning Stores, Adaptive Recall, Multi-Day Goals & Cascading Forget.

Synthesizes production patterns into a zero-external-daemon SQLite WAL store
designed for a 32 GB 24/7 single-machine AI business team & persistent droid:
- **Agno `LearningMachine` + `Curator`**: Scoped stores (`user_profile`, `business`,
  `project`, `entity`, `learned_knowledge`, `decision_log`, `goal`, `episodic`).
- **CrewAI `RecallFlow` + `MemoryScope`**: Multi-factor recall scoring
  (BM25/token overlap + recency decay + importance + recall reinforcement).
- **AutoGPT `recall_cascade` + `recall_stamp` + `dream`**: Provenance-linked
  cascading forget (forgetting a source fact automatically retracts derived
  memories!), 30-day recall-protected consolidation, and persistent multi-day
  goals (business pipelines AND idle Minecraft persistence).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")

VALID_SCOPES = frozenset(
    {
        "user_profile",
        "business",
        "project",
        "entity",
        "learned_knowledge",
        "decision_log",
        "goal",
        "episodic",
    }
)


@dataclass(frozen=True)
class LearningEntry:
    entry_id: str
    scope: str
    subject: str
    content: str
    importance: float
    tags: tuple[str, ...] = ()
    parent_ids: tuple[str, ...] = ()
    recall_count: int = 0
    last_recalled_at: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "scope": self.scope,
            "subject": self.subject,
            "content": self.content,
            "importance": self.importance,
            "tags": list(self.tags),
            "parent_ids": list(self.parent_ids),
            "recall_count": self.recall_count,
            "last_recalled_at": self.last_recalled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PersistentGoal:
    goal_id: str
    domain: str  # "business" | "youtube" | "engineering" | "minecraft" | "droid"
    title: str
    status: str  # "active" | "paused" | "completed" | "abandoned"
    priority: int
    checkpoint: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "domain": self.domain,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "checkpoint": dict(self.checkpoint),
            "notes": self.notes,
            "updated_at": self.updated_at,
        }


class PersistentLearningStore:
    """SQLite WAL learning, adaptive recall, cascading-forget, and multi-day goal store."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "learning_memory.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_entries (
                    entry_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    parent_ids_json TEXT NOT NULL DEFAULT '[]',
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    last_recalled_at REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_scope ON learning_entries(scope, updated_at DESC);

                CREATE TABLE IF NOT EXISTS persistent_goals (
                    goal_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER NOT NULL DEFAULT 2,
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_goals_domain_status ON persistent_goals(domain, status, priority);
                """
            )

    def add(
        self,
        *,
        scope: str,
        content: str,
        subject: str = "owner",
        importance: float = 0.6,
        tags: Sequence[str] = (),
        parent_ids: Sequence[str] = (),
        entry_id: str | None = None,
    ) -> LearningEntry:
        clean_scope = scope if scope in VALID_SCOPES else "learned_knowledge"
        eid = entry_id or f"mem_{uuid.uuid4().hex[:12]}"
        now = time.time()
        norm_tags = tuple(dict.fromkeys(str(t).strip().lower() for t in tags if str(t).strip()))
        norm_parents = tuple(dict.fromkeys(str(p).strip() for p in parent_ids if str(p).strip()))
        imp = max(0.0, min(1.0, float(importance)))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO learning_entries
                (entry_id, scope, subject, content, importance, tags_json, parent_ids_json,
                 recall_count, last_recalled_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.0, ?, ?)
                """,
                (
                    eid,
                    clean_scope,
                    subject.strip() or "owner",
                    content.strip(),
                    imp,
                    json.dumps(list(norm_tags)),
                    json.dumps(list(norm_parents)),
                    now,
                    now,
                ),
            )
        return LearningEntry(
            entry_id=eid,
            scope=clean_scope,
            subject=subject.strip() or "owner",
            content=content.strip(),
            importance=imp,
            tags=norm_tags,
            parent_ids=norm_parents,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _row_to_entry(row: tuple[Any, ...]) -> LearningEntry:
        return LearningEntry(
            entry_id=row[0],
            scope=row[1],
            subject=row[2],
            content=row[3],
            importance=float(row[4]),
            tags=tuple(json.loads(row[5] or "[]")),
            parent_ids=tuple(json.loads(row[6] or "[]")),
            recall_count=int(row[7] or 0),
            last_recalled_at=float(row[8] or 0.0),
            created_at=float(row[9] or 0.0),
            updated_at=float(row[10] or 0.0),
        )

    def list_entries(self, *, scope: str | None = None, limit: int = 100) -> list[LearningEntry]:
        with self._lock, self._connect() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT * FROM learning_entries WHERE scope = ? ORDER BY updated_at DESC LIMIT ?",
                    (scope, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM learning_entries ORDER BY updated_at DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def recall(
        self,
        query: str,
        *,
        scopes: Sequence[str] | None = None,
        limit: int = 8,
        stamp_recall: bool = True,
    ) -> list[LearningEntry]:
        """Adaptive multi-factor recall (token overlap + recency + importance + recall boost)."""
        q_tokens = set(_TOKEN_RE.findall((query or "").lower()))
        with self._lock, self._connect() as conn:
            if scopes:
                placeholders = ",".join("?" for _ in scopes)
                rows = conn.execute(
                    f"SELECT * FROM learning_entries WHERE scope IN ({placeholders})",
                    tuple(scopes),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM learning_entries").fetchall()

        now = time.time()
        scored: list[tuple[float, LearningEntry]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            doc_tokens = set(_TOKEN_RE.findall(f"{entry.subject} {entry.content} {' '.join(entry.tags)}".lower()))
            overlap = (len(q_tokens & doc_tokens) / max(1, len(q_tokens))) if q_tokens else 0.25
            if q_tokens and overlap == 0.0:
                continue
            age_days = max(0.0, (now - entry.updated_at) / 86400.0)
            recency = math.exp(-age_days / 30.0)
            reinforcement = min(0.3, entry.recall_count * 0.05)
            score = (0.55 * overlap) + (0.25 * entry.importance) + (0.20 * recency) + reinforcement
            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = [e for _, e in scored[: max(1, int(limit))]]
        if stamp_recall and top:
            with self._lock, self._connect() as conn:
                for e in top:
                    conn.execute(
                        "UPDATE learning_entries SET recall_count = recall_count + 1, last_recalled_at = ? WHERE entry_id = ?",
                        (now, e.entry_id),
                    )
        return top

    def forget(self, entry_id: str, *, cascade: bool = True) -> list[str]:
        """Forget an entry and (when ``cascade=True``) recursively retract all derived memories."""
        removed: list[str] = []
        with self._lock, self._connect() as conn:
            all_rows = conn.execute("SELECT entry_id, parent_ids_json FROM learning_entries").fetchall()
            children_map: dict[str, list[str]] = {}
            existing_ids: set[str] = set()
            for eid, pjson in all_rows:
                existing_ids.add(eid)
                for pid in json.loads(pjson or "[]"):
                    children_map.setdefault(str(pid), []).append(eid)

            if entry_id not in existing_ids:
                return []

            queue = [entry_id]
            seen: set[str] = set()
            while queue:
                cur = queue.pop(0)
                if cur in seen:
                    continue
                seen.add(cur)
                removed.append(cur)
                if cascade:
                    queue.extend(children_map.get(cur, ()))

            placeholders = ",".join("?" for _ in removed)
            conn.execute(f"DELETE FROM learning_entries WHERE entry_id IN ({placeholders})", tuple(removed))
        return removed

    def consolidate(self, *, max_age_days: float = 30.0, min_importance: float = 0.25) -> int:
        """Prune stale low-importance memories while sparing anything recalled within ``max_age_days``."""
        cutoff = time.time() - (max_age_days * 86400.0)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM learning_entries
                WHERE importance < ?
                  AND updated_at < ?
                  AND (last_recalled_at = 0.0 OR last_recalled_at < ?)
                """,
                (min_importance, cutoff, cutoff),
            )
            return int(cur.rowcount or 0)

    # --- Persistent Multi-Day Goals (Business Pipelines + Idle Minecraft / Droid Life) ---

    def upsert_goal(
        self,
        *,
        domain: str,
        title: str,
        status: str = "active",
        priority: int = 2,
        checkpoint: Mapping[str, Any] | None = None,
        notes: str = "",
        goal_id: str | None = None,
    ) -> PersistentGoal:
        gid = goal_id or f"goal_{uuid.uuid4().hex[:10]}"
        now = time.time()
        cp = dict(checkpoint or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO persistent_goals
                (goal_id, domain, title, status, priority, checkpoint_json, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (gid, domain.strip().lower(), title.strip(), status, int(priority), json.dumps(cp), notes, now),
            )
        return PersistentGoal(
            goal_id=gid,
            domain=domain.strip().lower(),
            title=title.strip(),
            status=status,
            priority=int(priority),
            checkpoint=cp,
            notes=notes,
            updated_at=now,
        )

    def list_goals(self, *, domain: str | None = None, status: str | None = None) -> list[PersistentGoal]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain.strip().lower())
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT goal_id, domain, title, status, priority, checkpoint_json, notes, updated_at "
                f"FROM persistent_goals {where} ORDER BY priority ASC, updated_at DESC",
                tuple(params),
            ).fetchall()
        return [
            PersistentGoal(
                goal_id=r[0],
                domain=r[1],
                title=r[2],
                status=r[3],
                priority=int(r[4]),
                checkpoint=json.loads(r[5] or "{}"),
                notes=r[6],
                updated_at=float(r[7]),
            )
            for r in rows
        ]


__all__ = ["LearningEntry", "PersistentGoal", "PersistentLearningStore", "VALID_SCOPES"]
