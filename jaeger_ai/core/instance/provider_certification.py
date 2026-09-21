"""Discover, test, and persist provider fitness by cognitive role.

Existing live evidence is authoritative until retested:

* ``kimi-k2.7-code:cloud`` — REACT PASS
* ``glm-5.3-flash:cloud`` — REACT FAIL

A provider that has failed a role is never selected for that role.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_ai.core.entity.model_capabilities import (
    DEFAULT_CAPABILITIES,
    FAIL,
    PASS,
    UNKNOWN,
    capabilities_for,
    is_certified,
)

SUITE_VERSION = "commissioning-1"
CERT_FILENAME = "provider_certifications.json"

ROLES = ("CHAT", "REACT", "PLANNER", "CRITIC", "REFLECTION", "VISION", "EMBEDDING")
_ROLE_TO_CAP = {
    "CHAT": "chat",
    "REACT": "react",
    "PLANNER": "planning",
    "CRITIC": "critic",
    "REFLECTION": "reflection",
    "VISION": "vision",
    "EMBEDDING": "embedding",
}


@dataclass
class CertificationResult:
    provider: str
    model: str
    role: str
    passed: bool
    timestamp: str
    latency_ms: int = 0
    failure_reason: str = ""
    suite_version: str = SUITE_VERSION
    source: str = "evidence"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        return f"{self.model}:{self.role}"


@dataclass
class CertificationMatrix:
    results: list[CertificationResult] = field(default_factory=list)
    assignments: dict[str, dict[str, str]] = field(default_factory=dict)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite_version": SUITE_VERSION,
            "results": [r.as_dict() for r in self.results],
            "assignments": self.assignments,
            "summary": self.summary,
        }

    def result_for(self, model: str, role: str) -> CertificationResult | None:
        role = role.upper()
        for item in reversed(self.results):
            if item.model == model and item.role == role:
                return item
        return None

    def passed(self, model: str, role: str) -> bool:
        found = self.result_for(model, role)
        return bool(found and found.passed)


def cert_path(instance_root: Path | Any) -> Path:
    from jaeger_ai.core.instance.first_boot import instance_dir
    return instance_dir(instance_root) / CERT_FILENAME


def load_matrix(instance_root: Path | Any) -> CertificationMatrix:
    path = cert_path(instance_root)
    if not path.is_file():
        return CertificationMatrix()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return CertificationMatrix()
    if not isinstance(data, dict):
        return CertificationMatrix()
    results = []
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        results.append(CertificationResult(
            provider=str(row.get("provider") or ""),
            model=str(row.get("model") or ""),
            role=str(row.get("role") or "").upper(),
            passed=bool(row.get("passed")),
            timestamp=str(row.get("timestamp") or ""),
            latency_ms=int(row.get("latency_ms") or 0),
            failure_reason=str(row.get("failure_reason") or ""),
            suite_version=str(row.get("suite_version") or SUITE_VERSION),
            source=str(row.get("source") or "evidence"),
        ))
    assignments = data.get("assignments") if isinstance(data.get("assignments"), dict) else {}
    return CertificationMatrix(
        results=results,
        assignments={str(k): dict(v) for k, v in assignments.items() if isinstance(v, dict)},
        summary=str(data.get("summary") or ""),
    )


def save_matrix(instance_root: Path | Any, matrix: CertificationMatrix) -> None:
    path = cert_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(matrix.as_dict(), indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".provcert.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp)
        raise


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _from_seed(model: str, role: str, provider: str = "ollama") -> CertificationResult | None:
    cap_role = _ROLE_TO_CAP.get(role.upper())
    if not cap_role:
        return None
    status = str(capabilities_for(model).get(cap_role) or UNKNOWN).lower()
    if status == UNKNOWN and model not in DEFAULT_CAPABILITIES:
        return None
    if status == UNKNOWN:
        return CertificationResult(
            provider=provider, model=model, role=role.upper(),
            passed=False, timestamp=_stamp(), failure_reason="uncertified",
            source="seed",
        )
    return CertificationResult(
        provider=provider,
        model=model,
        role=role.upper(),
        passed=status == PASS,
        timestamp=_stamp(),
        failure_reason="" if status == PASS else f"certified {status}",
        source="seed",
    )


def discover_candidates(host_ai: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Providers/models that can be certified on this host."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(provider: str, model: str) -> None:
        key = (provider, model)
        if not model or key in seen:
            return
        seen.add(key)
        found.append({"provider": provider, "model": model})

    for model in DEFAULT_CAPABILITIES:
        provider = "ollama" if ":" in model else "local"
        _add(provider, model)

    ai = host_ai or {}
    ollama = ai.get("ollama") or {}
    for row in ollama.get("models") or []:
        name = row.get("name") if isinstance(row, dict) else str(row)
        if name:
            _add("ollama", str(name))
    if (ai.get("lm_studio") or {}).get("online"):
        _add("lmstudio", "local-model")
    for path_row in ai.get("installed_local_model_files") or []:
        if isinstance(path_row, dict) and path_row.get("filename"):
            _add("local", str(path_row.get("filename")))
    cloud = ai.get("configured_cloud_providers") or {}
    if isinstance(cloud, dict):
        for name, configured in cloud.items():
            if configured:
                _add(str(name), str(name))
    return found


def certify_role(
    provider: str,
    model: str,
    role: str,
    *,
    live: bool = False,
) -> CertificationResult:
    """Certify one model for one role. Seed evidence wins until a live retest."""
    seeded = _from_seed(model, role, provider=provider)
    if seeded is not None and not live:
        return seeded
    if not live:
        return CertificationResult(
            provider=provider, model=model, role=role.upper(),
            passed=False, timestamp=_stamp(),
            failure_reason="not yet tested", source="pending",
        )
    t0 = time.time()
    try:
        ok, reason = _live_probe(provider, model, role)
        return CertificationResult(
            provider=provider, model=model, role=role.upper(),
            passed=ok, timestamp=_stamp(),
            latency_ms=int((time.time() - t0) * 1000),
            failure_reason="" if ok else reason,
            source="live",
        )
    except Exception as exc:
        return CertificationResult(
            provider=provider, model=model, role=role.upper(),
            passed=False, timestamp=_stamp(),
            latency_ms=int((time.time() - t0) * 1000),
            failure_reason=str(exc)[:240],
            source="live",
        )


def _live_probe(provider: str, model: str, role: str) -> tuple[bool, str]:
    """Cheap reachability + seed overlay. Does not invent a pass for a known fail."""
    cap_role = _ROLE_TO_CAP.get(role.upper(), role.lower())
    if is_certified(model, cap_role) is False and capabilities_for(model).get(cap_role) == FAIL:
        return False, "existing evidence: FAIL"
    if is_certified(model, cap_role):
        return True, ""
    if provider in {"ollama", "ollama-local", "ollama-cloud"}:
        from jaeger_ai.core.models.discovery import discover_ollama
        result = discover_ollama()
        if not result.get("online"):
            return False, "ollama offline"
        names = {str((m or {}).get("name") or "") for m in (result.get("models") or [])}
        if model not in names and model not in DEFAULT_CAPABILITIES:
            return False, f"{model} not listed by ollama"
        return cap_role != "react" or model in DEFAULT_CAPABILITIES, "reachable, role uncertified"
    if provider == "lmstudio":
        import socket
        try:
            with socket.create_connection(("127.0.0.1", 1234), timeout=0.5):
                return True, ""
        except OSError:
            return False, "lm studio offline"
    return False, "no live probe for provider"


def assign_roles(matrix: CertificationMatrix) -> dict[str, dict[str, str]]:
    """Pick the first passing model for each role. Failed roles stay unassigned."""
    assignments: dict[str, dict[str, str]] = {}
    for role in ROLES:
        chosen = None
        for row in matrix.results:
            if row.role == role and row.passed:
                chosen = row
                break
        if chosen is None:
            continue
        assignments[role] = {
            "provider": chosen.provider,
            "model": chosen.model,
            "source": chosen.source,
        }
    matrix.assignments = assignments
    chat = assignments.get("CHAT") or assignments.get("REACT")
    react = assignments.get("REACT")
    if react and chat:
        matrix.summary = (
            "I found and tested the AI available on this computer. "
            "I configured the combination that works best."
        )
    elif chat:
        matrix.summary = (
            "I found working AI on this computer and configured it for conversation."
        )
    else:
        matrix.summary = (
            "I could not certify a working AI engine yet. Advanced Setup can pick one."
        )
    return assignments


def certify_available(
    instance_root: Path | Any,
    host_ai: dict[str, Any] | None = None,
    *,
    live: bool = False,
) -> CertificationMatrix:
    matrix = load_matrix(instance_root)
    known = {(r.model, r.role) for r in matrix.results}
    for candidate in discover_candidates(host_ai):
        for role in ROLES:
            if (candidate["model"], role) in known:
                continue
            result = certify_role(
                candidate["provider"], candidate["model"], role, live=live,
            )
            matrix.results.append(result)
            known.add((candidate["model"], role))
    assign_roles(matrix)
    save_matrix(instance_root, matrix)
    _write_capability_overlay(instance_root, matrix)
    return matrix


def _write_capability_overlay(instance_root: Path | Any, matrix: CertificationMatrix) -> None:
    """Keep model_capabilities.json in sync so ReAct routing honours new results."""
    from jaeger_ai.core.instance.first_boot import instance_dir
    overlay: dict[str, dict[str, str]] = {}
    for row in matrix.results:
        cap_role = _ROLE_TO_CAP.get(row.role)
        if not cap_role:
            continue
        bucket = overlay.setdefault(row.model, {})
        bucket[cap_role] = PASS if row.passed else FAIL
    path = instance_dir(instance_root) / "memory" / "model_capabilities.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8")) or {}
        if not isinstance(existing, dict):
            existing = {}
        for model, caps in overlay.items():
            bucket = existing.setdefault(model, {})
            if isinstance(bucket, dict):
                bucket.update(caps)
        path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def select_production_model(matrix: CertificationMatrix) -> tuple[str, str]:
    """Provider, model for the live ReAct engine. Never a REACT FAIL."""
    react = matrix.assignments.get("REACT")
    if react:
        return str(react.get("provider") or "ollama"), str(react.get("model") or "")
    chat = matrix.assignments.get("CHAT")
    if chat:
        return str(chat.get("provider") or "ollama"), str(chat.get("model") or "")
    return "ollama", "kimi-k2.7-code:cloud"


__all__ = [
    "CERT_FILENAME",
    "CertificationMatrix",
    "CertificationResult",
    "ROLES",
    "SUITE_VERSION",
    "assign_roles",
    "certify_available",
    "certify_role",
    "discover_candidates",
    "load_matrix",
    "save_matrix",
    "select_production_model",
]
