"""Persistent Entity Identity for Jaeger (Pinocchio Architecture).

Core Invariant:
    MODEL ≠ AGENT
    PERSONA ≠ IDENTITY
    SESSION ≠ IDENTITY

The entity identity is the unique, persistent anchor of the agent instance.
It does not change when:
- The cognitive model/provider changes (Hermes -> Claude -> Ollama)
- A persona preset or tone slider changes
- A new conversation/session starts
- The process restarts or crashes
- A subagent is spawned
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
import time
from typing import Any
import uuid

from jaeger_ai.core.instance.instance import operator_state_root

logger = logging.getLogger("jaeger.entity.identity")

IDENTITY_FILE_NAME = "entity_identity.json"


@dataclass(frozen=True)
class EntityIdentity:
    """The stable, environment- and model-agnostic identity of the agent entity."""

    entity_id: str
    display_name: str
    created_at: float
    instance_name: str
    system_role: str = (
        "Persistent cognitive assistant entity. Operates with continuous memory, "
        "environmental perception, structured world knowledge, and safety-verified execution."
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntityIdentity:
        required = ("entity_id", "display_name", "created_at", "instance_name")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"EntityIdentity missing required field(s): {', '.join(missing)}")
        return cls(
            entity_id=str(data["entity_id"]).strip(),
            display_name=str(data["display_name"]).strip(),
            created_at=float(data["created_at"]),
            instance_name=str(data["instance_name"]).strip(),
            system_role=str(data.get("system_role", "")).strip() or cls.system_role,
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def create_default(
        cls,
        instance_name: str = "default",
        display_name: str = "Jaeger",
    ) -> EntityIdentity:
        return cls(
            entity_id=f"jaeger-entity-{uuid.uuid4().hex[:12]}",
            display_name=display_name,
            created_at=time.time(),
            instance_name=instance_name,
        )

    def save_to_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load_from_file(cls, path: Path) -> EntityIdentity:
        if not path.is_file():
            raise FileNotFoundError(f"Identity file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Identity file at {path} must contain a JSON object")
        return cls.from_dict(data)


def resolve_entity_identity(
    state_root: Path | str | None = None,
    default_name: str = "Jaeger",
    instance_name: str = "default",
) -> EntityIdentity:
    """Resolve or mint the persistent entity identity under the state root.

    Loads from `<state_root>/entity_identity.json`. If none exists, creates a
    new stable identity record and persists it before returning.
    """
    root = Path(state_root) if state_root else operator_state_root()
    root.mkdir(parents=True, exist_ok=True)
    identity_path = root / IDENTITY_FILE_NAME

    if identity_path.is_file():
        try:
            return EntityIdentity.load_from_file(identity_path)
        except Exception as exc:
            logger.warning("Corrupt or invalid entity identity file at %s: %s; re-minting", identity_path, exc)

    if instance_name == "default":
        instance_name = (os.environ.get("JAEGER_INSTANCE_NAME") or "").strip() or "default"
    new_id = f"jaeger-entity-{uuid.uuid4().hex[:12]}"
    identity = EntityIdentity(
        entity_id=new_id,
        display_name=default_name,
        created_at=time.time(),
        instance_name=instance_name,
    )
    identity.save_to_file(identity_path)
    logger.info("Minted new persistent entity identity %s at %s", new_id, identity_path)
    return identity
