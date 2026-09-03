"""Durable observations and conservative delegate effectiveness estimates."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from jaeger_agent.memory import sqlite_store


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class DelegateObservation:
    runtime_id: str
    success: bool
    latency_ms: int
    capability: str = "general"
    quality: float | None = None
    cost_usd: float | None = None
    error_category: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    observed_at: str = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class Effectiveness:
    runtime_id: str
    capability: str
    samples: int
    successes: int
    success_rate: float
    mean_latency_ms: float
    mean_quality: float
    total_cost_usd: float


class DelegateHealthStore(Protocol):
    def record(self, observation: DelegateObservation) -> None: ...

    def effectiveness(self, runtime_id: str, capability: str = "general") -> Effectiveness: ...


class InMemoryDelegateHealthStore:
    def __init__(self) -> None:
        self._rows: list[DelegateObservation] = []
        self._lock = threading.RLock()

    def record(self, observation: DelegateObservation) -> None:
        _validate(observation)
        with self._lock:
            self._rows.append(observation)

    def effectiveness(self, runtime_id: str, capability: str = "general") -> Effectiveness:
        with self._lock:
            rows = [
                row
                for row in self._rows
                if row.runtime_id == runtime_id
                and (row.capability == capability or row.capability == "general")
            ]
        return _aggregate(runtime_id, capability, rows)


class SqliteDelegateHealthStore:
    """Feature-owned table in Jaeger's WAL-backed instance database."""

    def _ensure(self) -> None:
        with sqlite_store.writer() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delegate_observations (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    runtime_id     TEXT NOT NULL,
                    capability     TEXT NOT NULL DEFAULT 'general',
                    success        INTEGER NOT NULL,
                    latency_ms     INTEGER NOT NULL,
                    quality        REAL,
                    cost_usd       REAL,
                    error_category TEXT,
                    metadata_json  TEXT NOT NULL DEFAULT '{}',
                    observed_at    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_delegate_observations_runtime "
                "ON delegate_observations (runtime_id, capability, observed_at)"
            )

    def record(self, observation: DelegateObservation) -> None:
        _validate(observation)
        self._ensure()
        with sqlite_store.writer() as conn:
            conn.execute(
                """
                INSERT INTO delegate_observations
                    (runtime_id, capability, success, latency_ms, quality,
                     cost_usd, error_category, metadata_json, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.runtime_id,
                    observation.capability,
                    int(observation.success),
                    observation.latency_ms,
                    observation.quality,
                    observation.cost_usd,
                    observation.error_category,
                    json.dumps(observation.metadata, sort_keys=True),
                    observation.observed_at,
                ),
            )

    def effectiveness(self, runtime_id: str, capability: str = "general") -> Effectiveness:
        self._ensure()
        rows = sqlite_store.connection().execute(
            """
            SELECT runtime_id, capability, success, latency_ms, quality,
                   cost_usd, error_category, metadata_json, observed_at
            FROM delegate_observations
            WHERE runtime_id = ? AND (capability = ? OR capability = 'general')
            ORDER BY observed_at DESC
            LIMIT 500
            """,
            (runtime_id, capability),
        ).fetchall()
        observations = [
            DelegateObservation(
                runtime_id=str(row["runtime_id"]),
                capability=str(row["capability"]),
                success=bool(row["success"]),
                latency_ms=int(row["latency_ms"]),
                quality=float(row["quality"]) if row["quality"] is not None else None,
                cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
                error_category=row["error_category"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                observed_at=str(row["observed_at"]),
            )
            for row in rows
        ]
        return _aggregate(runtime_id, capability, observations)


def _validate(observation: DelegateObservation) -> None:
    if not observation.runtime_id.strip():
        raise ValueError("runtime_id must not be empty")
    if observation.latency_ms < 0:
        raise ValueError("latency_ms must not be negative")
    if observation.quality is not None and not 0 <= observation.quality <= 1:
        raise ValueError("quality must be between 0 and 1")
    if observation.cost_usd is not None and observation.cost_usd < 0:
        raise ValueError("cost_usd must not be negative")


def _aggregate(
    runtime_id: str,
    capability: str,
    rows: list[DelegateObservation],
) -> Effectiveness:
    samples = len(rows)
    successes = sum(row.success for row in rows)
    # Beta(2, 2) prior prevents one lucky execution from ranking as perfect.
    success_rate = (successes + 2) / (samples + 4)
    mean_latency = sum(row.latency_ms for row in rows) / samples if samples else 0.0
    qualities = [row.quality for row in rows if row.quality is not None]
    mean_quality = sum(qualities) / len(qualities) if qualities else 0.5
    total_cost = sum(row.cost_usd or 0.0 for row in rows)
    return Effectiveness(
        runtime_id,
        capability,
        samples,
        successes,
        success_rate,
        mean_latency,
        mean_quality,
        total_cost,
    )


_MEMORY_STORE = InMemoryDelegateHealthStore()
_SQLITE_STORE = SqliteDelegateHealthStore()


def get_delegate_health_store() -> DelegateHealthStore:
    return _SQLITE_STORE if sqlite_store.is_bound() else _MEMORY_STORE
