"""Lead → specialist handoff stub (agents-as-tools).

This is intentionally a stub: it records a handoff, optionally waits on the
existing Gateway approval path, and returns a structured result the lead can
narrate. It does **not** claim a live multi-agent turn until that is proven.
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
    status: str  # pending_approval | approved | denied | stub_complete
    require_approval: bool = True
    approval_id: str | None = None
    created_at: float = field(default_factory=time.time)
    result_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandoffStub:
    """In-memory handoff ledger shared with Gateway approvals when wired."""

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
        status = "pending_approval" if require_approval else "stub_complete"
        summary = None
        if not require_approval:
            summary = (
                f"Stub handoff to {to_agent_id}: recorded task without live "
                "multi-agent turn (product sprint stub)."
            )
        record = HandoffRecord(
            id=handoff_id,
            from_agent_id=from_agent_id or "native:jaeger",
            to_agent_id=to_agent_id,
            task=(task or "").strip(),
            status=status,
            require_approval=require_approval,
            approval_id=approval_id,
            result_summary=summary,
            metadata=dict(metadata or {}),
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
                    record.result_summary = (
                        f"Approved stub handoff to {record.to_agent_id} — "
                        "no live specialist turn yet (honest stub)."
                    )
                else:
                    record.result_summary = "Handoff denied by operator."
                return record
        return None

    def list_records(self) -> list[HandoffRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)


_DEFAULT_HANDOFF = HandoffStub()


def get_handoff_stub() -> HandoffStub:
    return _DEFAULT_HANDOFF
