from __future__ import annotations

import pathlib
import tempfile
import textwrap

import pytest

from jaeger_ai.agent import clear_registry, has_tool
from jaeger_ai.agent.skill_registry.skill_loader import (
    _ToolCapturingAgent,
    classify_skip,
    last_skip_reason,
    load_and_register,
    reset_registered,
    skip_fix_hint,
)
from jaeger_ai.core.instance.instance import InstanceLayout


class _FakeAgent:
    """Legacy pydantic-ai stand-in; only used for attribute pass-through
    now (skills that read ``agent.model``, etc.). The capturing wrapper
    no longer forwards tool registrations to it."""


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def test_tool_capture_handles_bare_tool_plain() -> None:
    """The bare ``@agent.tool_plain`` form (no kwargs) lifts the function
    into the framework-free registry AND records it in the capturing
    wrapper's ``captured`` list (so the skill becomes its own toolset)."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain
    def demo_tool() -> dict:
        """Demo tool."""
        return {"ok": True}

    assert demo_tool() == {"ok": True}
    assert capturing.captured == ["demo_tool"]
    assert has_tool("demo_tool")


def test_tool_capture_handles_parameterized_tool_plain() -> None:
    """The ``@agent.tool_plain(retries=1)`` form still captures the
    function name. Legacy kwargs the new path doesn't understand
    (``retries``) are silently dropped — the new agent loop owns retry
    semantics now."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain(retries=1)
    def demo_tool() -> dict:
        """Demo tool."""
        return {"ok": True}

    assert demo_tool() == {"ok": True}
    assert capturing.captured == ["demo_tool"]
    assert has_tool("demo_tool")


def test_tool_capture_honours_name_override() -> None:
    """Skills that rename a tool via ``@agent.tool_plain(name=...)`` get
    the renamed registration."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain(name="custom_alias")
    def underlying_fn() -> dict:
        """Custom-named tool."""
        return {"ok": True}

    assert has_tool("custom_alias")
    assert not has_tool("underlying_fn")


# ── 0.9.3 Task 5 — dependency visibility ──────────────────────────


class _RegSentinel:
    """Same shape as ``main._RegistrationSentinel`` / ``doctor.
    _DoctorRegistrationSentinel`` — the loader only needs ``tool_plain``/
    ``tool`` to be callable."""

    def __getattr__(self, name: str):
        return lambda *a, **k: None


def _fresh_layout() -> InstanceLayout:
    root = pathlib.Path(tempfile.mkdtemp(prefix="jaeger-skill-loader-test-"))
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    return layout


def _write_broken_skill(layout: InstanceLayout, *, name: str, missing_pkg: str) -> None:
    """A fabricated instance-zone skill whose module import raises
    ``ModuleNotFoundError`` — the "import error class" case Task 5 calls
    out by name. Ships a trivial passing smoke test so the skip happens
    at IMPORT time (the ``import/register failed:`` path), not the
    "missing smoke test" gate."""
    folder = layout.skills_dir / f"{name}_v1"
    (folder / "tests").mkdir(parents=True)
    (folder / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: "fabricated failing skill — Task 5 test fixture"
        ---
        # {name}
        """), encoding="utf-8")
    (folder / f"{name}.py").write_text(
        f"import {missing_pkg}\n\ndef register(agent):\n    pass\n",
        encoding="utf-8",
    )
    (folder / "tests" / "smoke_test.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8",
    )


@pytest.mark.parametrize(
    "reason, expected_class",
    [
        ("disabled by config", "disabled"),
        ("package='reserved' / runtime='wasm' not implemented yet", "unsupported"),
        ("instance-zone skill has no tests/smoke_test.py — required for non-core code skills", "missing_smoke"),
        ("smoke test exit=1\nTraceback...\nModuleNotFoundError: No module named 'foo'", "smoke_fail"),
        ("safety scan: danger", "safety"),
        ("import/register failed: ModuleNotFoundError: No module named 'bar'\ntb", "import_error"),
        ("import/register failed: PermissionError: Operation not permitted\ntb", "permission"),
        ("no register(agent) callable in module", "other"),
    ],
)
def test_classify_skip_maps_every_reason_shape_this_module_emits(reason, expected_class) -> None:
    assert classify_skip(reason) == expected_class


def test_skip_fix_hint_derives_pip_install_from_module_not_found() -> None:
    reason = "import/register failed: ModuleNotFoundError: No module named 'totally_fake_pkg'\ntb"
    cls = classify_skip(reason)
    fix, fix_cmd = skip_fix_hint(skill=None, reason=reason, cls=cls)
    assert fix == "pip install totally_fake_pkg"
    assert fix_cmd == ["pip", "install", "totally_fake_pkg"]


def test_skip_fix_hint_permission_class_has_no_auto_fix_cmd() -> None:
    reason = "import/register failed: PermissionError: Operation not permitted\ntb"
    cls = classify_skip(reason)
    fix, fix_cmd = skip_fix_hint(skill=None, reason=reason, cls=cls)
    assert "System Settings" in fix
    assert fix_cmd == []


def test_fabricated_failing_skill_is_skipped_with_reason_recorded() -> None:
    """The 0.9.3 Task 5 walk case: a skill whose module can't import.
    The skip reason (a) leads with the exception CLASS name, not just
    the message, (b) classifies as import_error, and (c) is retrievable
    via last_skip_reason() by the self-model after this call."""
    layout = _fresh_layout()
    _write_broken_skill(layout, name="brokentool", missing_pkg="totally_not_a_real_package_xyz")
    reset_registered()
    try:
        report = load_and_register(_RegSentinel(), layout, run_smoke_tests=True)
    finally:
        reset_registered()

    skipped_by_name = {s.name: reason for s, reason in report.skipped}
    assert "brokentool" in skipped_by_name
    reason = skipped_by_name["brokentool"]
    assert reason.startswith("import/register failed: ModuleNotFoundError:")
    assert "totally_not_a_real_package_xyz" in reason
    assert classify_skip(reason) == "import_error"

    # last_skip_reason() is what the self-model reads to explain an
    # unavailable capability instead of silently omitting it.
    assert last_skip_reason("brokentool") == reason
    assert last_skip_reason("some_other_skill", "brokentool") == reason
    assert last_skip_reason("nonexistent") is None
