"""Diagnose validation failures and apply only safe, deterministic repairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.commissioning_validation import CheckResult, ValidationReport


SAFE_REPAIRS = {
    "entity_identity": "create_identity",
    "event_fabric": "create_event_store",
    "memory_store": "create_memory_dir",
    "authority": "write_default_policy",
    "indexer_registration": "write_baseline_sources",
    "cognition.chat": "select_certified_chat",
    "cognition.react": "select_certified_react",
    "safe_tool_execution": "create_memory_dir",
}

UNSAFE = frozenset({
    "bypass_os_permissions",
    "invent_credentials",
    "weaken_security",
    "grant_broader_authority",
    "disable_verification",
    "disable_effect_ledger",
    "merge_to_master",
    "silent_software_install",
})


@dataclass
class RepairAttempt:
    check_id: str
    action: str
    applied: bool
    safe: bool
    detail: str = ""
    needs_human: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose(check: CheckResult) -> RepairAttempt:
    action = SAFE_REPAIRS.get(check.id, "")
    if action:
        return RepairAttempt(
            check_id=check.id, action=action, applied=False, safe=True,
            detail=check.detail or check.evidence,
        )
    return RepairAttempt(
        check_id=check.id, action="request_human", applied=False, safe=False,
        needs_human=True,
        detail=check.detail or check.evidence or "Jaeger cannot safely repair this",
    )


def _write_default_policy(root: Path) -> None:
    from jaeger_ai.core.instance.commissioning import default_authority_policy, write_authority_policy
    write_authority_policy(root, default_authority_policy(root))


def _select_certified(root: Path, role: str) -> str:
    from jaeger_ai.core.instance.provider_certification import load_matrix, select_production_model
    matrix = load_matrix(root)
    if role.upper() == "REACT":
        provider, model = select_production_model(matrix)
        return f"{provider}:{model}"
    assignment = matrix.assignments.get(role.upper())
    if assignment:
        return f"{assignment.get('provider')}:{assignment.get('model')}"
    return ""


def apply_repair(instance_root: Path | Any, attempt: RepairAttempt) -> RepairAttempt:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.instance import InstanceLayout

    root = instance_dir(instance_root)
    layout = InstanceLayout(root=root)
    if not attempt.safe or attempt.action in UNSAFE:
        attempt.needs_human = True
        attempt.applied = False
        return attempt
    try:
        if attempt.action == "create_memory_dir":
            layout.ensure_dirs()
            attempt.applied = layout.memory_dir.is_dir()
        elif attempt.action == "create_event_store":
            layout.ensure_dirs()
            from jaeger_ai.core.entity.event_store import SqliteEventStore
            store = SqliteEventStore(layout.event_store_path)
            store.count()
            attempt.applied = layout.event_store_path.is_file()
        elif attempt.action == "create_identity":
            layout.ensure_dirs()
            from jaeger_ai.core.entity.identity import resolve_entity_identity
            ident = resolve_entity_identity(layout.memory_dir)
            attempt.applied = bool(ident.entity_id)
            attempt.detail = ident.entity_id
        elif attempt.action == "write_default_policy":
            _write_default_policy(root)
            attempt.applied = (root / "authority_policy.yaml").is_file()
        elif attempt.action == "write_baseline_sources":
            from jaeger_ai.core.instance.commissioning import write_baseline_knowledge
            write_baseline_knowledge(root)
            attempt.applied = (root / "knowledge_sources.yaml").is_file()
        elif attempt.action in {"select_certified_chat", "select_certified_react"}:
            from jaeger_ai.core.instance.provider_certification import certify_available
            certify_available(root, live=False)
            role = "CHAT" if "chat" in attempt.action else "REACT"
            chosen = _select_certified(root, role)
            attempt.applied = bool(chosen)
            attempt.detail = chosen or "no certified model"
            if not chosen:
                attempt.needs_human = True
        else:
            attempt.needs_human = True
            attempt.applied = False
    except Exception as exc:
        attempt.applied = False
        attempt.needs_human = True
        attempt.detail = str(exc)[:200]
    return attempt


def repair_report(
    instance_root: Path | Any,
    report: ValidationReport,
    *,
    retest: bool = True,
) -> tuple[list[RepairAttempt], ValidationReport | None]:
    attempts: list[RepairAttempt] = []
    for check in report.checks:
        if check.passed:
            continue
        attempt = diagnose(check)
        if attempt.safe:
            attempt = apply_repair(instance_root, attempt)
        attempts.append(attempt)
    retested = None
    if retest and any(a.applied for a in attempts):
        from jaeger_ai.core.instance.commissioning_validation import run_validation
        groups = tuple(sorted({c.group for c in report.checks if not c.passed}))
        retested = run_validation(instance_root, groups=groups or None)
    return attempts, retested


__all__ = [
    "RepairAttempt",
    "SAFE_REPAIRS",
    "apply_repair",
    "diagnose",
    "repair_report",
]
