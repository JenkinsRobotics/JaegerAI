"""Capability package manifest definitions (Workstream 10).

Differentiates:
1. Lightweight procedural skill: Human/agent instructions (e.g. markdown playbooks, guidelines).
2. Executable capability: Programmable package containing entrypoints, permissions, tools, verification, and rollback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal
import yaml


CapabilityCategory = Literal[
    "script",
    "skill",
    "integration",
    "workflow",
    "tool_adapter",
    "device_adapter",
    "domain_module",
    "context_strategy",
]


@dataclass(frozen=True)
class CapabilityManifest:
    """Canonical specification for a programmable capability package."""
    capability_id: str
    name: str
    version: str = "1.0.0"
    category: CapabilityCategory = "tool_adapter"
    description: str = ""
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    execution_entrypoint: str = "executor.py:run"
    verification_entrypoint: str | None = None
    rollback_entrypoint: str | None = None
    provenance: str = "operator_installed"
    is_executable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "permissions": list(self.permissions),
            "dependencies": list(self.dependencies),
            "tools": list(self.tools),
            "triggers": list(self.triggers),
            "preconditions": list(self.preconditions),
            "execution_entrypoint": self.execution_entrypoint,
            "verification_entrypoint": self.verification_entrypoint,
            "rollback_entrypoint": self.rollback_entrypoint,
            "provenance": self.provenance,
            "is_executable": self.is_executable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityManifest:
        return cls(
            capability_id=str(data["capability_id"]).strip(),
            name=str(data["name"]).strip(),
            version=str(data.get("version", "1.0.0")).strip(),
            category=data.get("category", "tool_adapter"),
            description=str(data.get("description", "")).strip(),
            permissions=tuple(data.get("permissions", ())),
            dependencies=tuple(data.get("dependencies", ())),
            tools=tuple(data.get("tools", ())),
            triggers=tuple(data.get("triggers", ())),
            preconditions=tuple(data.get("preconditions", ())),
            execution_entrypoint=str(data.get("execution_entrypoint", "executor.py:run")),
            verification_entrypoint=data.get("verification_entrypoint"),
            rollback_entrypoint=data.get("rollback_entrypoint"),
            provenance=str(data.get("provenance", "operator_installed")),
            is_executable=bool(data.get("is_executable", True)),
        )

    @classmethod
    def load(cls, path: Path | str) -> CapabilityManifest:
        p = Path(path)
        if not p.is_file():
            p = p / "manifest.yaml"
            if not p.is_file():
                p = p.with_name("manifest.json")
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    def save(self, path: Path | str) -> None:
        p = Path(path)
        if p.is_dir():
            p = p / "manifest.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix in (".yaml", ".yml"):
            p.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False), encoding="utf-8")
        else:
            p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
