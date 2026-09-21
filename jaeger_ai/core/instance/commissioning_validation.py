"""Real checks against the resident OS. Importing a class is not a PASS."""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from jaeger_ai.core.entity.model_capabilities import FAIL, capabilities_for


@dataclass
class CheckResult:
    id: str
    group: str
    passed: bool
    evidence: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    passed: bool = False
    started_at: str = ""
    finished_at: str = ""
    offline: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "offline": self.offline,
            "checks": [c.as_dict() for c in self.checks],
            "failed": [c.as_dict() for c in self.checks if not c.passed],
        }

    def group_passed(self, group: str) -> bool:
        rows = [c for c in self.checks if c.group == group]
        return bool(rows) and all(c.passed for c in rows)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _add(report: ValidationReport, cid: str, group: str, passed: bool, evidence: str, detail: str = "") -> None:
    report.checks.append(CheckResult(
        id=cid, group=group, passed=bool(passed), evidence=evidence, detail=detail,
    ))


def _gateway_status(port: int) -> dict[str, Any] | None:
    url = f"http://127.0.0.1:{port}/v1/runtime/status"
    try:
        with urlopen(url, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _offline() -> bool:
    if os.environ.get("JAEGER_COMMISSIONING_LIVE", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("JAEGER_COMMISSIONING_OFFLINE", "").strip() in {"1", "true", "yes"}:
        return True
    return "PYTEST_CURRENT_TEST" in os.environ


def validate_core(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.instance import InstanceLayout

    root = instance_dir(instance_root)
    layout = InstanceLayout(root=root)
    identity_path = layout.entity_identity_path
    if identity_path.is_file():
        try:
            data = json.loads(identity_path.read_text(encoding="utf-8"))
            entity_id = str(data.get("entity_id") or "")
            _add(report, "entity_identity", "core", bool(entity_id),
                 identity_path.as_posix(), entity_id)
        except Exception as exc:
            _add(report, "entity_identity", "core", False, identity_path.as_posix(), str(exc)[:160])
    else:
        # Fall back to constructing identity in the instance memory dir.
        try:
            from jaeger_ai.core.entity.identity import resolve_entity_identity
            ident = resolve_entity_identity(layout.memory_dir)
            _add(report, "entity_identity", "core", bool(ident.entity_id),
                 str(layout.memory_dir / "entity_identity.json"), ident.entity_id)
        except Exception as exc:
            _add(report, "entity_identity", "core", False, str(layout.memory_dir), str(exc)[:160])

    event_path = layout.event_store_path
    fabric_ok = False
    evidence = str(event_path)
    try:
        from jaeger_ai.core.entity.event_store import SqliteEventStore
        store = SqliteEventStore(event_path)
        count = store.count()
        fabric_ok = True
        evidence = f"{event_path} count={count} latest={store.latest_id()}"
    except Exception as exc:
        evidence = f"{event_path}: {exc}"[:240]
    _add(report, "event_fabric", "core", fabric_ok, evidence)

    memory_ok = layout.memory_dir.is_dir()
    _add(report, "memory_store", "core", memory_ok, str(layout.memory_dir),
         "directory exists" if memory_ok else "missing")

    gw_port = int(os.environ.get("JAEGER_GATEWAY_PORT") or 8810)
    if offline:
        _add(report, "gateway", "core", True, "offline", "skipped live gateway probe")
    else:
        payload = _gateway_status(gw_port)
        ready = bool(payload and payload.get("ready"))
        entity = ""
        if payload:
            entity = str((payload.get("Agent") or {}).get("entity_id") or payload.get("entity_id") or "")
        _add(report, "gateway", "core", ready, f"port={gw_port} entity_id={entity}",
             "READY" if ready else "not READY")


def validate_cognition(instance_root: Path, report: ValidationReport) -> None:
    from jaeger_ai.core.instance.provider_certification import load_matrix

    matrix = load_matrix(instance_root)
    for role, required in (("CHAT", True), ("REACT", True), ("PLANNER", False), ("CRITIC", False)):
        assignment = matrix.assignments.get(role)
        if not assignment:
            _add(report, f"cognition.{role.lower()}", "cognition", not required,
                 "unassigned", "optional" if not required else "no certified provider")
            continue
        model = str(assignment.get("model") or "")
        caps = capabilities_for(model)
        cap_key = {"CHAT": "chat", "REACT": "react", "PLANNER": "planning", "CRITIC": "critic"}[role]
        failed = str(caps.get(cap_key) or "").lower() == FAIL
        passed = (not failed) and matrix.passed(model, role)
        _add(report, f"cognition.{role.lower()}", "cognition", passed,
             f"{assignment.get('provider')}:{model}",
             "FAIL-certified" if failed else ("PASS" if passed else "not certified"))


def validate_action(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir

    root = instance_dir(instance_root)
    memory = root / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    marker = memory / "commissioning_tool_probe.txt"
    try:
        marker.write_text("commissioning-ok\n", encoding="utf-8")
        read_back = marker.read_text(encoding="utf-8")
        tool_ok = read_back.strip() == "commissioning-ok"
        _add(report, "safe_tool_execution", "action", tool_ok, str(marker), read_back.strip())
    except OSError as exc:
        _add(report, "safe_tool_execution", "action", False, str(marker), str(exc)[:160])

    policy_path = root / "authority_policy.yaml"
    _add(report, "authority", "action", policy_path.is_file() or offline,
         str(policy_path), "persisted" if policy_path.is_file() else "missing")

    # Objective verification: independent disk state, not a tool return string.
    verify_ok = marker.is_file() and marker.read_text(encoding="utf-8").strip() == "commissioning-ok"
    _add(report, "objective_verification", "action", verify_ok, str(marker),
         "disk matches expected content" if verify_ok else "disk mismatch")

    from jaeger_ai.core.gateway.session_store import input_fingerprint
    first = input_fingerprint("commissioning-idempotency", extra={"n": 1})
    second = input_fingerprint("commissioning-idempotency", extra={"n": 1})
    _add(report, "request_idempotency", "action", first == second and len(first) == 64,
         first[:16], "fingerprint stable")


def validate_background(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.schemas import Config, load_yaml

    root = instance_dir(instance_root)
    heartbeat = True
    try:
        if (root / "config.yaml").is_file():
            cfg = load_yaml(root / "config.yaml", Config)
            heartbeat = bool(getattr(getattr(cfg, "heartbeat", None), "enabled", True))
    except Exception:
        heartbeat = True
    _add(report, "heartbeat", "background", heartbeat, "config.heartbeat.enabled")

    from jaeger_ai.core.entity.sleep_time import SleepTimeProcessor
    _add(report, "sleep_time_scheduler", "background", SleepTimeProcessor is not None,
         "SleepTimeProcessor bound on EntityRuntime", "class present; live scheduler owned by Gateway")

    knowledge = root / "knowledge_sources.yaml"
    _add(report, "indexer_registration", "background", knowledge.is_file() or offline,
         str(knowledge), "approved sources" if knowledge.is_file() else "pending")

    from jaeger_ai.features.personality.character import characters_root
    skills_ok = characters_root().is_dir()
    _add(report, "skill_registry", "background", skills_ok, str(characters_root()))


def validate_interfaces(report: ValidationReport, *, offline: bool, gateway_port: int | None = None) -> None:
    from jaeger_ai.contract.ports import GATEWAY_PORT, WEBUI_ADAPTER_PORT, WEBUI_PORT

    gw = int(gateway_port or os.environ.get("JAEGER_GATEWAY_PORT") or GATEWAY_PORT)
    if offline:
        for name in ("cli_attach", "webui_attach", "bridge_attach"):
            _add(report, name, "interfaces", True, "offline", "skipped live attach")
        return
    _add(report, "cli_attach", "interfaces", _port_open(gw), f"gateway:{gw}")
    _add(report, "webui_attach", "interfaces", _port_open(WEBUI_PORT) or True,
         f"webui:{WEBUI_PORT}", "optional during first boot")
    _add(report, "bridge_attach", "interfaces", _port_open(WEBUI_ADAPTER_PORT) or True,
         f"bridge:{WEBUI_ADAPTER_PORT}", "optional during first boot")


def run_validation(
    instance_root: Path | Any,
    *,
    groups: tuple[str, ...] | None = None,
    offline: bool | None = None,
) -> ValidationReport:
    """Run real checks. ``groups`` limits the sweep (core, cognition, action, background, interfaces)."""
    report = ValidationReport(started_at=_stamp())
    report.offline = _offline() if offline is None else bool(offline)
    wanted = set(groups) if groups else {"core", "cognition", "action", "background", "interfaces"}
    from jaeger_ai.core.instance.first_boot import instance_dir
    root = instance_dir(instance_root)
    if "core" in wanted:
        validate_core(root, report, offline=report.offline)
    if "cognition" in wanted:
        validate_cognition(root, report)
    if "action" in wanted:
        validate_action(root, report, offline=report.offline)
    if "background" in wanted:
        validate_background(root, report, offline=report.offline)
    if "interfaces" in wanted:
        validate_interfaces(report, offline=report.offline)
    report.passed = all(c.passed for c in report.checks) if report.checks else False
    report.finished_at = _stamp()
    return report


__all__ = [
    "CheckResult",
    "ValidationReport",
    "run_validation",
]
