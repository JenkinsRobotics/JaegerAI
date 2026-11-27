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
    from jaeger_authority.redact import redact_object, redact_text
except ImportError:  # pragma: no cover - standalone fallback
    def redact_text(text: str) -> str:
        return text

    def redact_object(value: Any, *, _depth: int = 0) -> Any:
        return value


SUPPORTED_CHANNELS = ("local_log", "imessage", "telegram", "webhook")

_OUTBOX_COLS = (
    "message_id, channel, recipient, body, status, dry_run, approved, receipt_json, created_at"
)


@dataclass(slots=True)
class OutboxMessage:
    message_id: str
    channel: str
    recipient: str
    body: str
    status: str  # queued_for_approval | sending | sent | delivery_unknown | dry_run
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

    @staticmethod
    def _row_to_message(r: tuple) -> OutboxMessage:
        return OutboxMessage(
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

    def get_message(self, message_id: str) -> OutboxMessage | None:
        """Return the persisted outbox row for ``message_id`` (or None)."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {_OUTBOX_COLS} FROM outbox WHERE message_id = ?", (message_id,)
            ).fetchone()
        return self._row_to_message(row) if row else None

    def _persist(self, conn: sqlite3.Connection, msg: OutboxMessage) -> None:
        conn.execute(
            """
            UPDATE outbox SET status = ?, approved = ?, receipt_json = ?
            WHERE message_id = ?
            """,
            (msg.status, 1 if msg.approved else 0, json.dumps(msg.receipt), msg.message_id),
        )

    @staticmethod
    def _confirmed_delivery(receipt: Any) -> bool:
        """True only for an explicit boolean delivered/ok confirmation.

        ``sent`` requires a dict receipt with ``delivered: true`` or legacy
        ``ok: true``; an explicit ``false`` on either key, a missing key, or
        any non-dict outcome is ambiguous and must never be treated as sent.
        """
        if not isinstance(receipt, dict):
            return False
        delivered = receipt.get("delivered")
        ok = receipt.get("ok")
        if delivered is False or ok is False:
            return False
        return delivered is True or ok is True

    def _deliver(self, msg: OutboxMessage) -> OutboxMessage:
        """Persist-before-delivery for an approved, adapter-backed message.

        Claims the row exactly once (sending/approved) under BEGIN IMMEDIATE,
        invokes the adapter outside the lock, then persists the terminal
        status: ``sent`` + scrubbed receipt only on an explicit confirmed
        delivery, ``delivery_unknown`` on exception or any ambiguous outcome
        (never auto-retried).
        """
        adapter = self._adapters.get(msg.channel)
        if adapter is None:
            # No adapter: leave queued_for_approval with no side effect.
            return msg
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_OUTBOX_COLS} FROM outbox WHERE message_id = ?", (msg.message_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"unknown message_id: {msg.message_id}")
            current = self._row_to_message(row)
            if current.status != "queued_for_approval":
                # Already claimed/finished (repeated or concurrent approval,
                # including reopening while in flight): no second adapter call.
                conn.rollback()
                return current
            claimed = OutboxMessage(
                message_id=current.message_id,
                channel=current.channel,
                recipient=current.recipient,
                body=current.body,
                status="sending",
                dry_run=current.dry_run,
                approved=True,
                receipt=current.receipt,
                created_at=current.created_at,
            )
            self._persist(conn, claimed)
            conn.commit()
        try:
            receipt = adapter(msg.recipient, msg.body)
            if self._confirmed_delivery(receipt):
                final = OutboxMessage(
                    message_id=msg.message_id,
                    channel=msg.channel,
                    recipient=msg.recipient,
                    body=msg.body,
                    status="sent",
                    dry_run=msg.dry_run,
                    approved=True,
                    receipt=redact_object(receipt),
                    created_at=msg.created_at,
                )
            else:
                # Ambiguous outcome (non-dict, missing key, or explicit false):
                # fail closed, never auto-retry this message_id.
                final = OutboxMessage(
                    message_id=msg.message_id,
                    channel=msg.channel,
                    recipient=msg.recipient,
                    body=msg.body,
                    status="delivery_unknown",
                    dry_run=msg.dry_run,
                    approved=True,
                    receipt={"error": "ambiguous adapter outcome"},
                    created_at=msg.created_at,
                )
        except Exception:  # noqa: BLE001 - ambiguous outcomes fail closed
            # Never persist raw exception strings: they may embed secrets.
            final = OutboxMessage(
                message_id=msg.message_id,
                channel=msg.channel,
                recipient=msg.recipient,
                body=msg.body,
                status="delivery_unknown",
                dry_run=msg.dry_run,
                approved=True,
                receipt={"error": "adapter raised an exception"},
                created_at=msg.created_at,
            )
        with self._lock, self._connect() as conn:
            self._persist(conn, final)
        return final

    def approve_delivery(self, message_id: str) -> OutboxMessage:
        """Trusted Gateway owner callback: deliver a queued_for_approval row.

        Atomically claims the row exactly once; repeated or concurrent calls
        return the existing record without a second adapter invocation.
        """
        msg = self.get_message(message_id)
        if msg is None:
            raise KeyError(f"unknown message_id: {message_id}")
        if msg.status != "queued_for_approval":
            return msg
        if msg.dry_run:
            return msg
        return self._deliver(msg)

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

    def recover_interrupted_deliveries(self) -> int:
        """Settle every interrupted send at Gateway startup without replay."""
        receipt = json.dumps({"reason": "interrupted_at_startup"})
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "UPDATE outbox SET status = 'delivery_unknown', receipt_json = ? WHERE status = 'sending'",
                (receipt,),
            )
            return result.rowcount

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
            status = "queued_for_approval"
            receipt = {"reason": f"adapter_not_configured:{ch}"}

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
        if not dry_run and status == "queued_for_approval" and (ch == "local_log" or approved):
            # Approved direct enqueue and local_log go through the same
            # persist-before-delivery path (claim -> adapter -> terminal status).
            msg = self._deliver(msg)
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
        return [self._row_to_message(r) for r in rows]


__all__ = ["ChannelHub", "OutboxMessage", "SUPPORTED_CHANNELS"]
