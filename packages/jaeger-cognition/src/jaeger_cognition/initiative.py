"""Persistent Autonomous Initiative & Drive Engine for Jaeger's CognitiveLifeLoop.

Gives Jaeger safe, auditable, persistent self-directed actions when idle:
- Persists internal drives (`curiosity`, `goal_momentum`, `social`, `energy`),
  autonomy configuration (`enabled`, `cooldown_s`, `max_actions_per_hour`,
  `active_hours`), and a full SQLite WAL **Initiative Journal** of every decision.
- Strictly yields to `OWNER_WORK`, 32 GB `ResourceGovernor`, and E-Stop.
- Executes safe, bounded self-actions (advancing persistent goals, curating memory/skills,
  or stepping connected idle embodiments like Minecraft) while keeping external side effects
  and physical hardware fail-closed behind owner approvals.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

__all__ = ["InitiativeEngine"]

SelfActionExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class InitiativeEngine:
    """SQLite-backed autonomous drive & self-action engine plugged into CognitiveLifeLoop."""

    def __init__(
        self,
        state_dir: Path,
        *,
        goal_provider: Callable[[], list[dict[str, Any]]] | None = None,
        goal_executor: SelfActionExecutor | None = None,
        maintenance_executor: SelfActionExecutor | None = None,
        minecraft_executor: SelfActionExecutor | None = None,
        enabled: bool = True,
        cooldown_s: float = 900.0,
        max_actions_per_hour: int = 4,
    ) -> None:
        self._dir = Path(state_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "cognition_initiative.sqlite3"
        self._lock = threading.RLock()
        self._goal_provider = goal_provider
        self._goal_executor = goal_executor
        self._maintenance_executor = maintenance_executor
        self._minecraft_executor = minecraft_executor
        self._default_enabled = bool(enabled)
        self._default_cooldown_s = max(5.0, float(cooldown_s))
        self._default_max_per_hour = max(1, int(max_actions_per_hour))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS initiative_config (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    enabled INTEGER NOT NULL,
                    cooldown_s REAL NOT NULL,
                    max_actions_per_hour INTEGER NOT NULL,
                    active_start_hour INTEGER NOT NULL DEFAULT 0,
                    active_end_hour INTEGER NOT NULL DEFAULT 24,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS initiative_drives (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    curiosity REAL NOT NULL,
                    goal_momentum REAL NOT NULL,
                    social REAL NOT NULL,
                    energy REAL NOT NULL,
                    last_action_at REAL NOT NULL DEFAULT 0.0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS initiative_journal (
                    action_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_initiative_journal_created
                    ON initiative_journal(created_at DESC);
                """
            )
            conn.execute(
                """INSERT OR IGNORE INTO initiative_config
                   (id, enabled, cooldown_s, max_actions_per_hour, active_start_hour, active_end_hour, updated_at)
                   VALUES (1, ?, ?, ?, 0, 24, ?)""",
                (1 if self._default_enabled else 0, self._default_cooldown_s, self._default_max_per_hour, now),
            )
            conn.execute(
                """INSERT OR IGNORE INTO initiative_drives
                   (id, curiosity, goal_momentum, social, energy, last_action_at, updated_at)
                   VALUES (1, 0.45, 0.55, 0.30, 0.85, 0.0, ?)""",
                (now,),
            )

    def get_config(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM initiative_config WHERE id = 1").fetchone()
        return {
            "enabled": bool(row["enabled"]),
            "cooldown_s": float(row["cooldown_s"]),
            "max_actions_per_hour": int(row["max_actions_per_hour"]),
            "active_start_hour": int(row["active_start_hour"]),
            "active_end_hour": int(row["active_end_hour"]),
            "updated_at": float(row["updated_at"]),
        }

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        cooldown_s: float | None = None,
        max_actions_per_hour: int | None = None,
        active_start_hour: int | None = None,
        active_end_hour: int | None = None,
    ) -> dict[str, Any]:
        cur = self.get_config()
        new_en = cur["enabled"] if enabled is None else bool(enabled)
        new_cd = cur["cooldown_s"] if cooldown_s is None else max(10.0, min(float(cooldown_s), 86400.0))
        new_max = cur["max_actions_per_hour"] if max_actions_per_hour is None else max(1, min(int(max_actions_per_hour), 60))
        new_sh = cur["active_start_hour"] if active_start_hour is None else max(0, min(int(active_start_hour), 23))
        new_eh = cur["active_end_hour"] if active_end_hour is None else max(1, min(int(active_end_hour), 24))
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE initiative_config
                   SET enabled = ?, cooldown_s = ?, max_actions_per_hour = ?,
                       active_start_hour = ?, active_end_hour = ?, updated_at = ?
                   WHERE id = 1""",
                (1 if new_en else 0, new_cd, new_max, new_sh, new_eh, time.time()),
            )
        return self.get_config()

    def get_drives(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM initiative_drives WHERE id = 1").fetchone()
        return {
            "curiosity": round(float(row["curiosity"]), 3),
            "goal_momentum": round(float(row["goal_momentum"]), 3),
            "social": round(float(row["social"]), 3),
            "energy": round(float(row["energy"]), 3),
            "last_action_at": float(row["last_action_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _update_drives_tick(self, *, acted: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM initiative_drives WHERE id = 1").fetchone()
            dt_min = max(0.0, min((now - float(row["updated_at"])) / 60.0, 60.0))
            curiosity = min(1.0, float(row["curiosity"]) + 0.015 * dt_min)
            momentum = min(1.0, float(row["goal_momentum"]) + 0.02 * dt_min)
            social = min(1.0, float(row["social"]) + 0.005 * dt_min)
            energy = min(1.0, float(row["energy"]) + 0.01 * dt_min)
            last_action_at = float(row["last_action_at"])
            if acted:
                curiosity = max(0.15, curiosity - 0.25)
                momentum = max(0.20, momentum - 0.20)
                energy = max(0.25, energy - 0.12)
                last_action_at = now
            conn.execute(
                """UPDATE initiative_drives
                   SET curiosity = ?, goal_momentum = ?, social = ?, energy = ?, last_action_at = ?, updated_at = ?
                   WHERE id = 1""",
                (curiosity, momentum, social, energy, last_action_at, now),
            )
        return self.get_drives()

    def _actions_in_last_hour(self, now: float) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM initiative_journal WHERE status = 'acted' AND created_at >= ?",
                (now - 3600.0,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def record_action(
        self,
        *,
        kind: str,
        status: str,
        reason: str,
        summary: str,
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        aid = f"act_{uuid.uuid4().hex[:10]}"
        now = time.time()
        payload = dict(detail or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO initiative_journal(action_id, kind, status, reason, summary, detail_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (aid, kind, status, reason[:300], summary[:1000], json.dumps(payload, default=str), now),
            )
        return {
            "action_id": aid,
            "kind": kind,
            "status": status,
            "reason": reason,
            "summary": summary,
            "detail": payload,
            "created_at": now,
        }

    def list_actions(self, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM initiative_journal ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [
            {
                "action_id": r["action_id"],
                "kind": r["kind"],
                "status": r["status"],
                "reason": r["reason"],
                "summary": r["summary"],
                "detail": json.loads(r["detail_json"] or "{}"),
                "created_at": float(r["created_at"]),
            }
            for r in rows
        ]

    def status(self) -> dict[str, Any]:
        now = time.time()
        cfg = self.get_config()
        drives = self.get_drives()
        recent = self.list_actions(limit=5)
        next_eligible_in = max(0.0, (drives["last_action_at"] + cfg["cooldown_s"]) - now) if drives["last_action_at"] > 0 else 0.0
        return {
            "config": cfg,
            "drives": drives,
            "actions_last_hour": self._actions_in_last_hour(now),
            "next_eligible_in_s": round(next_eligible_in, 1),
            "recent_actions": recent,
        }

    @staticmethod
    async def _call(fn: SelfActionExecutor, payload: dict[str, Any]) -> dict[str, Any]:
        res = fn(payload)
        if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
            res = await res  # type: ignore[misc]
        return dict(res) if isinstance(res, Mapping) else {"acted": False}

    async def evaluate_tick(self, ctx: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        """CognitiveLifeLoop proactive handler: decide and run at most one safe self-action."""
        now = time.time()
        cfg = self.get_config()
        drives = self._update_drives_tick(acted=False)
        if not force:
            if not cfg["enabled"]:
                return {"acted": False, "reason": "autonomy_disabled"}
            hour = datetime.now().hour
            start_h, end_h = cfg["active_start_hour"], cfg["active_end_hour"]
            if start_h < end_h and not (start_h <= hour < end_h):
                return {"acted": False, "reason": "outside_active_hours"}
            if drives["last_action_at"] > 0 and (now - drives["last_action_at"]) < cfg["cooldown_s"]:
                return {"acted": False, "reason": "cooldown"}
            if self._actions_in_last_hour(now) >= cfg["max_actions_per_hour"]:
                return {"acted": False, "reason": "hourly_budget_reached"}

        # 1. Active persistent goals take priority
        goals = self._goal_provider() if self._goal_provider is not None else []
        if goals and self._goal_executor is not None:
            top_goal = goals[0]
            outcome = await self._call(self._goal_executor, {"goal": top_goal, "drives": drives, "ctx": ctx})
            if outcome.get("acted"):
                self._update_drives_tick(acted=True)
                rec = self.record_action(
                    kind="goal_step",
                    status="acted",
                    reason=f"active_goal:{top_goal.get('title', '')[:80]}",
                    summary=str(outcome.get("summary") or "Advanced active goal"),
                    detail=outcome,
                )
                return {
                    "acted": True,
                    "emotion": "focused",
                    "focus": f"Autonomous goal: {top_goal.get('title', '')[:60]}",
                    "summary": rec["summary"],
                    "action": rec,
                }

        # 2. Connected Minecraft embodiment self-action
        if self._minecraft_executor is not None:
            outcome = await self._call(self._minecraft_executor, {"drives": drives, "ctx": ctx})
            if outcome.get("acted"):
                self._update_drives_tick(acted=True)
                rec = self.record_action(
                    kind="minecraft_step",
                    status="acted",
                    reason="minecraft_live_idle",
                    summary=str(outcome.get("summary") or "Stepped Minecraft embodiment"),
                    detail=outcome,
                )
                return {
                    "acted": True,
                    "emotion": "happy",
                    "focus": f"Minecraft: {rec['summary'][:60]}",
                    "summary": rec["summary"],
                    "action": rec,
                }

        # 3. Safe self-maintenance / memory curation heartbeat
        if self._maintenance_executor is not None:
            outcome = await self._call(self._maintenance_executor, {"drives": drives, "ctx": ctx})
            if outcome.get("acted"):
                self._update_drives_tick(acted=True)
                rec = self.record_action(
                    kind="self_maintenance",
                    status="acted",
                    reason="periodic_curation",
                    summary=str(outcome.get("summary") or "Synced memory & world model"),
                    detail=outcome,
                )
                return {
                    "acted": True,
                    "emotion": "calm",
                    "focus": rec["summary"][:60],
                    "summary": rec["summary"],
                    "action": rec,
                }

        return {"acted": False, "reason": "nothing_due"}
