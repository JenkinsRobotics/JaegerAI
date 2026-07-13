"""0.9.3 Task 5 — `jaeger doctor` renders skipped skills with a fix.

``run_doctor(layout)`` now folds in one Check per skipped skill
(category ``"skills"``) via ``doctor._skill_skip_checks`` — a fabricated
failing skill (import error) should show up with an actionable
``pip install`` fix; deliberate skips (disabled by config) should not
clutter the report.
"""

from __future__ import annotations

import pathlib
import tempfile
import textwrap

from jaeger_ai.agent.skill_registry.skill_loader import reset_registered
from jaeger_ai.core.diagnostics.doctor import run_doctor
from jaeger_ai.core.instance.instance import InstanceLayout


def _fresh_layout() -> InstanceLayout:
    root = pathlib.Path(tempfile.mkdtemp(prefix="jaeger-doctor-test-"))
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    for name in ("identity.yaml", "config.yaml", "manifest.json"):
        (layout.root / name).write_text("{}", encoding="utf-8")
    return layout


def _write_broken_skill(layout: InstanceLayout, *, name: str, missing_pkg: str) -> None:
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


def test_doctor_renders_a_fabricated_failing_skill_with_a_pip_fix() -> None:
    layout = _fresh_layout()
    _write_broken_skill(layout, name="doctortestbroken", missing_pkg="totally_fake_doctor_pkg")
    reset_registered()
    try:
        checks = run_doctor(layout, deep=False, check_updates=False)
    finally:
        reset_registered()

    skill_checks = {c.name: c for c in checks if c.category == "skills"}
    assert "skill:doctortestbroken" in skill_checks
    c = skill_checks["skill:doctortestbroken"]
    assert c.ok is False
    assert "[import_error]" in c.detail
    assert "ModuleNotFoundError" in c.detail
    assert c.fix == "pip install totally_fake_doctor_pkg"
    assert c.fix_cmd == ["pip", "install", "totally_fake_doctor_pkg"]


def test_doctor_never_crashes_with_no_skips_present() -> None:
    """A clean instance (no fabricated failures) still returns a report —
    the skill-skip section degrades gracefully to "nothing to add"."""
    layout = _fresh_layout()
    reset_registered()
    try:
        checks = run_doctor(layout, deep=False, check_updates=False)
    finally:
        reset_registered()
    assert any(c.category == "skills" for c in checks)
