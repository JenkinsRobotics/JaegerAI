"""Tests for the Programmable Capability Layer (Workstream 10).

Verifies Exit Criteria:
1. Manifest structure contains ID, version, permissions, dependencies, tools,
   triggers, preconditions, execution, verification, rollback, and provenance.
2. Differentiates lightweight procedural skills from executable capabilities.
3. A capability package can be installed without editing EntityRuntime.
4. Capability is executed dynamically, independently verified, rolled back, and removed.
"""
from pathlib import Path
import tempfile
import pytest

from jaeger_ai.core.capabilities.manifest import CapabilityManifest
from jaeger_ai.core.capabilities.registry import CapabilityError, CapabilityRegistry


@pytest.fixture
def temp_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield CapabilityRegistry(Path(tmpdir) / "capabilities")


def test_manifest_serialization():
    manifest = CapabilityManifest(
        capability_id="cap.tools.text_transformer",
        name="Text Transformer",
        version="1.2.0",
        category="tool_adapter",
        description="Transforms text to uppercase and reverses strings",
        permissions=("filesystem:read",),
        dependencies=("python>=3.11",),
        tools=("uppercase", "reverse"),
        triggers=("text_transform",),
        preconditions=("environment_ready",),
        execution_entrypoint="executor.py:transform",
        verification_entrypoint="verifier.py:verify_transform",
        rollback_entrypoint="rollback.py:revert",
        provenance="operator_installed",
        is_executable=True,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "manifest.yaml"
        manifest.save(file_path)

        loaded = CapabilityManifest.load(file_path)
        assert loaded.capability_id == "cap.tools.text_transformer"
        assert loaded.name == "Text Transformer"
        assert loaded.version == "1.2.0"
        assert "uppercase" in loaded.tools
        assert loaded.is_executable is True


def test_procedural_skill_vs_executable_capability(temp_registry: CapabilityRegistry):
    """Lightweight procedural skill cannot be directly executed as code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "playbook_skill"
        pkg_dir.mkdir()

        manifest = CapabilityManifest(
            capability_id="skill.procedural.git_hygiene",
            name="Git Hygiene Playbook",
            category="skill",
            description="Guidelines for atomic git commits",
            is_executable=False,
        )
        manifest.save(pkg_dir)

        temp_registry.install(pkg_dir)
        installed = temp_registry.get("skill.procedural.git_hygiene")
        assert installed is not None
        assert installed.is_executable is False

        with pytest.raises(CapabilityError) as exc_info:
            temp_registry.execute("skill.procedural.git_hygiene", {})
        assert "procedural skill" in str(exc_info.value)


def test_install_execute_verify_rollback_uninstall_lifecycle(temp_registry: CapabilityRegistry):
    """Install, execute, verify, rollback, and remove an executable capability without core edits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "sample_cap"
        pkg_dir.mkdir()

        # 1. Manifest
        manifest = CapabilityManifest(
            capability_id="cap.integration.calc",
            name="Calculator Integration",
            version="2.0.0",
            category="integration",
            description="Multiplies numbers and logs results",
            permissions=("compute:math",),
            tools=("multiply",),
            execution_entrypoint="executor.py:compute",
            verification_entrypoint="verifier.py:verify_result",
            rollback_entrypoint="rollback.py:undo",
            provenance="agent_created",
            is_executable=True,
        )
        manifest.save(pkg_dir)

        # 2. Execution logic
        (pkg_dir / "executor.py").write_text(
            """
def compute(arguments, context=None):
    a = arguments.get("a", 0)
    b = arguments.get("b", 0)
    return {"result": a * b, "operation": "multiplication"}
""",
            encoding="utf-8",
        )

        # 3. Verification logic
        (pkg_dir / "verifier.py").write_text(
            """
def verify_result(exec_result, context=None):
    if exec_result.get("operation") == "multiplication":
        return True, "Operation math verified independently"
    return False, "Math mismatch"
""",
            encoding="utf-8",
        )

        # 4. Rollback logic
        (pkg_dir / "rollback.py").write_text(
            """
def undo(exec_result, context=None):
    # Revert state/logs
    return True
""",
            encoding="utf-8",
        )

        # ── Step A: Install ──────────────────────────────────────────────────
        installed = temp_registry.install(pkg_dir)
        assert installed.capability_id == "cap.integration.calc"
        assert len(temp_registry.list_all()) == 1

        # ── Step B: Execute ──────────────────────────────────────────────────
        out = temp_registry.execute("cap.integration.calc", {"a": 7, "b": 6})
        assert out["result"] == 42
        assert out["operation"] == "multiplication"

        # ── Step C: Verify ───────────────────────────────────────────────────
        ok, evidence = temp_registry.verify("cap.integration.calc", out)
        assert ok is True
        assert "Operation math verified" in evidence

        # ── Step D: Rollback ─────────────────────────────────────────────────
        reverted = temp_registry.rollback("cap.integration.calc", out)
        assert reverted is True

        # ── Step E: Uninstall ────────────────────────────────────────────────
        removed = temp_registry.uninstall("cap.integration.calc")
        assert removed is True
        assert temp_registry.get("cap.integration.calc") is None
        assert len(temp_registry.list_all()) == 0
