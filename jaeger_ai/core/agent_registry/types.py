"""Agent identity kinds for the Grok-Bot product shape.

One persistent face (Mac app / WebUI / CLI via gateway) with agents underneath:
Jaeger-native agents created by this framework, plus third-party agents reached
through adapters (Hermes, OpenClaw, Roundtable, …).

Fees/features MUST add capability — never gate fundamentals. The
``fundamentals_gated`` field exists only so callers can assert the invariant;
create/list paths always force it False.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AgentKind(str, Enum):
    """Support model exposed to gateway clients and WebUI."""

    NATIVE = "jaeger_native"
    THIRD_PARTY = "third_party"


# Stable ids for built-in third-party faces (Hermes WebUI profile adapters).
BUILTIN_THIRD_PARTY: tuple[dict[str, Any], ...] = (
    {
        "id": "tp:hermes",
        "name": "hermes",
        "display_name": "Hermes Agent",
        "adapter": "hermes",
        "profile_id": "default",
        "endpoint": None,
        "port": None,
    },
    {
        "id": "tp:openclaw",
        "name": "openclaw",
        "display_name": "OpenClaw",
        "adapter": "openclaw",
        "profile_id": "openclaw",
        "endpoint": "http://127.0.0.1:8644",
        "port": 8644,
    },
    {
        "id": "tp:roundtable",
        "name": "roundtable",
        "display_name": "Roundtable",
        "adapter": "roundtable",
        "profile_id": "roundtable",
        "endpoint": "http://127.0.0.1:8643",
        "port": 8643,
    },
)


@dataclass(slots=True)
class AgentRecord:
    """Serializable agent catalog entry (native or third-party)."""

    id: str
    name: str
    kind: AgentKind
    display_name: str
    source: str  # instance | adapter | registry
    active: bool = False
    switchable: bool = True
    fundamentals_gated: bool = False
    instance_name: str | None = None
    instance_path: str | None = None
    adapter: str | None = None
    profile_id: str | None = None
    endpoint: str | None = None
    port: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["kind"] = self.kind.value
        # Invariant: fundamentals are never fee/feature gated.
        raw["fundamentals_gated"] = False
        raw["switchable"] = True if self.switchable or not self.fundamentals_gated else self.switchable
        raw["switchable"] = True
        raw["fundamentals_gated"] = False
        return raw

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRecord:
        kind_raw = data.get("kind") or AgentKind.NATIVE.value
        try:
            kind = AgentKind(str(kind_raw))
        except ValueError:
            kind = AgentKind.NATIVE
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            kind=kind,
            display_name=str(data.get("display_name") or data.get("name") or data["id"]),
            source=str(data.get("source") or "registry"),
            active=bool(data.get("active", False)),
            switchable=True,  # never honor a fee lock from persisted state
            fundamentals_gated=False,
            instance_name=(str(data["instance_name"]) if data.get("instance_name") else None),
            instance_path=(str(data["instance_path"]) if data.get("instance_path") else None),
            adapter=(str(data["adapter"]) if data.get("adapter") else None),
            profile_id=(str(data["profile_id"]) if data.get("profile_id") else None),
            endpoint=(str(data["endpoint"]) if data.get("endpoint") else None),
            port=(int(data["port"]) if data.get("port") is not None else None),
            metadata=dict(data.get("metadata") or {}),
        )


# Explicit type aliases for the support model (documentation + isinstance).
JaegerNativeAgent = AgentRecord
ThirdPartyAgent = AgentRecord


def is_native(record: AgentRecord) -> bool:
    return record.kind is AgentKind.NATIVE


def is_third_party(record: AgentRecord) -> bool:
    return record.kind is AgentKind.THIRD_PARTY
