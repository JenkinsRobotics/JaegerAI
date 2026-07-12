"""INST-11 — ``<instance>/workspace/`` as the agent's general
scratch + outputs dir, separate from ``<instance>/skills/`` (which
stays code-modules-only).

The write tools (file_write / append_file / edit_file / delete_file)
route the lead path component:

  - ``workspace/...`` → ``<instance>/workspace/``
  - everything else  → ``<instance>/skills/`` (back-compat default)

These tests pin the routing + the layout shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.context import (
    SandboxError, _require_layout, _resolve_write,
)
import jaeger_ai.core.context as _common
from jaeger_ai.agent.tools import files as file_tools


# ── layout / ensure_dirs ────────────────────────────────────────────


def test_layout_exposes_workspace_dir(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    assert layout.workspace_dir == (tmp_path / "inst" / "workspace").resolve()


def test_ensure_dirs_creates_workspace(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir()
    layout.ensure_dirs()
    assert layout.workspace_dir.is_dir()
    # Pre-existing siblings still get created.
    assert layout.skills_dir.is_dir()
    assert layout.memory_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.credentials_dir.is_dir()


# ── _resolve_write routing ──────────────────────────────────────────


@pytest.fixture
def bound_layout(tmp_path, monkeypatch):
    """Bind a real layout into the tools' module-level singleton so
    ``_require_layout()`` resolves to ours."""
    root = tmp_path / "inst"
    root.mkdir()
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    monkeypatch.setattr(_common, "_layout", layout, raising=True)
    return layout


def test_resolve_write_routes_workspace_prefix(bound_layout):
    target = _resolve_write("workspace/report.md")
    assert target.is_relative_to(bound_layout.workspace_dir)
    # Specifically the named file inside.
    assert target == (bound_layout.workspace_dir / "report.md").resolve()


def test_resolve_write_routes_skills_by_default(bound_layout):
    """Bare paths still land in ``skills/`` — backward-compatible
    with every existing skill the agent authored on 0.1.x."""
    target = _resolve_write("my_skill_v1/SKILL.md")
    assert target.is_relative_to(bound_layout.skills_dir)


def test_resolve_write_routes_explicit_skills_prefix(bound_layout):
    """``skills/foo`` also lands in ``skills/`` — the leading
    sandbox-root strip in ``_resolve_under`` handles idempotency."""
    target = _resolve_write("skills/notes.txt")
    assert target.is_relative_to(bound_layout.skills_dir)


def test_resolve_write_rejects_workspace_escape(bound_layout):
    """``..`` traversal under the workspace prefix is still blocked."""
    with pytest.raises(SandboxError):
        _resolve_write("workspace/../skills/secret.txt")


def test_resolve_write_rejects_absolute_path(bound_layout):
    with pytest.raises(SandboxError):
        _resolve_write("/etc/passwd")


# ── file_write end-to-end ───────────────────────────────────────────


def test_file_write_lands_in_workspace_when_prefixed(bound_layout):
    result = file_tools.file_write("workspace/report.md", "# my report\n")
    assert result["written"] is True
    assert (bound_layout.workspace_dir / "report.md").read_text() == "# my report\n"
    # And NOT under skills/
    assert not (bound_layout.skills_dir / "report.md").exists()
    # Audit log path is relative to the instance root.
    assert result["path"].startswith("workspace/")


def test_file_write_lands_in_skills_by_default(bound_layout):
    result = file_tools.file_write("my_skill_v1/SKILL.md", "# my skill\n")
    assert result["written"] is True
    assert (bound_layout.skills_dir / "my_skill_v1" / "SKILL.md").exists()
    assert result["path"].startswith("skills/")


def test_append_file_routes_to_workspace(bound_layout):
    file_tools.file_write("workspace/log.txt", "line1\n")
    file_tools.append_file("workspace/log.txt", "line2\n")
    body = (bound_layout.workspace_dir / "log.txt").read_text()
    assert body == "line1\nline2\n"


def test_edit_file_routes_to_workspace(bound_layout):
    file_tools.file_write("workspace/note.txt", "hello world")
    result = file_tools.edit_file("workspace/note.txt", "world", "you")
    assert result["edited"] is True
    assert (bound_layout.workspace_dir / "note.txt").read_text() == "hello you"


def test_delete_file_routes_to_workspace(bound_layout):
    file_tools.file_write("workspace/tmp.txt", "x")
    result = file_tools.delete_file("workspace/tmp.txt")
    assert result["deleted"] is True
    assert not (bound_layout.workspace_dir / "tmp.txt").exists()


def test_workspace_nested_subdirs(bound_layout):
    """Nested paths under workspace/ work the same way."""
    result = file_tools.file_write(
        "workspace/reports/2026-05-26.md", "## summary\n",
    )
    assert result["written"] is True
    nested = bound_layout.workspace_dir / "reports" / "2026-05-26.md"
    assert nested.exists()


def test_workspace_and_skills_can_share_filename(bound_layout):
    """A ``workspace/foo.txt`` and a ``skills/foo.txt`` are two
    different files — proves the routing isn't conflating them."""
    file_tools.file_write("workspace/foo.txt", "workspace version")
    file_tools.file_write("skills/foo.txt", "skills version")
    assert (bound_layout.workspace_dir / "foo.txt").read_text() == "workspace version"
    assert (bound_layout.skills_dir / "foo.txt").read_text() == "skills version"


