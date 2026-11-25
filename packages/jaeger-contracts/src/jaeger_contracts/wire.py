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


# ── Unified Transport Frame Vocabulary (AG2 LocalLink / WsLink pattern) ─────


@dataclass(frozen=True)
class HelloFrame:
    """Client handshake carrying the last contiguous sequence seen for replay."""

    client_id: str
    session_id: str = ""
    since_seq: int = 0
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "hello"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "client_id": self.client_id,
            "session_id": self.session_id,
            "since_seq": self.since_seq,
        }


@dataclass(frozen=True)
class WelcomeFrame:
    """Server handshake acknowledging protocol version and current high-water seq."""

    server_id: str
    session_id: str = ""
    head_seq: int = 0
    replayed_count: int = 0
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "welcome"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "server_id": self.server_id,
            "session_id": self.session_id,
            "head_seq": self.head_seq,
            "replayed_count": self.replayed_count,
        }


@dataclass(frozen=True)
class RequestFrame:
    """Control-plane RPC request frame."""

    request_id: str
    method: str
    params: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "request"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "method": self.method,
            "params": dict(self.params),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class ResponseFrame:
    """Control-plane RPC response frame."""

    request_id: str
    ok: bool
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "response"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "ok": self.ok,
            "result": dict(self.result),
            "error": self.error,
        }


@dataclass(frozen=True)
class NotifyFrame:
    """Data-plane push notification wrapping a sequenced WireEnvelope."""

    envelope: WireEnvelope
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "notify"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "envelope": self.envelope.to_dict(),
        }


@dataclass(frozen=True)
class ReceiptFrame:
    """Client acknowledgement of a received data-plane envelope seq."""

    envelope_id: str
    session_id: str
    seq: int
    schema_version: str = WIRE_SCHEMA_VERSION
    frame_type: str = "receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_type": self.frame_type,
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "session_id": self.session_id,
            "seq": self.seq,
        }


WireFrame = HelloFrame | WelcomeFrame | RequestFrame | ResponseFrame | NotifyFrame | ReceiptFrame


def parse_wire_frame(raw: Mapping[str, Any]) -> WireFrame:
    """Deserialize any supported transport frame; fails closed on unknown types."""
    ftype = str(raw.get("frame_type") or "").strip().lower()
    ver = str(raw.get("schema_version") or WIRE_SCHEMA_VERSION)
    if ftype == "hello":
        return HelloFrame(
            client_id=str(raw["client_id"]),
            session_id=str(raw.get("session_id") or ""),
            since_seq=int(raw.get("since_seq") or 0),
            schema_version=ver,
        )
    if ftype == "welcome":
        return WelcomeFrame(
            server_id=str(raw["server_id"]),
            session_id=str(raw.get("session_id") or ""),
            head_seq=int(raw.get("head_seq") or 0),
            replayed_count=int(raw.get("replayed_count") or 0),
            schema_version=ver,
        )
    if ftype == "request":
        return RequestFrame(
            request_id=str(raw["request_id"]),
            method=str(raw["method"]),
            params=dict(raw.get("params") or {}),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            schema_version=ver,
        )
    if ftype == "response":
        return ResponseFrame(
            request_id=str(raw["request_id"]),
            ok=bool(raw["ok"]),
            result=dict(raw.get("result") or {}),
            error=str(raw["error"]) if raw.get("error") is not None else None,
            schema_version=ver,
        )
    if ftype == "notify":
        return NotifyFrame(
            envelope=WireEnvelope.from_dict(raw["envelope"]),
            schema_version=ver,
        )
    if ftype == "receipt":
        return ReceiptFrame(
            envelope_id=str(raw["envelope_id"]),
            session_id=str(raw["session_id"]),
            seq=int(raw["seq"]),
            schema_version=ver,
        )
    raise ValueError(f"Unknown wire frame_type: {ftype!r}")
