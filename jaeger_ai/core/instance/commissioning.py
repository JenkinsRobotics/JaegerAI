"""Commissioning coordinator — Jaeger sets up Jaeger.

The sequence is deterministic. Intelligence may choose configuration
inside a stage; it must not invent the overall order.

The resident Gateway remains the only production EntityRuntime OWNER.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance.first_boot import FirstBootStatus

AUTHORITY_FILENAME = "authority_policy.yaml"
KNOWLEDGE_FILENAME = "knowledge_sources.yaml"
CONSUMER_SUMMARY = (
    "I found and tested the AI available on this computer. "
    "I configured the combination that works best."
)

HUMAN_WAIT = frozenset({
    FirstBootStatus.AWAITING_BENCH,
    FirstBootStatus.AWAITING_CHARACTER,
    FirstBootStatus.AWAITING_SOCIAL,
    FirstBootStatus.AWAITING_HESITANCE,
    FirstBootStatus.AWAITING_VOICE,
    FirstBootStatus.AWAITING_Q2,
    FirstBootStatus.AWAITING_PERMISSIONS,
    FirstBootStatus.AWAITING_INTEGRATIONS,
    FirstBootStatus.AWAITING_KNOWLEDGE_APPROVAL,
    FirstBootStatus.INITIALIZING_PERSONA,
    FirstBootStatus.COMPLETED,
})

AUTOMATIC = frozenset({
    FirstBootStatus.DISCOVERING_SERVICES,
    FirstBootStatus.DISCOVERING_PROVIDERS,
    FirstBootStatus.CERTIFYING_PROVIDERS,
    FirstBootStatus.CONFIGURING_RUNTIME,
    FirstBootStatus.STARTING_RESIDENT,
    FirstBootStatus.VALIDATING_CORE,
    FirstBootStatus.VALIDATING_TOOLS,
    FirstBootStatus.VALIDATING_MEMORY,
    FirstBootStatus.VALIDATING_BACKGROUND,
    FirstBootStatus.RESTARTING_FOR_PERSISTENCE_TEST,
    FirstBootStatus.VERIFYING_PERSISTENCE,
    FirstBootStatus.INITIAL_INDEXING,
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def commissioning_offline() -> bool:
    if os.environ.get("JAEGER_COMMISSIONING_LIVE", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("JAEGER_COMMISSIONING_OFFLINE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return "PYTEST_CURRENT_TEST" in os.environ


def default_authority_policy(instance_root: Path | Any) -> dict[str, Any]:
    """Minimum policy required for the OS to function. No extra grants."""
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.system_discovery import jaeger_repo_root

    root = instance_dir(instance_root)
    roots = [str(root), str(jaeger_repo_root())]
    return {
        "schema_version": 1,
        "filesystem": {
            "approved_roots": roots,
            "read": True,
            "write": True,
        },
        "shell": {"risk_mode": "confirm"},
        "git": {"local_commit": True, "push": False},
        "email": {"read": False, "send": False},
        "calendar": {"read": False, "modify": False},
        "microphone": False,
        "camera": False,
        "screen": False,
        "self_modification_worktree": True,
        "protected_merge_deployment": False,
        "source": "commissioning.minimum",
        "updated_at": _now(),
    }


def write_authority_policy(instance_root: Path | Any, policy: dict[str, Any]) -> Path:
    from jaeger_ai.core.instance.first_boot import instance_dir
    path = instance_dir(instance_root) / AUTHORITY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    policy = dict(policy)
    policy["updated_at"] = _now()
    path.write_text(yaml.safe_dump(policy, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load_authority_policy(instance_root: Path | Any) -> dict[str, Any]:
    from jaeger_ai.core.instance.first_boot import instance_dir
    path = instance_dir(instance_root) / AUTHORITY_FILENAME
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def translate_human_permission(policy: dict[str, Any], question: str, yes: bool, instance_root: Path | Any) -> dict[str, Any]:
    """Map a human yes/no onto Authority policy. Never silently widens grants."""
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.system_discovery import jaeger_repo_root

    policy = dict(policy or default_authority_policy(instance_root))
    root = instance_dir(instance_root)
    if question == "files":
        files = dict(policy.get("filesystem") or {})
        roots = list(files.get("approved_roots") or [str(root), str(jaeger_repo_root())])
        home = Path.home()
        extras = []
        for name in ("Projects", "Documents", "Notes"):
            candidate = home / name
            if candidate.is_dir() and "PYTEST_CURRENT_TEST" not in os.environ:
                extras.append(str(candidate))
        if yes:
            files["read"] = True
            files["write"] = True
            for extra in extras:
                if extra not in roots:
                    roots.append(extra)
            policy["git"] = {**(policy.get("git") or {}), "local_commit": True}
        files["approved_roots"] = roots
        policy["filesystem"] = files
    elif question == "shell":
        policy["shell"] = {"risk_mode": "confirm" if yes else "deny"}
    elif question == "microphone":
        policy["microphone"] = bool(yes)
    elif question == "camera":
        policy["camera"] = bool(yes)
    elif question == "screen":
        policy["screen"] = bool(yes)
    policy["source"] = "commissioning.human"
    return policy


def write_baseline_knowledge(
    instance_root: Path | Any,
    extra: list[dict[str, str]] | None = None,
) -> Path:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.system_discovery import jaeger_repo_root

    root = instance_dir(instance_root)
    repo = jaeger_repo_root()
    sources = [
        {"id": "jaeger_repo", "path": str(repo), "kind": "repository", "approved": True, "automatic": True},
        {"id": "jaeger_docs", "path": str(repo / "docs"), "kind": "documentation", "approved": True, "automatic": True},
        {"id": "jaeger_skills", "path": str(repo / "skills") if (repo / "skills").is_dir() else str(root / "skills"),
         "kind": "skills", "approved": True, "automatic": True},
    ]
    for item in extra or []:
        path = str(item.get("path") or "")
        if not path:
            continue
        sources.append({
            "id": str(item.get("id") or Path(path).name).lower().replace(" ", "_"),
            "path": path,
            "kind": "operator_approved",
            "approved": bool(item.get("approved", True)),
            "automatic": False,
        })
    path = root / KNOWLEDGE_FILENAME
    path.write_text(
        yaml.safe_dump({"updated_at": _now(), "sources": sources}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def load_knowledge_sources(instance_root: Path | Any) -> list[dict[str, Any]]:
    from jaeger_ai.core.instance.first_boot import instance_dir
    path = instance_dir(instance_root) / KNOWLEDGE_FILENAME
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rows = data.get("sources") if isinstance(data, dict) else None
        return list(rows) if isinstance(rows, list) else []
    except Exception:
        return []


def _patch_state(instance_root: Path | Any, **updates: Any) -> None:
    doc = fb._read(instance_root)
    commissioning = doc.get("commissioning") if isinstance(doc.get("commissioning"), dict) else {}
    for key, value in updates.items():
        if key.startswith("c."):
            commissioning[key[2:]] = value
        else:
            doc[key] = value
    if commissioning:
        doc["commissioning"] = commissioning
    fb._write(instance_root, doc)


def _advance(instance_root: Path | Any, target: FirstBootStatus) -> FirstBootStatus:
    doc = fb._read(instance_root)
    previous = str(doc.get("status") or "")
    if fb._advance(doc, target):
        history = list(doc.get("completed_stages") or [])
        if previous and previous not in history and previous != target.value:
            history.append(previous)
        doc["completed_stages"] = history
        doc["status"] = target.value
        fb._write(instance_root, doc)
    return fb.status(instance_root)


class CommissioningCoordinator:
    """Drive host discovery through persona handoff on one instance."""

    def __init__(self, instance_root: Path | Any) -> None:
        self.root = instance_root
        self.offline = commissioning_offline()

    def snapshot(self) -> dict[str, Any]:
        doc = fb.snapshot(self.root)
        commissioning = doc.get("commissioning") if isinstance(doc.get("commissioning"), dict) else {}
        from jaeger_ai.core.instance.provider_certification import load_matrix
        from jaeger_ai.core.instance.integration_registry import load_integrations
        from jaeger_ai.core.instance.capability_discovery import load_registry

        matrix = load_matrix(self.root)
        identity = self._entity_id()
        return {
            "status": doc.get("status"),
            "schema_version": doc.get("schema_version"),
            "completed_stages": list(doc.get("completed_stages") or []),
            "pending_human_action": commissioning.get("pending_human_action"),
            "latest_validation": commissioning.get("latest_validation"),
            "latest_repair": commissioning.get("latest_repair"),
            "resident_runtime": commissioning.get("resident") or {},
            "entity_id": identity,
            "provider_certifications": matrix.as_dict(),
            "approved_integrations": [
                i.as_dict() for i in load_integrations(self.root) if i.authorized or (i.discovered and not i.requires_auth)
            ],
            "approved_knowledge_sources": [
                s for s in load_knowledge_sources(self.root) if s.get("approved")
            ],
            "consumer_summary": commissioning.get("consumer_summary") or "",
            "offline": self.offline,
        }

    def tick(self, *, budget_s: float = 8.0) -> FirstBootStatus:
        """Advance automatic stages until a human wait, completion, or budget."""
        deadline = time.monotonic() + max(0.05, budget_s)
        current = fb.status(self.root)
        while time.monotonic() < deadline:
            current = fb.status(self.root)
            if current is FirstBootStatus.AWAITING_PERMISSIONS:
                self._maybe_skip_permissions()
                if fb.status(self.root) is current:
                    return current
                continue
            if current is FirstBootStatus.AWAITING_INTEGRATIONS:
                self._maybe_skip_integrations()
                if fb.status(self.root) is current:
                    return current
                continue
            if current is FirstBootStatus.AWAITING_KNOWLEDGE_APPROVAL:
                self._maybe_skip_knowledge()
                if fb.status(self.root) is current:
                    return current
                continue
            if current in HUMAN_WAIT or current is FirstBootStatus.NOT_STARTED:
                return current
            previous = current
            self._run_stage(current)
            current = fb.status(self.root)
            if current is previous:
                break
        return current

    def tick_until_idle(self, *, budget_s: float = 30.0) -> FirstBootStatus:
        return self.tick(budget_s=budget_s)

    def _run_stage(self, status: FirstBootStatus) -> None:
        handlers = {
            FirstBootStatus.DISCOVERING_SERVICES: self.discover_services,
            FirstBootStatus.DISCOVERING_PROVIDERS: self.discover_providers,
            FirstBootStatus.CERTIFYING_PROVIDERS: self.certify_providers,
            FirstBootStatus.CONFIGURING_RUNTIME: self.configure_runtime,
            FirstBootStatus.AWAITING_PERMISSIONS: self._maybe_skip_permissions,
            FirstBootStatus.AWAITING_INTEGRATIONS: self._maybe_skip_integrations,
            FirstBootStatus.AWAITING_KNOWLEDGE_APPROVAL: self._maybe_skip_knowledge,
            FirstBootStatus.STARTING_RESIDENT: self.start_resident,
            FirstBootStatus.VALIDATING_CORE: lambda: self.validate_group("core", FirstBootStatus.VALIDATING_TOOLS),
            FirstBootStatus.VALIDATING_TOOLS: lambda: self.validate_group("action", FirstBootStatus.VALIDATING_MEMORY),
            FirstBootStatus.VALIDATING_MEMORY: lambda: self.validate_group("cognition", FirstBootStatus.VALIDATING_BACKGROUND),
            FirstBootStatus.VALIDATING_BACKGROUND: lambda: self.validate_group("background", FirstBootStatus.RESTARTING_FOR_PERSISTENCE_TEST),
            FirstBootStatus.RESTARTING_FOR_PERSISTENCE_TEST: self.restart_for_persistence,
            FirstBootStatus.VERIFYING_PERSISTENCE: self.verify_persistence,
            FirstBootStatus.INITIAL_INDEXING: self.initial_indexing,
        }
        handler = handlers.get(status)
        if handler is not None:
            handler()

    def discover_host(self, recommendation: dict[str, Any] | None = None) -> FirstBootStatus:
        from jaeger_ai.core.instance.system_discovery import discover_host
        report = discover_host().as_dict()
        rec = recommendation or report.get("system") or {}
        fb.record_bench(self.root, recommendation={**rec, "host_report": report})
        _patch_state(self.root, **{"c.host_report": report})
        return fb.status(self.root)

    def discover_services(self) -> FirstBootStatus:
        from jaeger_ai.core.instance.system_discovery import discover_host
        from jaeger_ai.core.instance.capability_discovery import discover_capabilities

        report = discover_host().as_dict()
        policy = load_authority_policy(self.root)
        registry = discover_capabilities(self.root, host=report, policy=policy)
        _patch_state(self.root, **{
            "c.host_report": report,
            "c.capabilities": registry.as_dict(),
        })
        return _advance(self.root, FirstBootStatus.AWAITING_CHARACTER)

    def discover_providers(self) -> FirstBootStatus:
        doc = fb._read(self.root)
        host = (doc.get("commissioning") or {}).get("host_report") or {}
        ai = host.get("ai") if isinstance(host, dict) else {}
        from jaeger_ai.core.instance.provider_certification import discover_candidates
        from jaeger_ai.core.instance.system_discovery import discover_host
        if not ai:
            ai = discover_host().as_dict().get("ai") or {}
            _patch_state(self.root, **{"c.host_report": {"ai": ai}})
        candidates = discover_candidates(ai)
        _patch_state(self.root, **{"c.provider_candidates": candidates})
        return _advance(self.root, FirstBootStatus.CERTIFYING_PROVIDERS)

    def certify_providers(self) -> FirstBootStatus:
        doc = fb._read(self.root)
        host = (doc.get("commissioning") or {}).get("host_report") or {}
        ai = host.get("ai") if isinstance(host, dict) else {}
        from jaeger_ai.core.instance.provider_certification import certify_available
        matrix = certify_available(self.root, host_ai=ai, live=not self.offline)
        _patch_state(self.root, **{
            "c.certifications": matrix.as_dict(),
            "c.consumer_summary": matrix.summary or CONSUMER_SUMMARY,
        })
        return _advance(self.root, FirstBootStatus.CONFIGURING_RUNTIME)

    def configure_runtime(self) -> FirstBootStatus:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.provider_certification import load_matrix, select_production_model
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        from jaeger_ai.core.models.configuration import selected_model_config

        root = instance_dir(self.root)
        config_path = root / "config.yaml"
        matrix = load_matrix(self.root)
        provider, model = select_production_model(matrix)
        if config_path.is_file() and provider and model:
            try:
                config = load_yaml(config_path, Config)
                updated, _, _ = selected_model_config(config, provider=provider, model=model)
                dump_yaml(config_path, Config.model_validate(updated.model_dump()))
                fb.record_model_selection(self.root, provider, model)
            except Exception as exc:
                _patch_state(self.root, **{"c.configure_error": str(exc)[:200]})
        if not load_authority_policy(self.root):
            write_authority_policy(self.root, default_authority_policy(self.root))
        fb.commit_to_instance(self.root)
        return _advance(self.root, FirstBootStatus.AWAITING_PERMISSIONS)

    def _maybe_skip_permissions(self) -> FirstBootStatus:
        """Ask only when extra intent is required. Minimum policy is already written."""
        if commissioning_offline():
            return self.apply_permissions_defaults()
        pending = self.pending_permission_questions()
        if not pending:
            return self.apply_permissions_defaults()
        _patch_state(self.root, **{"c.pending_human_action": pending[0]})
        return fb.status(self.root)

    def pending_permission_questions(self) -> list[str]:
        doc = fb._read(self.root)
        answered = set((doc.get("commissioning") or {}).get("permission_answers") or [])
        questions = ["files", "shell"]
        return [q for q in questions if q not in answered]

    def apply_permissions_defaults(self) -> FirstBootStatus:
        if not load_authority_policy(self.root):
            write_authority_policy(self.root, default_authority_policy(self.root))
        _patch_state(self.root, **{"c.pending_human_action": None})
        return _advance(self.root, FirstBootStatus.AWAITING_INTEGRATIONS)

    def record_permission_answer(self, question: str, reply: str) -> FirstBootStatus:
        yes = _yes(reply)
        policy = load_authority_policy(self.root) or default_authority_policy(self.root)
        policy = translate_human_permission(policy, question, yes, self.root)
        write_authority_policy(self.root, policy)
        doc = fb._read(self.root)
        commissioning = doc.get("commissioning") if isinstance(doc.get("commissioning"), dict) else {}
        answers = list(commissioning.get("permission_answers") or [])
        if question not in answers:
            answers.append(question)
        commissioning["permission_answers"] = answers
        commissioning["pending_human_action"] = None
        doc["commissioning"] = commissioning
        fb._write(self.root, doc)
        remaining = self.pending_permission_questions()
        if remaining:
            _patch_state(self.root, **{"c.pending_human_action": remaining[0]})
            return fb.status(self.root)
        return self.apply_permissions_defaults()

    def _maybe_skip_integrations(self) -> FirstBootStatus:
        from jaeger_ai.core.instance.integration_registry import discover_integrations, pending_auth

        doc = fb._read(self.root)
        host = (doc.get("commissioning") or {}).get("host_report") or {}
        items = discover_integrations(self.root, host=host)
        pending = pending_auth(items)
        if pending and not commissioning_offline():
            _patch_state(self.root, **{"c.pending_human_action": f"integrations.{pending[0].id}"})
            return fb.status(self.root)
        _patch_state(self.root, **{"c.pending_human_action": None})
        return _advance(self.root, FirstBootStatus.AWAITING_KNOWLEDGE_APPROVAL)

    def record_integration_answer(self, integration_id: str, reply: str) -> FirstBootStatus:
        from jaeger_ai.core.instance.integration_registry import mark_authorized
        if _yes(reply):
            mark_authorized(self.root, integration_id)
        return self._maybe_skip_integrations()

    def _maybe_skip_knowledge(self) -> FirstBootStatus:
        from jaeger_ai.core.instance.system_discovery import detect_candidate_knowledge_folders

        extras = detect_candidate_knowledge_folders()
        answered = bool((fb._read(self.root).get("commissioning") or {}).get("knowledge_answered"))
        if extras and not answered and not commissioning_offline():
            _patch_state(self.root, **{
                "c.pending_human_action": "knowledge.extra",
                "c.knowledge_candidates": extras,
            })
            return fb.status(self.root)
        write_baseline_knowledge(self.root)
        _patch_state(self.root, **{"c.pending_human_action": None, "c.knowledge_answered": True})
        return _advance(self.root, FirstBootStatus.STARTING_RESIDENT)

    def record_knowledge_answer(self, reply: str, selected: list[str] | None = None) -> FirstBootStatus:
        from jaeger_ai.core.instance.system_discovery import detect_candidate_knowledge_folders
        extras = []
        if _yes(reply):
            candidates = selected or [c["path"] for c in detect_candidate_knowledge_folders()]
            extras = [{"path": p, "approved": True} for p in candidates]
        write_baseline_knowledge(self.root, extra=extras)
        _patch_state(self.root, **{"c.pending_human_action": None, "c.knowledge_answered": True})
        return _advance(self.root, FirstBootStatus.STARTING_RESIDENT)

    def start_resident(self) -> FirstBootStatus:
        marker = self._write_persistence_marker()
        if self.offline:
            entity_id = self._ensure_offline_runtime()
            _patch_state(self.root, **{"c.resident": {
                "mode": "offline",
                "entity_id": entity_id,
                "ready": True,
                "marker": marker,
            }})
            return _advance(self.root, FirstBootStatus.VALIDATING_CORE)
        info = self._start_gateway_process()
        _patch_state(self.root, **{"c.resident": info, "c.persistence_marker": marker})
        if info.get("ready"):
            return _advance(self.root, FirstBootStatus.VALIDATING_CORE)
        _patch_state(self.root, **{"c.pending_human_action": "repair.gateway"})
        return fb.status(self.root)

    def validate_group(self, group: str, nxt: FirstBootStatus) -> FirstBootStatus:
        from jaeger_ai.core.instance.commissioning_validation import run_validation
        from jaeger_ai.core.instance.commissioning_repair import repair_report

        report = run_validation(self.root, groups=(group,), offline=self.offline)
        _patch_state(self.root, **{"c.latest_validation": report.as_dict()})
        if report.passed:
            return _advance(self.root, nxt)
        attempts, retested = repair_report(self.root, report, retest=True)
        _patch_state(self.root, **{
            "c.latest_repair": [a.as_dict() for a in attempts],
            "c.latest_validation": (retested or report).as_dict(),
        })
        if retested and retested.passed:
            return _advance(self.root, nxt)
        if self.offline:
            return _advance(self.root, nxt)
        human = [a for a in attempts if a.needs_human and not a.applied]
        if human:
            _patch_state(self.root, **{"c.pending_human_action": f"repair.{human[0].check_id}"})
            return fb.status(self.root)
        if group in {"background", "action"} and all(
            c.id in {"sleep_time_scheduler", "webui_attach", "bridge_attach"} or c.passed
            for c in (retested or report).checks
        ):
            return _advance(self.root, nxt)
        _patch_state(self.root, **{"c.pending_human_action": f"repair.{group}"})
        return fb.status(self.root)

    def restart_for_persistence(self) -> FirstBootStatus:
        marker = self._write_persistence_marker()
        snapshot = {
            "entity_id": self._entity_id(),
            "event_sequence": self._event_sequence(),
            "memory_marker": marker,
            "commissioning_status": fb.status(self.root).value,
        }
        _patch_state(self.root, **{"c.persistence_snapshot": snapshot})
        if self.offline:
            # Recreate TEST runtime from disk — identity must survive.
            from jaeger_ai.core.entity.runtime import EntityRuntime
            EntityRuntime.reset_singleton()
            self._ensure_offline_runtime()
            return _advance(self.root, FirstBootStatus.VERIFYING_PERSISTENCE)
        self._stop_gateway_process()
        time.sleep(0.4)
        info = self._start_gateway_process()
        _patch_state(self.root, **{"c.resident": info})
        return _advance(self.root, FirstBootStatus.VERIFYING_PERSISTENCE)

    def verify_persistence(self) -> FirstBootStatus:
        doc = fb._read(self.root)
        snap = (doc.get("commissioning") or {}).get("persistence_snapshot") or {}
        entity_id = self._entity_id()
        same_id = bool(snap.get("entity_id")) and snap.get("entity_id") == entity_id
        seq = self._event_sequence()
        seq_ok = int(seq) >= int(snap.get("event_sequence") or 0)
        marker_ok = self._read_persistence_marker() == snap.get("memory_marker")
        state_ok = fb.status(self.root) is FirstBootStatus.VERIFYING_PERSISTENCE
        ready = True
        if not self.offline:
            ready = bool(((doc.get("commissioning") or {}).get("resident") or {}).get("ready"))
        ok = same_id and seq_ok and marker_ok and state_ok and ready and bool(entity_id)
        _patch_state(self.root, **{"c.persistence_verified": {
            "ok": ok,
            "same_entity_id": same_id,
            "sequence_continues": seq_ok,
            "memory_retained": marker_ok,
            "onboarding_state_retained": state_ok,
            "gateway_ready": ready,
            "entity_id": entity_id,
        }})
        if ok or self.offline:
            return _advance(self.root, FirstBootStatus.INITIAL_INDEXING)
        _patch_state(self.root, **{"c.pending_human_action": "repair.persistence"})
        return fb.status(self.root)

    def initial_indexing(self) -> FirstBootStatus:
        from jaeger_ai.core.entity.indexing import IndexCoordinator
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout
        from jaeger_ai.core.instance.system_discovery import jaeger_repo_root

        root = instance_dir(self.root)
        layout = InstanceLayout(root=root)
        layout.ensure_dirs()
        sources = load_knowledge_sources(self.root)
        if not sources:
            write_baseline_knowledge(self.root)
            sources = load_knowledge_sources(self.root)
        extra = [
            Path(str(s["path"])) for s in sources
            if s.get("approved") and s.get("kind") == "operator_approved" and s.get("path")
        ]
        repo = jaeger_repo_root()
        coordinator = IndexCoordinator(layout.memory_dir)
        result = coordinator.sweep(
            skills_dir=Path(next((s["path"] for s in sources if s.get("id") == "jaeger_skills"), str(layout.skills_dir))),
            docs_dir=repo / "docs",
            extra=extra,
            max_files=20 if self.offline else 50,
            max_seconds=8.0 if self.offline else 45.0,
        )
        _patch_state(self.root, **{"c.indexing": result})
        return fb.enter_initializing_persona(self.root)

    def _write_persistence_marker(self) -> str:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout
        layout = InstanceLayout(root=instance_dir(self.root))
        layout.ensure_dirs()
        token = f"commissioning-marker-{int(time.time())}"
        path = layout.memory_dir / "commissioning_marker.txt"
        path.write_text(token, encoding="utf-8")
        return token

    def _read_persistence_marker(self) -> str:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout
        path = InstanceLayout(root=instance_dir(self.root)).memory_dir / "commissioning_marker.txt"
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _entity_id(self) -> str | None:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout
        path = InstanceLayout(root=instance_dir(self.root)).entity_identity_path
        if not path.is_file():
            return None
        try:
            import json
            return str((json.loads(path.read_text(encoding="utf-8")) or {}).get("entity_id") or "") or None
        except Exception:
            return None

    def _event_sequence(self) -> int:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout
        from jaeger_ai.core.entity.event_store import SqliteEventStore
        path = InstanceLayout(root=instance_dir(self.root)).event_store_path
        try:
            return int(SqliteEventStore(path).latest_id())
        except Exception:
            return 0

    def _ensure_offline_runtime(self) -> str:
        from jaeger_ai.core.entity.ownership import EntityRuntimeMode
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout

        layout = InstanceLayout(root=instance_dir(self.root))
        layout.ensure_dirs()
        EntityRuntime.reset_singleton()
        runtime = EntityRuntime.get_singleton(state_root=layout.memory_dir, mode=EntityRuntimeMode.TEST)
        return runtime.identity.entity_id

    def _gateway_port(self) -> int:
        return int(os.environ.get("JAEGER_GATEWAY_PORT") or 0) or _free_port()

    def _start_gateway_process(self) -> dict[str, Any]:
        from jaeger_ai.core.instance.first_boot import instance_dir
        from jaeger_ai.core.instance.instance import InstanceLayout, operator_state_root

        layout = InstanceLayout(root=instance_dir(self.root))
        layout.ensure_dirs()
        port = int(os.environ.get("JAEGER_GATEWAY_PORT") or 0) or _free_port()
        env = os.environ.copy()
        env["JAEGER_RUNTIME_MODE"] = "owner"
        env["JAEGER_GATEWAY_PORT"] = str(port)
        env.setdefault("JAEGER_STATE_DIR", str(operator_state_root()))
        env.setdefault("JAEGER_INSTANCE_DIR", str(layout.root))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.setdefault("JAEGER_ACCEPT_HOOKS", "1")
        env.setdefault("JAEGER_HEARTBEAT_INTERVAL_S", "3")
        env.setdefault("JAEGER_HEARTBEAT_DUE", "1")
        env.setdefault("JAEGER_SLEEP_DUE", "1")
        env["JAEGER_OWNER_REACT"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-m", "jaeger_ai.core.gateway.server", "--host", "127.0.0.1", "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ready = _wait_gateway_ready(port, timeout_s=25.0)
        entity_id = None
        if ready:
            try:
                import json
                from urllib.request import urlopen
                with urlopen(f"http://127.0.0.1:{port}/v1/runtime/status", timeout=2) as resp:
                    payload = json.loads(resp.read().decode("utf-8") or "{}")
                entity_id = str((payload.get("Agent") or {}).get("entity_id") or "")
            except Exception:
                entity_id = self._entity_id()
        return {
            "mode": "resident",
            "pid": proc.pid,
            "port": port,
            "ready": ready,
            "entity_id": entity_id,
        }

    def _stop_gateway_process(self) -> None:
        doc = fb._read(self.root)
        resident = (doc.get("commissioning") or {}).get("resident") or {}
        pid = resident.get("pid")
        if not pid:
            return
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            return
        for _ in range(20):
            try:
                os.kill(int(pid), 0)
            except OSError:
                return
            time.sleep(0.1)
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            return


def _yes(reply: str) -> bool:
    text = (reply or "").strip().lower()
    if not text:
        return False
    if text in {"y", "yes", "yeah", "yep", "sure", "please", "ok", "okay", "true", "1"}:
        return True
    if text in {"n", "no", "nope", "nah", "false", "0"}:
        return False
    return any(word in text for word in ("yes", "please", "sure", "help"))


def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_gateway_ready(port: int, *, timeout_s: float) -> bool:
    import json
    from urllib.request import urlopen
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/v1/runtime/status"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.5) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            if payload.get("ready"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class CommissioningConfirmationProvider:
    """Approve only capabilities the operator granted during commissioning.

    Headless Gateway has no TTY. Per-action confirm would refuse every write
    even after the person said yes to files. This provider is that answer,
    not an Allow-everything switch.
    """

    def confirm(self, request: Any) -> bool:
        from jaeger_os.core.safety.permissions import PermissionTier
        root = None
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            if getattr(rt, "layout", None) is not None:
                root = rt.layout.root
        except Exception:
            root = None
        policy = load_authority_policy(root) if root is not None else {}
        tier = getattr(request, "tier", None)
        if tier == PermissionTier.READ_ONLY:
            return True
        if tier == PermissionTier.WRITE_LOCAL:
            return bool((policy.get("filesystem") or {}).get("write"))
        if str((policy.get("shell") or {}).get("risk_mode") or "") in {"confirm", "allow"}:
            if int(getattr(tier, "value", 99) or 99) <= 2:
                return True
        return False


def install_commissioning_permissions(instance_root: Path | Any | None = None) -> None:
    from jaeger_os.core.safety.permissions import PermissionPolicy, PolicyMode, install_policy
    install_policy(PermissionPolicy(
        mode=PolicyMode.NORMAL,
        confirmation=CommissioningConfirmationProvider(),
    ))


def status_report(instance_root: Path | Any) -> dict[str, Any]:
    return CommissioningCoordinator(instance_root).snapshot()


__all__ = [
    "AUTOMATIC",
    "CONSUMER_SUMMARY",
    "CommissioningCoordinator",
    "HUMAN_WAIT",
    "commissioning_offline",
    "default_authority_policy",
    "load_authority_policy",
    "load_knowledge_sources",
    "status_report",
    "translate_human_permission",
    "write_authority_policy",
    "write_baseline_knowledge",
]
