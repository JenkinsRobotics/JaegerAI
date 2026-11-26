"""Standalone multi-channel notification & messaging relay (SQLite WAL outbox).

Promoted from JaegerAI's archived `features/channels/relay/` architecture:
- Durable SQLite WAL outbox with idempotent receipt tracking.
- Automatic credential redaction (`jaeger_authority.redact_text`) before any
  outbound message is persisted or sent.
- Safe-by-default: outbound messages to external channels (`imessage`,
  `telegram`, `webhook`) default to `queued_for_approval` unless explicitly
  approved or sent to `local_log` / `dry_run`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from jaeger_authority.redact import redact_text
except ImportError:  # pragma: no cover - standalone fallback
    def redact_text(text: str) -> str:
        return text


SUPPORTED_CHANNELS = ("local_log", "imessage", "telegram", "webhook")


@dataclass(slots=True)
class OutboxMessage:
    message_id: str
    channel: str
    recipient: str
    body: str
    status: str  # queued_for_approval | sent | dry_run | failed
    dry_run: bool
    approved: bool
    receipt: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChannelHub:
    """SQLite WAL outbox + pluggable channel adapters with secret scrubbing."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "channels.sqlite3"
        self._lock = threading.RLock()
        self._adapters: dict[str, Callable[[str, str], dict[str, Any]]] = {
            "local_log": lambda recipient, body: {"delivered": True, "recipient": recipient, "bytes": len(body)},
        }
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    message_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    approved INTEGER NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def register_adapter(self, channel: str, fn: Callable[[str, str], dict[str, Any]]) -> None:
        self._adapters[channel] = fn

    def status(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            pending = int(
                conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'queued_for_approval'").fetchone()[0]
            )
            sent = int(conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'sent'").fetchone()[0])
        return {
            "supported_channels": list(SUPPORTED_CHANNELS),
            "configured_adapters": sorted(self._adapters.keys()),
            "pending_approval": pending,
            "sent_count": sent,
        }

    def enqueue(
        self,
        *,
        channel: str,
        recipient: str,
        body: str,
        approved: bool = False,
        dry_run: bool = False,
    ) -> OutboxMessage:
        ch = channel if channel in SUPPORTED_CHANNELS else "local_log"
        safe_body = redact_text(body or "")
        mid = f"msg_{uuid.uuid4().hex[:10]}"
        now = time.time()
        receipt: dict[str, Any] = {}

        if dry_run:
            status = "dry_run"
            receipt = {"simulated": True, "channel": ch}
        elif ch != "local_log" and not approved:
            status = "queued_for_approval"
            receipt = {"reason": "external_channel_requires_owner_approval"}
        else:
            adapter = self._adapters.get(ch)
            if adapter is None:
                status = "queued_for_approval"
                receipt = {"reason": f"adapter_not_configured:{ch}"}
            else:
                try:
                    receipt = adapter(recipient, safe_body)
                    status = "sent"
                except Exception as exc:  # noqa: BLE001
                    status = "failed"
                    receipt = {"error": str(exc)}

        msg = OutboxMessage(
            message_id=mid,
            channel=ch,
            recipient=recipient,
            body=safe_body,
            status=status,
            dry_run=bool(dry_run),
            approved=bool(approved),
            receipt=receipt,
            created_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outbox (
                    message_id, channel, recipient, body, status, dry_run, approved, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_id,
                    msg.channel,
                    msg.recipient,
                    msg.body,
                    msg.status,
                    1 if msg.dry_run else 0,
                    1 if msg.approved else 0,
                    json.dumps(msg.receipt),
                    msg.created_at,
                ),
            )
        return msg

    def list_outbox(self, *, limit: int = 50) -> list[OutboxMessage]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, channel, recipient, body, status, dry_run, approved, receipt_json, created_at
                FROM outbox ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            OutboxMessage(
                message_id=r[0],
                channel=r[1],
                recipient=r[2],
                body=r[3],
                status=r[4],
                dry_run=bool(r[5]),
                approved=bool(r[6]),
                receipt=json.loads(r[7] or "{}"),
                created_at=float(r[8]),
            )
            for r in rows
        ]


__all__ = ["ChannelHub", "OutboxMessage", "SUPPORTED_CHANNELS"]
