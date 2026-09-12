"""Lead → specialist handoff records.

Durable rows live in the gateway session store. This module keeps the
record shape and a small in-memory helper for tests that do not open a
store. Live execution is performed by the gateway using the native
specialist runtime — registration or an in-memory row is not success.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class HandoffRecord:
    id: str
    from_agent_id: str
    to_agent_id: str
    task: str
    status: str
    require_approval: bool = True
    approval_id: str | None = None
    created_at: float = field(default_factory=time.time)
    result_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    parent_run_id: str | None = None
    child_run_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result_summary"] = self.result_summary or (self.result or {}).get("summary")
        return payload

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> HandoffRecord:
        return cls(
            id=row["id"],
            from_agent_id=row["from_agent_id"],
            to_agent_id=row["to_agent_id"],
            task=row["task"],
            status=row["status"],
            require_approval=bool(row.get("require_approval")),
            approval_id=row.get("approval_id"),
            created_at=float(row.get("created_at") or time.time()),
            result_summary=(row.get("result") or {}).get("summary") or row.get("result_summary"),
            metadata=dict(row.get("metadata") or {}),
            request_id=row.get("request_id"),
            parent_run_id=row.get("parent_run_id"),
            child_run_id=row.get("child_run_id"),
            result=dict(row.get("result") or {}),
        )


class HandoffStub:
    """In-memory fallback used only when no session store is available."""

    def __init__(self) -> None:
        self._records: dict[str, HandoffRecord] = {}

    def create(
        self,
        *,
        from_agent_id: str,
        to_agent_id: str,
        task: str,
        require_approval: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> HandoffRecord:
        handoff_id = f"handoff_{uuid.uuid4().hex[:12]}"
        approval_id = f"approval_{uuid.uuid4().hex[:12]}" if require_approval else None
        status = "pending_approval" if require_approval else "admitted"
        record = HandoffRecord(
            id=handoff_id,
            from_agent_id=from_agent_id or "native:jaeger",
            to_agent_id=to_agent_id,
            task=(task or "").strip(),
            status=status,
            require_approval=require_approval,
            approval_id=approval_id,
            metadata=dict(metadata or {}),
            request_id=handoff_id,
        )
        self._records[handoff_id] = record
        return record

    def get(self, handoff_id: str) -> HandoffRecord | None:
        return self._records.get(handoff_id)

    def resolve_approval(self, approval_id: str, *, approved: bool) -> HandoffRecord | None:
        for record in self._records.values():
            if record.approval_id == approval_id and record.status == "pending_approval":
                record.status = "approved" if approved else "denied"
                if approved:
                    record.result_summary = f"Approved handoff to {record.to_agent_id}"
                else:
                    record.result_summary = "Handoff denied by operator."
                    record.result = {"ok": False, "status": "denied"}
                return record
        return None

    def list_records(self) -> list[HandoffRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)


_DEFAULT_HANDOFF = HandoffStub()


def get_handoff_stub() -> HandoffStub:
    return _DEFAULT_HANDOFF
