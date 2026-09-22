"""Workstream 21 — test-runner tiers are real, documented, and honest.

A contributor must be able to read ``dev/scripts/run_tests.sh`` and know
what passing each flag actually proves. This test pins the flag surface
and refuses silent drift back to unit files posing as production-path.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parents[4]
RUNNER = REPO / "dev/scripts/run_tests.sh"
DOCTRINE = REPO / "docs/architecture/TEST_ARCHITECTURE.md"

REQUIRED_FLAGS = (
    "--smoke",
    "--unit",
    "--integration",
    "--production-path",
    "--acceptance",
    "--security",
    "--fault-injection",
    "--external-eval",
    "--soak",
    "--full",
)

PRODUCTION_PATH_FILES = (
    "dev/tests/jaeger_ai/core/test_execution_lifecycle.py",
    "dev/tests/jaeger_ai/core/test_control_plane_consolidation.py",
    "dev/tests/jaeger_ai/core/test_runtime_truth.py",
    "dev/tests/jaeger_ai/core/test_effects_verification.py",
    "dev/tests/jaeger_ai/core/test_policy_kernel.py",
    "dev/tests/jaeger_ai/core/test_architecture_boundary_purity.py",
    "dev/tests/jaeger_ai/core/test_state_ownership.py",
    "dev/tests/test_upaa_production_runtime.py",
)

SECURITY_PATHS = (
    "dev/tests/jaeger_ai/core/test_security_hardening.py",
    "dev/tests/jaeger_ai/core/test_skills_guard.py",
    "dev/tests/jaeger_ai/interfaces/test_legacy_adapters_security.py",
    "packages/jaeger-agent/tests/security/",
)


def _runner_text() -> str:
    assert RUNNER.is_file(), f"missing test runner at {RUNNER}"
    return RUNNER.read_text(encoding="utf-8")


def test_runner_is_executable_and_documents_every_tier():
    text = _runner_text()
    assert RUNNER.stat().st_mode & 0o111, "run_tests.sh must be executable"
    for flag in REQUIRED_FLAGS:
        assert flag in text, f"tier flag {flag} missing from run_tests.sh"
        assert flag in DOCTRINE.read_text(encoding="utf-8"), (
            f"tier flag {flag} missing from TEST_ARCHITECTURE.md"
        )


def test_run_packages_is_the_package_suite_gate():
    """Empty MARKER_EXPR must not silently re-enable package suites."""
    text = _runner_text()
    assert "RUN_PACKAGES" in text
    assert re.search(r'if \[ "\$RUN_PACKAGES" -eq 1 \]', text), (
        "package suites must key off RUN_PACKAGES, not empty MARKER_EXPR"
    )


def test_production_path_is_not_only_unit_kernel_files():
    text = _runner_text()
    case = text.split("--production-path)", 1)[1].split(";;", 1)[0]
    for path in PRODUCTION_PATH_FILES:
        assert path in case, f"production-path omitted {path}"
        assert (REPO / path).is_file(), f"production-path target missing: {path}"
    # Honesty: two PolicyKernel/effects files alone are not a production path.
    assert "test_control_plane_consolidation.py" in case
    assert "test_runtime_truth.py" in case
    assert "test_execution_lifecycle.py" in case


def test_security_tier_covers_agent_shell_hooks_and_webui_adapters():
    text = _runner_text()
    case = text.split("--security)", 1)[1].split(";;", 1)[0]
    for path in SECURITY_PATHS:
        assert path in case, f"security tier omitted {path}"
        target = REPO / path.rstrip("/")
        assert target.exists(), f"security target missing: {path}"


def test_soak_targets_named_soak_test_not_the_whole_tree():
    text = _runner_text()
    case = text.split("--soak)", 1)[1].split(";;", 1)[0]
    assert "test_fault_injection_and_resilience.py" in case
    assert '"-k"' in case or " -k " in case
    assert "soak" in case


def test_acceptance_is_the_live_webui_suite():
    text = _runner_text()
    case = text.split("--acceptance)", 1)[1].split(";;", 1)[0]
    assert "dev/tests/acceptance/" in case
    assert (REPO / "dev/tests/acceptance").is_dir()


def test_doctrine_refuses_mock_as_production_proof():
    doctrine = DOCTRINE.read_text(encoding="utf-8")
    assert "MOCK PASS != PRODUCTION VERIFICATION" in doctrine
    assert "Does **not** prove live WebUI" in doctrine or "does **not** prove live WebUI" in doctrine
