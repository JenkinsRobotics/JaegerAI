"""Evolving SQLite WAL World Model & Temporal Awareness Store.

Tracks the live state of Jaeger's world across restarts:
- Multimodal perception beliefs (room/camera/mic presence, owner availability)
- Temporal awareness (time-of-day windows, upcoming deadlines, elapsed idle time)
- Business & pipeline state (YouTube episodes, pending approvals, tasks)
- Embodiment state (VR avatar mood/activity, Minecraft coordinates/inventory, JP01 hardware)

Conversation is strictly an interface to this evolving mind — not its execution loop.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class WorldFact:
    domain: str  # "perception" | "temporal" | "business" | "embodiment" | "owner" | "system"
    key: str
    value: Any
    confidence: float = 1.0
    source: str = "system"
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PerceptionEvent:
    event_id: str
    modality: str  # "audio" | "vision" | "temporal" | "minecraft" | "hardware" | "channel" | "owner"
    kind: str
    payload: dict[str, Any]
    salience: float = 0.5
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "modality": self.modality,
            "kind": self.kind,
            "payload": dict(self.payload),
            "salience": self.salience,
            "timestamp": self.timestamp,
        }


class WorldModelStore:
    """Durable SQLite WAL evolving world model + salience-scored perception journal."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "world_model.sqlite3"
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
                CREATE TABLE IF NOT EXISTS world_state (
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'system',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (domain, key)
                );

                CREATE TABLE IF NOT EXISTS perception_log (
                    event_id TEXT PRIMARY KEY,
                    modality TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    salience REAL NOT NULL DEFAULT 0.5,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_perception_ts ON perception_log(timestamp DESC);
                """
            )

    def observe(
        self,
        *,
        domain: str,
        key: str,
        value: Any,
        confidence: float = 1.0,
        source: str = "system",
    ) -> WorldFact:
        now = time.time()
        conf = max(0.0, min(1.0, float(confidence)))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO world_state (domain, key, value_json, confidence, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (domain, key, json.dumps(value, default=str), conf, source, now),
            )
        return WorldFact(domain=domain, key=key, value=value, confidence=conf, source=source, updated_at=now)

    def get(self, domain: str, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM world_state WHERE domain = ? AND key = ?",
                (domain, key),
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def snapshot(self, *, domain: str | None = None) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            if domain:
                rows = conn.execute(
                    "SELECT domain, key, value_json, confidence, source, updated_at FROM world_state WHERE domain = ? ORDER BY updated_at DESC",
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT domain, key, value_json, confidence, source, updated_at FROM world_state ORDER BY domain, key"
                ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for dom, k, vjson, conf, src, ts in rows:
            grouped.setdefault(dom, {})[k] = {
                "value": json.loads(vjson),
                "confidence": float(conf),
                "source": src,
                "updated_at": float(ts),
            }
        now_utc = datetime.now(timezone.utc)
        return {
            "timestamp": time.time(),
            "iso_utc": now_utc.isoformat(),
            "domains": grouped,
        }

    def record_perception(
        self,
        *,
        modality: str,
        kind: str,
        payload: Mapping[str, Any],
        salience: float = 0.5,
        max_retained: int = 2000,
    ) -> PerceptionEvent:
        eid = f"perc_{uuid.uuid4().hex[:12]}"
        now = time.time()
        sal = max(0.0, min(1.0, float(salience)))
        clean_payload = dict(payload)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO perception_log (event_id, modality, kind, payload_json, salience, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (eid, modality, kind, json.dumps(clean_payload, default=str), sal, now),
            )
            # Rolling cap so 24/7 perception never balloons disk or RAM on 32 GB hosts
            conn.execute(
                """
                DELETE FROM perception_log
                WHERE event_id NOT IN (
                    SELECT event_id FROM perception_log ORDER BY timestamp DESC LIMIT ?
                )
                """,
                (max(100, int(max_retained)),),
            )
        return PerceptionEvent(
            event_id=eid,
            modality=modality,
            kind=kind,
            payload=clean_payload,
            salience=sal,
            timestamp=now,
        )

    def recent_perceptions(self, *, limit: int = 30, modality: str | None = None) -> list[PerceptionEvent]:
        with self._lock, self._connect() as conn:
            if modality:
                rows = conn.execute(
                    "SELECT event_id, modality, kind, payload_json, salience, timestamp FROM perception_log WHERE modality = ? ORDER BY timestamp DESC LIMIT ?",
                    (modality, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event_id, modality, kind, payload_json, salience, timestamp FROM perception_log ORDER BY timestamp DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [
            PerceptionEvent(
                event_id=r[0],
                modality=r[1],
                kind=r[2],
                payload=json.loads(r[3] or "{}"),
                salience=float(r[4]),
                timestamp=float(r[5]),
            )
            for r in rows
        ]


__all__ = ["PerceptionEvent", "WorldFact", "WorldModelStore"]
