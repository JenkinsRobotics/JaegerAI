"""SQLite persistence for the user-controlled Human Needs & Flourishing Engine.

Lives strictly under ``operator_state_root() / "human_needs.sqlite3"`` so
isolated tests and sandboxed runs never touch the operator's live state.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.instance import operator_state_root

from .policy import FlourishingDimension, SignalKind

GOAL_STATUSES = frozenset({"active", "paused", "completed", "archived", "rejected"})
OPPORTUNITY_STATUSES = frozenset({"proposed", "accepted", "rejected", "deferred", "completed"})


def default_human_needs_db() -> Path:
    return operator_state_root() / "human_needs.sqlite3"


class HumanNeedsStore:
    """User-owned goals, linked opportunities, and measurable outcomes."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_human_needs_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_goals (
                    goal_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    signal_kind TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 3,
                    status TEXT NOT NULL DEFAULT 'active',
                    notes TEXT NOT NULL DEFAULT '',
                    success_metric TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_opportunities (
                    opportunity_id TEXT PRIMARY KEY,
                    goal_id TEXT,
                    dimension TEXT NOT NULL,
                    signal_kind TEXT NOT NULL DEFAULT 'inferred_opportunity',
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    proposed_action TEXT NOT NULL DEFAULT '',
                    requires_authorization INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    user_feedback TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (goal_id) REFERENCES user_goals(goal_id)
                );

                CREATE TABLE IF NOT EXISTS user_outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    goal_id TEXT,
                    opportunity_id TEXT,
                    signal_kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metric_name TEXT NOT NULL DEFAULT '',
                    metric_before TEXT NOT NULL DEFAULT '',
                    metric_after TEXT NOT NULL DEFAULT '',
                    evidence_ref TEXT NOT NULL DEFAULT '',
                    recorded_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_goals_status ON user_goals(status);
                CREATE INDEX IF NOT EXISTS idx_opp_status ON user_opportunities(status);
                CREATE INDEX IF NOT EXISTS idx_outcomes_goal ON user_outcomes(goal_id);
                """
            )

    # ── Goals ──────────────────────────────────────────────────────────

    def add_goal(
        self,
        title: str,
        dimension: FlourishingDimension | str,
        *,
        signal_kind: SignalKind | str = SignalKind.USER_PREFERENCE,
        priority: int = 3,
        notes: str = "",
        success_metric: str = "",
    ) -> dict[str, Any]:
        clean_title = (title or "").strip()
        if not clean_title or len(clean_title) > 300:
            raise ValueError("goal title must be 1-300 characters")
        dim = FlourishingDimension(dimension).value
        sig = SignalKind(signal_kind).value
        prio = max(1, min(5, int(priority)))
        now = time.time()
        gid = f"goal_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_goals (goal_id,title,dimension,signal_kind,priority,status,notes,success_metric,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'active',?,?,?,?)",
                (gid, clean_title, dim, sig, prio, str(notes or "")[:2000], str(success_metric or "")[:500], now, now),
            )
            row = conn.execute("SELECT * FROM user_goals WHERE goal_id=?", (gid,)).fetchone()
        return dict(row)

    def update_goal(
        self,
        goal_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        priority: int | None = None,
        notes: str | None = None,
        success_metric: str | None = None,
    ) -> dict[str, Any]:
        updates: list[str] = []
        params: list[Any] = []
        if title is not None:
            clean = title.strip()
            if not clean or len(clean) > 300:
                raise ValueError("goal title must be 1-300 characters")
            updates.append("title=?"); params.append(clean)
        if status is not None:
            if status not in GOAL_STATUSES:
                raise ValueError(f"status must be one of {sorted(GOAL_STATUSES)}")
            updates.append("status=?"); params.append(status)
        if priority is not None:
            updates.append("priority=?"); params.append(max(1, min(5, int(priority))))
        if notes is not None:
            updates.append("notes=?"); params.append(str(notes)[:2000])
        if success_metric is not None:
            updates.append("success_metric=?"); params.append(str(success_metric)[:500])
        if not updates:
            raise ValueError("no fields provided to update")
        updates.append("updated_at=?"); params.append(time.time())
        params.append(goal_id)
        with self._connect() as conn:
            cur = conn.execute("UPDATE user_goals SET " + ", ".join(updates) + " WHERE goal_id=?", params)
            if cur.rowcount == 0:
                raise ValueError(f"goal '{goal_id}' not found")
            row = conn.execute("SELECT * FROM user_goals WHERE goal_id=?", (goal_id,)).fetchone()
        return dict(row)

    def list_goals(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM user_goals"
        if not include_inactive:
            sql += " WHERE status IN ('active', 'paused')"
        sql += " ORDER BY priority ASC, updated_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    # ── Opportunities ──────────────────────────────────────────────────

    def propose_opportunity(
        self,
        title: str,
        dimension: FlourishingDimension | str,
        rationale: str,
        *,
        goal_id: str | None = None,
        proposed_action: str = "",
        requires_authorization: bool = True,
    ) -> dict[str, Any]:
        clean_title = (title or "").strip()
        clean_rationale = (rationale or "").strip()
        if not clean_title or not clean_rationale:
            raise ValueError("opportunity requires title and rationale")
        dim = FlourishingDimension(dimension).value
        now = time.time()
        oid = f"opp_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            if goal_id is not None:
                exists = conn.execute("SELECT 1 FROM user_goals WHERE goal_id=?", (goal_id,)).fetchone()
                if not exists:
                    raise ValueError(f"goal '{goal_id}' not found")
            conn.execute(
                "INSERT INTO user_opportunities "
                "(opportunity_id,goal_id,dimension,signal_kind,title,rationale,proposed_action,requires_authorization,status,user_feedback,created_at,updated_at) "
                "VALUES (?,?,?,'inferred_opportunity',?,?,?,?,'proposed','',?,?)",
                (oid, goal_id, dim, clean_title[:300], clean_rationale[:2000], str(proposed_action or "")[:1000],
                 1 if requires_authorization else 0, now, now),
            )
            row = conn.execute("SELECT * FROM user_opportunities WHERE opportunity_id=?", (oid,)).fetchone()
        return dict(row)

    def decide_opportunity(
        self,
        opportunity_id: str,
        decision: str,
        *,
        user_feedback: str = "",
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "deferred", "completed"}:
            raise ValueError("decision must be accepted, rejected, deferred, or completed")
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE user_opportunities SET status=?, user_feedback=?, updated_at=? WHERE opportunity_id=?",
                (decision, str(user_feedback or "")[:1000], now, opportunity_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"opportunity '{opportunity_id}' not found")
            row = conn.execute("SELECT * FROM user_opportunities WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        return dict(row)

    def list_opportunities(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM user_opportunities WHERE status=? ORDER BY updated_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM user_opportunities ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    # ── Outcomes & Export ──────────────────────────────────────────────

    def record_outcome(
        self,
        summary: str,
        *,
        goal_id: str | None = None,
        opportunity_id: str | None = None,
        signal_kind: SignalKind | str = SignalKind.OBJECTIVE_MEASURE,
        metric_name: str = "",
        metric_before: str = "",
        metric_after: str = "",
        evidence_ref: str = "",
    ) -> dict[str, Any]:
        clean = (summary or "").strip()
        if not clean:
            raise ValueError("outcome summary required")
        sig = SignalKind(signal_kind).value
        now = time.time()
        out_id = f"out_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_outcomes "
                "(outcome_id,goal_id,opportunity_id,signal_kind,summary,metric_name,metric_before,metric_after,evidence_ref,recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (out_id, goal_id, opportunity_id, sig, clean[:2000], str(metric_name or "")[:200],
                 str(metric_before or "")[:200], str(metric_after or "")[:200], str(evidence_ref or "")[:500], now),
            )
            row = conn.execute("SELECT * FROM user_outcomes WHERE outcome_id=?", (out_id,)).fetchone()
        return dict(row)

    def list_outcomes(self, *, goal_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if goal_id:
                rows = conn.execute(
                    "SELECT * FROM user_outcomes WHERE goal_id=? ORDER BY recorded_at DESC LIMIT ?",
                    (goal_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM user_outcomes ORDER BY recorded_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def export_all(self) -> dict[str, Any]:
        """Full user-owned export of goals, opportunities, and outcomes."""
        return {
            "schema": "jaeger.human_needs.export.v1",
            "exported_at": time.time(),
            "dimensions": [d.value for d in FlourishingDimension],
            "goals": self.list_goals(include_inactive=True),
            "opportunities": self.list_opportunities(),
            "outcomes": self.list_outcomes(limit=1000),
        }
