"""Pure, versioned, JSON-serializable wire envelopes and operation classes.

Unlike local Python SPI types (which may reference ``pathlib.Path`` or local
sync callbacks), everything in ``wire.py`` is strictly serializable, carries
an explicit schema version, and has zero implicit wall-clock, UUID, or cwd
side effects — suitable for durable logs and future remote/multi-node transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

WIRE_SCHEMA_VERSION = "1.0"


class OperationClass(str, Enum):
    """Retry-safety classification enforced across all reliability boundaries."""

    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT_MUTATION = "non_idempotent_mutation"

    @property
    def retry_allowed(self) -> bool:
        """Fail closed: only read-only or explicitly idempotent ops may retry."""
        return self in (OperationClass.READ_ONLY, OperationClass.IDEMPOTENT_WRITE)


@dataclass(frozen=True)
class WireEnvelope:
    """Versioned, transport-neutral durable event or command envelope."""

    envelope_id: str
    event_type: str
    session_id: str
    seq: int
    timestamp_ms: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = WIRE_SCHEMA_VERSION
    trace_id: str = ""
    idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "seq": self.seq,
            "timestamp_ms": self.timestamp_ms,
            "trace_id": self.trace_id,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "WireEnvelope":
        return cls(
            schema_version=str(raw.get("schema_version") or WIRE_SCHEMA_VERSION),
            envelope_id=str(raw["envelope_id"]),
            event_type=str(raw["event_type"]),
            session_id=str(raw["session_id"]),
            seq=int(raw["seq"]),
            timestamp_ms=int(raw["timestamp_ms"]),
            trace_id=str(raw.get("trace_id") or ""),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            payload=dict(raw.get("payload") or {}),
        )


@dataclass(frozen=True)
class WireActionReceipt:
    """Durable, versioned receipt for an external or local action outcome."""

    receipt_id: str
    tool_name: str
    operation_class: OperationClass
    outcome: str  # "completed" | "failed" | "denied" | "outcome_unknown"
    timestamp_ms: int
    schema_version: str = WIRE_SCHEMA_VERSION
    idempotency_key: str = ""
    error: str | None = None

    @property
    def safe_to_retry(self) -> bool:
        if self.outcome == "outcome_unknown":
            return self.operation_class.retry_allowed
        return self.operation_class.retry_allowed and self.outcome == "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "tool_name": self.tool_name,
            "operation_class": self.operation_class.value,
            "outcome": self.outcome,
            "timestamp_ms": self.timestamp_ms,
            "idempotency_key": self.idempotency_key,
            "error": self.error,
        }
