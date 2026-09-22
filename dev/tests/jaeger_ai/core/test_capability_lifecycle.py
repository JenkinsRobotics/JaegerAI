"""Tests for Capability Lifecycle and Controlled Self-Improvement (Workstream 11).

Verifies Invariants:
1. Complete lifecycle: CANDIDATE -> STATIC CHECKS -> TESTS -> EVALUATION -> REVIEW -> VERIFIED -> INSTALLED
2. Never let experimental agent code silently modify the stable kernel or protected paths.
3. Unsafe code (e.g. eval/exec or targeting jaeger_ai/core/) is rejected at static checks.
4. Test failure halts promotion.
5. Promotion without passing prior gates is refused.
6. Full audit provenance is tracked.
"""
from pathlib import Path
import tempfile
import pytest

from jaeger_ai.core.capabilities.lifecycle import (
    CapabilityLifecyclePipeline,
    LifecycleStage,
)
from jaeger_ai.core.capabilities.manifest import CapabilityManifest
from jaeger_ai.core.capabilities.registry import CapabilityRegistry


@pytest.fixture
def lifecycle_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        reg = CapabilityRegistry(base / "trusted_registry")
        pipeline = CapabilityLifecyclePipeline(reg, base / "candidate_worktrees")
        yield pipeline, reg


def test_full_candidate_lifecycle_to_promotion(lifecycle_env):
    """A safe, well-formed candidate successfully navigates all gates to promotion."""
    pipeline, registry = lifecycle_env

    manifest = CapabilityManifest(
        capability_id="cap.integration.csv_parser",
        name="CSV Parser",
        version="1.0.0",
        category="tool_adapter",
        description="Parses CSV records safely into dictionaries",
        execution_entrypoint="executor.py:parse",
        verification_entrypoint="verifier.py:verify_parse",
        rollback_entrypoint="rollback.py:clean",
    )

    files = {
        "executor.py": "def parse(args, context=None): return {'rows': len(args.get('text', '').splitlines())}",
        "verifier.py": "def verify_parse(res, context=None): return res.get('rows', 0) >= 0",
        "rollback.py": "def clean(res, context=None): return True",
    }

    # 1. Propose candidate
    cand = pipeline.propose_candidate(
        manifest,
        files,
        proposed_by="agent:jaeger",
        model="kimi-k2.7-code:cloud",
        commit_sha="b8c9312b",
    )
    assert cand.stage == LifecycleStage.CANDIDATE
    assert cand.provenance.model == "kimi-k2.7-code:cloud"
    assert cand.provenance.proposed_by == "agent:jaeger"

    # 2. Static checks
    assert pipeline.run_static_checks(cand.candidate_id) is True
    assert cand.stage == LifecycleStage.STATIC_CHECKS_PASSED

    # 3. Unit tests
    def dummy_tests(sandbox_dir: Path):
        return True, {"tests_passed": 2, "duration": 0.05}

    assert pipeline.run_unit_tests(cand.candidate_id, dummy_tests) is True
    assert cand.stage == LifecycleStage.TESTS_PASSED

    # 4. Evaluation
    assert pipeline.evaluate_and_gate(cand.candidate_id) is True
    assert cand.stage == LifecycleStage.AWAITING_REVIEW
    assert cand.provenance.evaluation_score >= 0.8

    # 5. Promotion
    installed = pipeline.promote_to_trusted(cand.candidate_id, authority="operator_matthew")
    assert cand.stage == LifecycleStage.INSTALLED
    assert cand.provenance.promotion_authority == "operator_matthew"
    assert registry.get("cap.integration.csv_parser") is not None


def test_reject_forbidden_target_modification(lifecycle_env):
    """Candidate attempting to target jaeger_ai/core/ is rejected at static checks."""
    pipeline, registry = lifecycle_env

    manifest = CapabilityManifest(
        capability_id="cap.exploit.core_override",
        name="Core Override Exploit",
        description="Attempts to modify core engine files",
    )

    files = {
        "executor.py": "target = 'jaeger_ai/core/entity/runtime.py'\nwith open(target, 'w') as f: f.write('hacked')",
    }

    cand = pipeline.propose_candidate(manifest, files)
    assert pipeline.run_static_checks(cand.candidate_id) is False
    assert cand.stage == LifecycleStage.STATIC_CHECKS_FAILED
    assert "Forbidden pattern 'jaeger_ai/core/'" in cand.error

    # Attempting promotion fails immediately
    with pytest.raises(RuntimeError):
        pipeline.promote_to_trusted(cand.candidate_id)


def test_reject_dangerous_eval_construct(lifecycle_env):
    """Candidate using eval() or exec() fails static checks."""
    pipeline, registry = lifecycle_env

    manifest = CapabilityManifest(
        capability_id="cap.exploit.eval_runner",
        name="Eval Runner",
    )
    files = {
        "executor.py": "def run(args): eval(args['code'])",
    }

    cand = pipeline.propose_candidate(manifest, files)
    assert pipeline.run_static_checks(cand.candidate_id) is False
    assert cand.stage == LifecycleStage.STATIC_CHECKS_FAILED
    assert "Dangerous call eval()" in cand.error


def test_unit_test_failure_blocks_promotion(lifecycle_env):
    """Failing unit tests stops the lifecycle pipeline."""
    pipeline, registry = lifecycle_env

    manifest = CapabilityManifest(
        capability_id="cap.tools.broken_calc",
        name="Broken Calc",
    )
    files = {"executor.py": "def calc(args): return 1 / 0"}

    cand = pipeline.propose_candidate(manifest, files)
    assert pipeline.run_static_checks(cand.candidate_id) is True

    def failing_tests(sandbox_dir: Path):
        return False, {"error": "ZeroDivisionError: division by zero"}

    assert pipeline.run_unit_tests(cand.candidate_id, failing_tests) is False
    assert cand.stage == LifecycleStage.TESTS_FAILED

    with pytest.raises(RuntimeError):
        pipeline.promote_to_trusted(cand.candidate_id)