# ── workspace override (config.yaml: workspace.location) ───────────


def test_workspace_override_redirects_writes(tmp_path, monkeypatch):
    """When ``bind(..., workspace_override=...)`` is called, every
    ``workspace/...`` write lands at the override path instead of
    ``<instance>/workspace/``."""
    from jaeger_ai.agent import tools as jaeger_tools

    inst_root = tmp_path / "inst"
    inst_root.mkdir()
    override = tmp_path / "Documents" / "Jaeger Outputs"
    layout = InstanceLayout(root=inst_root)
    layout.ensure_dirs()
    jaeger_tools.bind(layout, workspace_override=override)

    result = file_tools.file_write("workspace/report.md", "# hi")
    assert result["written"] is True
    # The file landed at the override path, NOT under the instance dir.
    assert (override / "report.md").read_text() == "# hi"
    assert not (layout.workspace_dir / "report.md").exists()

    # And ``skills/`` writes still land inside the instance — only
    # the workspace prefix is redirected.
    file_tools.file_write("my_skill/SKILL.md", "x")
    assert (layout.skills_dir / "my_skill" / "SKILL.md").exists()


def test_workspace_override_creates_target_dir(tmp_path):
    """``bind()`` creates the override dir if it doesn't exist."""
    from jaeger_ai.agent import tools as jaeger_tools

    inst = tmp_path / "inst"
    inst.mkdir()
    override = tmp_path / "fresh" / "location"
    assert not override.exists()

    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    jaeger_tools.bind(layout, workspace_override=override)
    assert override.is_dir()


def test_workspace_override_expands_user(tmp_path, monkeypatch):
    """``~/Documents/foo`` is expanded relative to $HOME."""
    from jaeger_ai.agent import tools as jaeger_tools

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    inst = tmp_path / "inst"
    inst.mkdir()
    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    jaeger_tools.bind(layout, workspace_override="~/Documents/Outputs")

    file_tools.file_write("workspace/x.txt", "ok")
    expected = tmp_path / "home" / "Documents" / "Outputs" / "x.txt"
    assert expected.read_text() == "ok"


def test_workspace_config_schema_default_is_none():
    from jaeger_ai.core.instance.schemas import WorkspaceConfig
    assert WorkspaceConfig().location is None


def test_workspace_config_accepts_a_path():
    from jaeger_ai.core.instance.schemas import WorkspaceConfig
    cfg = WorkspaceConfig(location="~/Documents/Jaeger")
    assert cfg.location == "~/Documents/Jaeger"
