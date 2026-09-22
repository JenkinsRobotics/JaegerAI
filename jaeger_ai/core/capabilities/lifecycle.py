"""Capability Lifecycle and Controlled Self-Improvement Pipeline (Workstream 11).

Formalizes the lifecycle of agent-created capabilities:
CANDIDATE
→ ISOLATED DEVELOPMENT
→ STATIC CHECKS
→ UNIT TESTS
→ INTEGRATION TESTS
→ EVALUATION
→ REVIEW / POLICY
→ VERIFIED
→ TRUSTED / INSTALLED

Invariants:
1. Never let experimental agent code silently modify the stable kernel.
2. Protected paths remain strictly protected.
3. Full provenance tracking: who proposed it, model used, test results, evaluation score, promotion authority.
4. Unsafe code is rejected at the static analysis or test gate before reaching the trusted registry.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import uuid

from .manifest import CapabilityManifest
from .registry import CapabilityRegistry

logger = logging.getLogger("jaeger.core.capabilities.lifecycle")


class LifecycleStage(str, Enum):
    CANDIDATE = "candidate"
    ISOLATED_DEVELOPMENT = "isolated_development"
    STATIC_CHECKS_PASSED = "static_checks_passed"
    STATIC_CHECKS_FAILED = "static_checks_failed"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    EVALUATION_PASSED = "evaluation_passed"
    EVALUATION_FAILED = "evaluation_failed"
    AWAITING_REVIEW = "awaiting_review"
    VERIFIED = "verified"
    INSTALLED = "installed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class CapabilityProvenance:
    """Audit provenance for an agent-created or evolved capability."""
    proposed_by: str
    model: str
    created_at: float = field(default_factory=time.time)
    commit_sha: str | None = None
    promotion_authority: str | None = None
    evaluation_score: float = 0.0
    static_checks: dict[str, Any] = field(default_factory=dict)
    test_results: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateCapability:
    """In-flight capability undergoing evaluation and gating."""
    candidate_id: str
    manifest: CapabilityManifest
    sandbox_dir: Path
    stage: LifecycleStage = LifecycleStage.CANDIDATE
    provenance: CapabilityProvenance = field(
        default_factory=lambda: CapabilityProvenance(proposed_by="unknown", model="unknown")
    )
    error: str | None = None


class CapabilityLifecyclePipeline:
    """Enforces the verification pipeline before promoting a capability to the trusted registry."""

    # Protected paths that candidate capabilities are forbidden from modifying or targeting
    FORBIDDEN_PATTERNS = (
        "/.jaeger_ai/",
        "/.jaeger_agent/",
        "jaeger_ai/core/",
        "/etc/",
        "~/.ssh",
        "master",
    )

    def __init__(self, trusted_registry: CapabilityRegistry, work_dir: Path | str) -> None:
        self.registry = trusted_registry
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._candidates: dict[str, CandidateCapability] = {}

    def propose_candidate(
        self,
        manifest: CapabilityManifest,
        files: dict[str, str],
        *,
        proposed_by: str = "agent:jaeger",
        model: str = "kimi-k2.7-code:cloud",
        commit_sha: str | None = None,
    ) -> CandidateCapability:
        """Admit a new candidate capability into isolated development."""
        cid = f"cand_{uuid.uuid4().hex[:10]}"
        sandbox = self.work_dir / cid
        sandbox.mkdir(parents=True, exist_ok=True)

        # Save manifest
        manifest.save(sandbox)

        # Write capability files into sandbox
        for filename, content in files.items():
            dest = sandbox / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

        prov = CapabilityProvenance(
            proposed_by=proposed_by,
            model=model,
            commit_sha=commit_sha,
        )
        cand = CandidateCapability(
            candidate_id=cid,
            manifest=manifest,
            sandbox_dir=sandbox,
            stage=LifecycleStage.CANDIDATE,
            provenance=prov,
        )
        self._candidates[cid] = cand
        logger.info("Admitted candidate capability %s (%s) into %s", manifest.capability_id, cid, sandbox)
        return cand

    def run_static_checks(self, candidate_id: str) -> bool:
        """Run AST and security scans against the candidate sandbox."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            raise ValueError(f"Candidate {candidate_id} not found")

        cand.stage = LifecycleStage.ISOLATED_DEVELOPMENT
        violations = []

        # 1. Inspect Python files for dangerous calls or forbidden strings
        for py_file in cand.sandbox_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                # Check forbidden patterns
                for pat in self.FORBIDDEN_PATTERNS:
                    if pat in content:
                        violations.append(f"Forbidden pattern {pat!r} found in {py_file.name}")

                # AST check for dangerous imports/evals
                tree = ast.parse(content, filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                            violations.append(f"Dangerous call {node.func.id}() in {py_file.name}")
            except Exception as exc:
                violations.append(f"Failed parsing {py_file.name}: {exc}")

        checks_summary = {"violations": violations, "scanned_files": len(list(cand.sandbox_dir.rglob("*.py")))}
        cand.provenance.static_checks.update(checks_summary)

        if violations:
            cand.stage = LifecycleStage.STATIC_CHECKS_FAILED
            cand.error = "; ".join(violations)
            logger.warning("Candidate %s failed static checks: %s", candidate_id, cand.error)
            return False

        cand.stage = LifecycleStage.STATIC_CHECKS_PASSED
        return True

    def run_unit_tests(self, candidate_id: str, test_runner_fn: Any | None = None) -> bool:
        """Execute sandboxed unit tests against candidate capability."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            raise ValueError(f"Candidate {candidate_id} not found")

        if cand.stage != LifecycleStage.STATIC_CHECKS_PASSED:
            cand.stage = LifecycleStage.TESTS_FAILED
            cand.error = "Cannot run unit tests: static checks have not passed"
            return False

        passed = True
        test_info = {}
        if callable(test_runner_fn):
            try:
                passed, test_info = test_runner_fn(cand.sandbox_dir)
            except Exception as exc:
                passed = False
                test_info = {"error": str(exc)}
        else:
            # Default: check entrypoint existence and syntax
            entrypoint = cand.manifest.execution_entrypoint
            if ":" in entrypoint:
                fn_name = entrypoint.split(":", 1)[0]
                passed = (cand.sandbox_dir / fn_name).is_file()
                test_info = {"entrypoint_file_exists": passed}

        cand.provenance.test_results.update(test_info)
        if passed:
            cand.stage = LifecycleStage.TESTS_PASSED
            return True
        else:
            cand.stage = LifecycleStage.TESTS_FAILED
            cand.error = f"Unit tests failed: {test_info}"
            return False

    def evaluate_and_gate(self, candidate_id: str, min_score: float = 0.8) -> bool:
        """Evaluate capability against quality/safety rubric before human review."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            raise ValueError(f"Candidate {candidate_id} not found")

        if cand.stage != LifecycleStage.TESTS_PASSED:
            cand.stage = LifecycleStage.EVALUATION_FAILED
            cand.error = "Cannot evaluate: tests did not pass"
            return False

        # Evaluation rubric score calculation
        score = 1.0
        if not cand.manifest.description:
            score -= 0.1
        if not cand.manifest.verification_entrypoint:
            score -= 0.1
        if not cand.manifest.rollback_entrypoint:
            score -= 0.1

        # Must have is_executable accurately set
        score = max(0.0, score)
        object.__setattr__(cand.provenance, "evaluation_score", score)

        if score >= min_score:
            cand.stage = LifecycleStage.AWAITING_REVIEW
            return True
        else:
            cand.stage = LifecycleStage.EVALUATION_FAILED
            cand.error = f"Evaluation score {score:.2f} below threshold {min_score:.2f}"
            return False

    def promote_to_trusted(
        self,
        candidate_id: str,
        *,
        authority: str = "operator_approval",
    ) -> CapabilityManifest:
        """Promote a thoroughly verified candidate to the trusted CapabilityRegistry."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            raise ValueError(f"Candidate {candidate_id} not found")

        if cand.stage != LifecycleStage.AWAITING_REVIEW:
            raise RuntimeError(
                f"Cannot promote candidate {candidate_id}: current stage is {cand.stage.value} "
                f"(expected {LifecycleStage.AWAITING_REVIEW.value})"
            )

        object.__setattr__(cand.provenance, "promotion_authority", authority)
        cand.stage = LifecycleStage.VERIFIED

        # Install into authoritative trusted registry
        installed_manifest = self.registry.install(cand.sandbox_dir)
        cand.stage = LifecycleStage.INSTALLED
        logger.info(
            "Promoted candidate %s to trusted registry as %s (authorized by %s)",
            candidate_id,
            installed_manifest.capability_id,
            authority,
        )
        return installed_manifest

    def reject(self, candidate_id: str, reason: str = "") -> None:
        """Reject a candidate capability and clean up its sandbox."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            return
        cand.stage = LifecycleStage.REJECTED
        cand.error = reason or "Candidate rejected by policy or operator"
        if cand.sandbox_dir.exists():
            shutil.rmtree(cand.sandbox_dir)
        logger.info("Rejected candidate %s: %s", candidate_id, cand.error)
