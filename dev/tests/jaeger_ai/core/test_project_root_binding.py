"""A workspace switch reaches the agent's tools.

ARES has always had a workspace selector, and it has always been a lie on the
JaegerAI backend. The value propagated correctly the whole way — UI to session
to bridge frame to ``_turn_workspace`` — and then stopped, because the only
thing it bound was ``workspace_override``, which governs exactly one behaviour:
where writes whose path literally begins ``workspace/`` are filed.

Everything a person means by "work in this directory" ignored it:

  * ``run_shell`` ran in a fresh ``TemporaryDirectory``, always
  * ``_resolve_read`` resolved relative paths against ``Path.cwd()`` — for an
    app launched from Finder, the user's home
  * ``grep_files(".")`` searched ``<instance>/skills``

``project_root`` is the missing concept. These tests hold the two bindings
apart, because collapsing them is how this bug happens again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_agent import workspace as ws


@pytest.fixture
def allow_shell():
    """run_shell is tier-4 PRIVILEGED, so it asks before it runs.

    These tests are about WHERE the command runs, not whether it is permitted;
    the gate itself is covered by the permissions suite. Same pattern as
    test_tool_interrupt.
    """
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        use_policy,
    )

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "my-project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("PROJECT_MARKER = 1\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _restore_binding():
    before = ws.get_project_root()
    yield
    ws.set_project_root(before)


def test_unbound_by_default(project):
    ws.set_project_root(None)
    assert ws.get_project_root() is None


def test_binding_requires_a_real_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        ws.set_project_root(tmp_path / "does-not-exist")
    with pytest.raises(ValueError, match="not a directory"):
        ws.set_project_root(tmp_path / "does-not-exist" / "deeper")


def test_binding_resolves_and_expands(project):
    ws.set_project_root(str(project))
    assert ws.get_project_root() == project.resolve()


def test_run_shell_runs_inside_the_bound_project(project, allow_shell):
    """The headline behaviour. ``pwd`` is the whole assertion."""
    from jaeger_agent.tools.code import run_shell

    ws.set_project_root(project)
    result = run_shell("pwd")
    assert result["ok"] is True, result
    assert Path(result["stdout"].strip()).resolve() == project.resolve()


def test_run_shell_sees_project_files(project, allow_shell):
    from jaeger_agent.tools.code import run_shell

    ws.set_project_root(project)
    result = run_shell("cat src/main.py")
    assert "PROJECT_MARKER" in result["stdout"]


def test_run_shell_still_uses_a_scratch_dir_when_unbound(project, allow_shell):
    """The pre-existing behaviour must survive for surfaces with no project.

    A surface that never selects one has to behave exactly as it did before
    this concept existed, or the change is a regression dressed as a feature.
    """
    from jaeger_agent.tools.code import run_shell

    ws.set_project_root(None)
    result = run_shell("pwd")
    assert result["ok"] is True, result
    where = Path(result["stdout"].strip()).resolve()
    assert where != project.resolve()
    assert "jaeger_shell_" in str(where)


def test_relative_reads_resolve_against_the_project(project, monkeypatch, tmp_path):
    """Not against wherever the process happened to be launched."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    ws.set_project_root(project)
    assert ws._resolve_read("src/main.py") == (project / "src" / "main.py").resolve()


def test_relative_reads_fall_back_to_cwd_when_the_project_lacks_the_file(
    project, monkeypatch, tmp_path
):
    """A bound project must not make previously-readable paths unreadable."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "only-here.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(elsewhere)

    ws.set_project_root(project)
    assert ws._resolve_read("only-here.txt") == (elsewhere / "only-here.txt").resolve()


def test_project_root_and_workspace_override_stay_separate(project, tmp_path):
    """The conflation that caused the original bug.

    ``workspace_override`` is where generated OUTPUT is filed.
    ``project_root`` is which codebase the agent is looking at. Binding one
    must never imply the other.
    """
    outputs = tmp_path / "Jaeger Outputs"

    class _Layout:
        root = tmp_path / "inst"
        logs_dir = tmp_path / "inst" / "logs"
        skills_dir = tmp_path / "inst" / "skills"
        memory_dir = tmp_path / "inst" / "memory"
        workspace_dir = tmp_path / "inst" / "workspace"
        audit_log_path = tmp_path / "inst" / "logs" / "audit.log"
        config_path = tmp_path / "inst" / "config.yaml"
        identity_path = tmp_path / "inst" / "identity.yaml"

    for attr in ("logs_dir", "skills_dir", "memory_dir", "workspace_dir"):
        getattr(_Layout, attr).mkdir(parents=True, exist_ok=True)

    ws.bind(_Layout(), workspace_override=outputs, project_root=project)
    assert ws.get_effective_workspace_dir() == outputs.resolve()
    assert ws.get_project_root() == project.resolve()
    assert ws.get_effective_workspace_dir() != ws.get_project_root()

    # Binding only the override must leave the project unbound, which is
    # precisely the state every caller was in before this parameter existed.
    ws.bind(_Layout(), workspace_override=outputs)
    assert ws.get_project_root() is None


def test_the_bridge_binds_project_root_per_turn():
    """``_turn_workspace`` is the one place ARES's selection lands."""
    source = Path(
        __file__
    ).resolve().parents[3].parent.joinpath(
        "jaeger_ai/interfaces/bridge.py"
    ).read_text(encoding="utf-8")
    assert "project_root=candidate" in source, (
        "_turn_workspace no longer binds the project root — an ARES workspace "
        "switch would silently stop reaching the agent's tools again"
    )
