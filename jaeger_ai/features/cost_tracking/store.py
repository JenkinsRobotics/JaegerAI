"""SQLite-backed cost ledger with deterministic budget admission."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Self

_PERIODS = frozenset({"day", "month", "all"})


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    scope: str
    period: str
    limit_usd: float | None
    spent_usd: float
    projected_usd: float
    reason: str


class CostStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS budget_limits (
                    scope TEXT NOT NULL,
                    period TEXT NOT NULL,
                    limit_usd REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (scope, period)
                );
                CREATE TABLE IF NOT EXISTS cost_records (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    model TEXT,
                    task_id TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cost_scope_time
                    ON cost_records(scope, created_at);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def set_limit(self, scope: str, period: str, limit_usd: float) -> None:
        scope, period = _validate(scope, period)
        limit = float(limit_usd)
        if limit < 0:
            raise ValueError("budget limit cannot be negative")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO budget_limits(scope,period,limit_usd,updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(scope,period) DO UPDATE SET "
                "limit_usd=excluded.limit_usd, updated_at=excluded.updated_at",
                (scope, period, limit, time.time()),
            )

    def authorize(self, scope: str, estimated_cost_usd: float) -> BudgetDecision:
        scope = str(scope or "global").strip().lower() or "global"
        estimate = float(estimated_cost_usd)
        if estimate < 0:
            raise ValueError("estimated cost cannot be negative")
        with self._lock:
            limits = self._conn.execute(
                "SELECT scope,period,limit_usd FROM budget_limits "
                "WHERE scope IN ('global', ?)",
                (scope,),
            ).fetchall()
            decisions = []
            for row in limits:
                start = _period_start(str(row["period"]))
                if row["scope"] == "global":
                    spent_row = self._conn.execute(
                        "SELECT COALESCE(SUM(cost_usd),0) FROM cost_records "
                        "WHERE created_at >= ?",
                        (start,),
                    ).fetchone()
                else:
                    spent_row = self._conn.execute(
                        "SELECT COALESCE(SUM(cost_usd),0) FROM cost_records "
                        "WHERE scope = ? AND created_at >= ?",
                        (scope, start),
                    ).fetchone()
                spent = float(spent_row[0])
                projected = spent + estimate
                decisions.append(BudgetDecision(
                    projected <= float(row["limit_usd"]),
                    str(row["scope"]),
                    str(row["period"]),
                    float(row["limit_usd"]),
                    spent,
                    projected,
                    "within budget" if projected <= float(row["limit_usd"]) else "budget exceeded",
                ))
            blocked = next((item for item in decisions if not item.allowed), None)
            if blocked:
                return blocked
            return decisions[0] if decisions else BudgetDecision(
                True, scope, "all", None, 0.0, estimate, "no budget limit configured"
            )

    def record(
        self,
        *,
        runtime_id: str,
        cost_usd: float,
        task_id: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> str:
        runtime = str(runtime_id or "").strip().lower()
        if not runtime:
            raise ValueError("runtime_id is required")
        cost = float(cost_usd)
        if cost < 0:
            raise ValueError("cost cannot be negative")
        record_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO cost_records VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    runtime,
                    runtime,
                    model or None,
                    task_id or None,
                    max(0, int(input_tokens)),
                    max(0, int(output_tokens)),
                    cost,
                    time.time(),
                ),
            )
        return record_id

    def summary(self, scope: str = "global") -> dict:
        scope = str(scope or "global").strip().lower()
        with self._lock:
            where = "1=1" if scope == "global" else "scope IN ('global', ?)"
            params = () if scope == "global" else (scope,)
            totals = self._conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(cost_usd),0),"
                "COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) "
                f"FROM cost_records WHERE {where}",
                params,
            ).fetchone()
            limits = [dict(row) for row in self._conn.execute(
                "SELECT scope,period,limit_usd,updated_at FROM budget_limits "
                "WHERE scope IN ('global', ?) ORDER BY scope,period",
                (scope,),
            ).fetchall()]
        return {
            "scope": scope,
            "records": int(totals[0]),
            "cost_usd": float(totals[1]),
            "input_tokens": int(totals[2]),
            "output_tokens": int(totals[3]),
            "limits": limits,
        }


def _validate(scope: str, period: str) -> tuple[str, str]:
    clean_scope = str(scope or "").strip().lower()
    clean_period = str(period or "").strip().lower()
    if not clean_scope:
        raise ValueError("budget scope is required")
    if clean_period not in _PERIODS:
        raise ValueError("budget period must be day, month, or all")
    return clean_scope, clean_period


def _period_start(period: str) -> float:
    if period == "all":
        return 0.0
    now = time.localtime()
    day = time.struct_time((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    if period == "day":
        return time.mktime(day)
    month = time.struct_time((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    return time.mktime(month)
