"""AgentRegistry — create/list/switch native + third-party agents.

Persistence lives under operator state (``~/.jaeger/agents/`` or
``$JAEGER_STATE_DIR/agents/``), never in the repo tree.

Discovery:
  * Native agents: directories under ``instances/`` plus registry creates.
  * Third-party agents: built-in Hermes/OpenClaw/Roundtable faces plus
    any ``register_third_party`` entries.

Gateway and WebUI both consume :meth:`list_agents` / :meth:`to_catalog` so
Mac app and remote WebUI see the same support model.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from jaeger_ai.core.agent_registry.types import (
    BUILTIN_THIRD_PARTY,
    AgentKind,
    AgentRecord,
    AgentRole,
    default_role_for,
    is_native,
    is_third_party,
    normalize_agent_role,
)

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _state_root() -> Path:
    from jaeger_ai.core.instance.instance import operator_state_root

    return operator_state_root()


def default_registry_path(root: Path | None = None) -> Path:
    base = (root or _state_root()).expanduser().resolve()
    return base / "agents" / "registry.json"


class AgentRegistry:
    """Catalog of JaegerNativeAgent + ThirdPartyAgent records."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or _state_root()).expanduser().resolve()
        self.path = default_registry_path(self.root)
        self._data: dict[str, Any] = {"version": 1, "active_id": None, "agents": {}}
        self._load()

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        agents: dict[str, Any] = {}
        for key, value in (raw.get("agents") or {}).items():
            if isinstance(value, dict):
                # Strip any persisted fee gate — fundamentals stay open.
                value = dict(value)
                value["fundamentals_gated"] = False
                value["switchable"] = True
                agents[str(key)] = value
        self._data = {
            "version": int(raw.get("version") or 1),
            "active_id": raw.get("active_id"),
            "agents": agents,
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(self._data, indent=2, sort_keys=True) + "\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    # ── discovery ─────────────────────────────────────────────────

    def _instances_root(self) -> Path:
        return self.root / "instances"

    def _discover_native(self) -> list[AgentRecord]:
        records: list[AgentRecord] = []
        root = self._instances_root()
        if not root.is_dir():
            return records
        active_name = self._sticky_instance_name()
        for path in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            agent_id = f"native:{path.name}"
            display = path.name
            identity = path / "identity.yaml"
            if identity.is_file():
                try:
                    text = identity.read_text(encoding="utf-8")
                    for line in text.splitlines():
                        key, _, value = line.partition(":")
                        if key.strip() in {"name", "agent_name", "display_name"} and value.strip():
                            display = value.strip().strip("\"'")
                            break
                except OSError:
                    pass
            records.append(
                AgentRecord(
                    id=agent_id,
                    name=path.name,
                    kind=AgentKind.NATIVE,
                    display_name=display,
                    source="instance",
                    role=default_role_for(
                        kind=AgentKind.NATIVE, name=path.name, agent_id=agent_id
                    ),
                    active=(path.name == active_name),
                    instance_name=path.name,
                    instance_path=str(path),
                    profile_id="jaeger",
                    metadata={"framework": "jaeger"},
                )
            )
        return records

    def _sticky_instance_name(self) -> str | None:
        path = self.root / "active_instance"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _builtin_third_party(self) -> list[AgentRecord]:
        active_id = self._data.get("active_id")
        out: list[AgentRecord] = []
        for item in BUILTIN_THIRD_PARTY:
            agent_id = str(item["id"])
            out.append(
                AgentRecord(
                    id=agent_id,
                    name=str(item["name"]),
                    kind=AgentKind.THIRD_PARTY,
                    display_name=str(item["display_name"]),
                    source="adapter",
                    role=AgentRole.SPECIALIST,
                    active=(active_id == agent_id),
                    adapter=str(item.get("adapter") or item["name"]),
                    profile_id=(str(item["profile_id"]) if item.get("profile_id") else None),
                    endpoint=(str(item["endpoint"]) if item.get("endpoint") else None),
                    port=(int(item["port"]) if item.get("port") is not None else None),
                    metadata={"builtin": True},
                )
            )
        return out

    def _registered(self) -> list[AgentRecord]:
        active_id = self._data.get("active_id")
        out: list[AgentRecord] = []
        for raw in (self._data.get("agents") or {}).values():
            if not isinstance(raw, dict):
                continue
            record = AgentRecord.from_dict(raw)
            if active_id:
                record.active = record.id == active_id
            out.append(record)
        return out

    # ── public API ────────────────────────────────────────────────

    def list_agents(
        self,
        *,
        kind: AgentKind | str | None = None,
        role: AgentRole | str | None = None,
    ) -> list[AgentRecord]:
        """Return merged catalog: discovered native + builtin/registered third-party."""
        # Product shape: lead + standing specialists always present (idempotent).
        try:
            from jaeger_ai.core.agent_registry.specialists import ensure_standing_specialists

            ensure_standing_specialists(self)
        except Exception:
            pass
        want: AgentKind | None = None
        if kind is not None:
            want = kind if isinstance(kind, AgentKind) else AgentKind(str(kind))
        want_role: AgentRole | None = None
        if role is not None and str(role).strip():
            want_role = role if isinstance(role, AgentRole) else normalize_agent_role(role)

        by_id: dict[str, AgentRecord] = {}
        for record in self._discover_native():
            by_id[record.id] = record
        for record in self._builtin_third_party():
            by_id[record.id] = record
        for record in self._registered():
            # Registry overlays discovery (custom display names, endpoints).
            existing = by_id.get(record.id)
            if existing is not None and record.kind is AgentKind.NATIVE:
                record.instance_path = record.instance_path or existing.instance_path
                record.instance_name = record.instance_name or existing.instance_name
                if not record.active:
                    record.active = existing.active
            by_id[record.id] = record

        active_id = self._data.get("active_id")
        if active_id and active_id in by_id:
            for record in by_id.values():
                record.active = record.id == active_id

        agents = list(by_id.values())
        if want is not None:
            agents = [a for a in agents if a.kind is want]
        if want_role is not None:
            agents = [a for a in agents if a.role is want_role]
        agents.sort(
            key=lambda a: (
                0 if a.role is AgentRole.LEAD else 1 if a.role is AgentRole.SPECIALIST else 2,
                0 if a.kind is AgentKind.NATIVE else 1,
                a.display_name.lower(),
            )
        )
        return agents

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        needle = str(agent_id or "").strip()
        if not needle:
            return None
        for record in self.list_agents():
            if record.id == needle or record.name == needle:
                return record
        return None

    def create_agent(
        self,
        name: str,
        *,
        kind: AgentKind | str = AgentKind.NATIVE,
        role: AgentRole | str | None = None,
        display_name: str | None = None,
        adapter: str | None = None,
        profile_id: str | None = None,
        endpoint: str | None = None,
        port: int | None = None,
        metadata: dict[str, Any] | None = None,
        make_active: bool = False,
        scaffold_instance: bool = True,
    ) -> AgentRecord:
        """Create a Jaeger-native agent or register a third-party face.

        Native path writes a minimal instance scaffold (no model boot, no
        wizard) and a registry entry. Third-party path records adapter
        metadata only — execution stays with the external runtime.
        """
        clean = str(name or "").strip()
        if not _NAME_RE.match(clean):
            raise ValueError(
                "agent name must be 1-64 chars, start alphanumeric, "
                "and contain only [A-Za-z0-9._-]"
            )
        kind_enum = kind if isinstance(kind, AgentKind) else AgentKind(str(kind))
        label = (display_name or clean).strip() or clean
        meta = dict(metadata or {})
        meta["created_at"] = meta.get("created_at") or time.time()
        adapter_hint = (adapter or clean) if kind_enum is AgentKind.THIRD_PARTY else None
        provisional_id = (
            f"native:{clean}" if kind_enum is AgentKind.NATIVE else f"tp:{(adapter or clean)}"
        )
        role_hint = role if role is not None else meta.get("role")
        if role_hint is None and meta.get("specialist") is True:
            role_hint = AgentRole.SPECIALIST.value
        role_enum = normalize_agent_role(
            role_hint,
            default=default_role_for(
                kind=kind_enum,
                name=clean,
                agent_id=provisional_id,
                adapter=adapter_hint,
            ),
        )

        if kind_enum is AgentKind.NATIVE:
            agent_id = f"native:{clean}"
            instance_dir = self._instances_root() / clean
            if scaffold_instance:
                self._scaffold_native_instance(instance_dir, name=clean, display_name=label)
            record = AgentRecord(
                id=agent_id,
                name=clean,
                kind=AgentKind.NATIVE,
                display_name=label,
                source="registry",
                role=role_enum,
                active=False,
                instance_name=clean,
                instance_path=str(instance_dir),
                profile_id="jaeger",
                metadata=meta,
            )
        else:
            adapter_name = (adapter or clean).strip() or clean
            agent_id = f"tp:{adapter_name}"
            record = AgentRecord(
                id=agent_id,
                name=clean,
                kind=AgentKind.THIRD_PARTY,
                display_name=label,
                source="registry",
                role=role_enum,
                active=False,
                adapter=adapter_name,
                profile_id=profile_id or adapter_name,
                endpoint=endpoint,
                port=port,
                metadata=meta,
            )

        existing = (self._data.get("agents") or {}).get(record.id)
        if isinstance(existing, dict) and not meta.get("replace"):
            # Idempotent create: return merged existing unless replace requested.
            prior = AgentRecord.from_dict(existing)
            prior.display_name = label or prior.display_name
            if endpoint:
                prior.endpoint = endpoint
            if port is not None:
                prior.port = port
            if role is not None:
                prior.role = role_enum
            record = prior

        self._data.setdefault("agents", {})[record.id] = record.to_dict()
        if make_active:
            self._data["active_id"] = record.id
            record.active = True
            if kind_enum is AgentKind.NATIVE:
                self._write_sticky(clean)
        self._save()
        return record

    def register_third_party(
        self,
        name: str,
        *,
        display_name: str | None = None,
        adapter: str | None = None,
        profile_id: str | None = None,
        endpoint: str | None = None,
        port: int | None = None,
        metadata: dict[str, Any] | None = None,
        make_active: bool = False,
    ) -> AgentRecord:
        """Explicit ThirdPartyAgent registration (adapter face)."""
        return self.create_agent(
            name,
            kind=AgentKind.THIRD_PARTY,
            display_name=display_name,
            adapter=adapter,
            profile_id=profile_id,
            endpoint=endpoint,
            port=port,
            metadata=metadata,
            make_active=make_active,
            scaffold_instance=False,
        )

    def set_active(self, agent_id: str) -> AgentRecord:
        """Switch the active agent. Never blocked by fee/feature flags."""
        record = self.get_agent(agent_id)
        if record is None:
            raise KeyError(f"agent not found: {agent_id}")
        # Fundamentals invariant — switching native/third-party is always allowed.
        if record.fundamentals_gated:  # pragma: no cover — forced False on load
            record.fundamentals_gated = False
        self._data["active_id"] = record.id
        if record.kind is AgentKind.NATIVE and record.instance_name:
            self._write_sticky(record.instance_name)
        # Persist overlay so active_id survives restart.
        stored = dict(record.to_dict())
        stored["active"] = True
        self._data.setdefault("agents", {})[record.id] = stored
        self._save()
        record.active = True
        return record

    def to_catalog(self) -> dict[str, Any]:
        """WebUI / gateway payload: native + third-party, switchable together."""
        agents = self.list_agents()
        native = [a.to_dict() for a in agents if is_native(a)]
        third_party = [a.to_dict() for a in agents if is_third_party(a)]
        specialists = [a.to_dict() for a in agents if a.role is AgentRole.SPECIALIST]
        active = next((a.to_dict() for a in agents if a.active), None)
        lead_rec = next((a for a in agents if a.role is AgentRole.LEAD), None)
        if lead_rec is None:
            lead_rec = next(
                (a for a in agents if a.id == "native:jaeger" or a.name == "jaeger"),
                None,
            )
        lead = lead_rec.to_dict() if lead_rec is not None else active
        return {
            "model": "grok_bot_shape",
            "persistence_spine": "jaeger_gateway",
            "gateway_port": 8810,
            "fundamentals_fee_gated": False,
            "active": active,
            "lead": lead,
            "agents": [a.to_dict() for a in agents],
            "jaeger_native": native,
            "third_party": third_party,
            "specialists": specialists,
            "counts": {
                "total": len(agents),
                "jaeger_native": len(native),
                "third_party": len(third_party),
                "lead": 1 if lead else 0,
                "specialist": len(specialists),
                "runtime": sum(1 for a in agents if a.role is AgentRole.RUNTIME),
            },
        }

    # ── helpers ───────────────────────────────────────────────────

    def _write_sticky(self, instance_name: str) -> None:
        path = self.root / "active_instance"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(instance_name.strip() + "\n", encoding="utf-8")

    def _scaffold_native_instance(self, instance_dir: Path, *, name: str, display_name: str) -> None:
        """Minimal on-disk agent without running the interactive wizard."""
        instance_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = instance_dir / "identity.yaml"
        if not identity.exists():
            identity.write_text(
                f"name: {display_name}\n"
                f"agent_name: {name}\n"
                "framework: jaeger\n"
                "kind: jaeger_native\n",
                encoding="utf-8",
            )
        marker = instance_dir / "agent_registry.json"
        if not marker.exists():
            marker.write_text(
                json.dumps(
                    {
                        "id": f"native:{name}",
                        "kind": AgentKind.NATIVE.value,
                        "created_via": "AgentRegistry.create_agent",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


def get_default_registry() -> AgentRegistry:
    return AgentRegistry()


def create_agent(*args, **kwargs):
    """Module-level create_agent — framework entry for Jaeger-native / third-party."""
    return get_default_registry().create_agent(*args, **kwargs)


def list_agents(*args, **kwargs):
    """Module-level list_agents — native + third-party catalog."""
    return get_default_registry().list_agents(*args, **kwargs)
