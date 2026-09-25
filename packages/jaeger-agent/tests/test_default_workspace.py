"""A bare install must be able to touch disk without a layout class.

~40 tools resolve paths through the workspace. Until 0.11 an unbound
module raised "tools not bound", which was correct inside JaegerAI —
the app always bound an instance — and a chore for everyone else.
"""

from __future__ import annotations

import pathlib

import pytest

from jaeger_agent.core import workspace


def test_default_workspace_uses_external_operator_state(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    state = tmp_path / "state"
    monkeypatch.chdir(source)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "legacy-override"))
    ws = workspace.DefaultWorkspace().create()
    assert ws.root == (state / "agent").resolve()
    assert ws.root.is_dir() and ws.workspace_dir.is_dir()
    assert not list(source.iterdir())


def test_the_seven_paths_are_the_whole_contract(tmp_path) -> None:
    """Everything jaeger_agent asks of a host layout. JaegerAI's
    InstanceLayout satisfies it structurally; so does this."""
    ws = workspace.DefaultWorkspace(tmp_path / "ws")
    for attr in ("root", "logs_dir", "skills_dir", "memory_dir",
                 "audit_log_path", "config_path", "identity_path"):
        assert isinstance(getattr(ws, attr), pathlib.Path), attr


def test_explicit_root_wins(tmp_path) -> None:
    ws = workspace.DefaultWorkspace(tmp_path / "elsewhere").create()
    assert ws.root == (tmp_path / "elsewhere").resolve()


def test_bare_write_of_an_existing_workspace_file_stays_in_workspace(tmp_path) -> None:
    """Option A: if the file is already in workspace/, a bare name
    round-trips there. New bare names still land in skills/."""
    layout = workspace.DefaultWorkspace(tmp_path / "inst").create()
    existing = layout.workspace_dir / "item_00.txt"
    existing.write_text("seed\n")
    workspace.bind(layout)
    try:
        hit = workspace._resolve_write("item_00.txt")
        assert hit == existing.resolve()
        fresh = workspace._resolve_write("brand_new.py")
        assert fresh.is_relative_to(layout.skills_dir)
        prefixed = workspace._resolve_write("workspace/report.md")
        assert prefixed.is_relative_to(layout.workspace_dir)
    finally:
        workspace._layout = None


def test_write_to_a_real_out_of_sandbox_path_raises_instead_of_phantom_404(
    tmp_path, monkeypatch
) -> None:
    """A path that resolves to a REAL file outside workspace/skills (e.g.
    framework code under packages/...) must raise SandboxError, not
    silently re-root under skills_dir and 404.

    Regression for the loop that hit production: the agent's own
    dispatcher session (2026-09-22 03:06-03:11, cards card_6c9153233c and
    card_14425a5598) called patch() on a real, existing file outside the
    sandbox, got a misleading "not found", re-verified with read_file
    (which succeeded — reads are unconfined), got confused by the
    contradiction, and looped: 2 identical patch failures, then 4
    identical workspace_read calls before the loop backstop halted the
    turn. The fix must fail clearly on the FIRST attempt instead.
    """
    repo = tmp_path / "repo"
    real_file = repo / "packages" / "real_pkg" / "file.py"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("existing framework content\n")
    monkeypatch.chdir(repo)

    layout = workspace.DefaultWorkspace(tmp_path / "inst").create()
    workspace.bind(layout)
    try:
        rel_path = "packages/real_pkg/file.py"
        # Sanity: reads DO find the real file (unconfined, per docstring).
        assert workspace._resolve_read(rel_path) == real_file.resolve()
        # Writes must refuse it loudly, not silently target a phantom
        # nonexistent path under skills_dir.
        with pytest.raises(workspace.SandboxError):
            workspace._resolve_write(rel_path)
    finally:
        workspace._layout = None


def test_ensure_bound_does_not_steal_a_hosts_layout(tmp_path, monkeypatch) -> None:
    """A host layout owns workspace and memory; fallback state stays unused."""
    from jaeger_agent.memory import sqlite_store

    monkeypatch.chdir(tmp_path)
    host = workspace.DefaultWorkspace(tmp_path / "host_owned").create()
    workspace.bind(host)
    try:
        assert workspace.ensure_bound().root == host.root
        assert sqlite_store.db_path() == host.memory_dir / "state.db"
        assert not (tmp_path / ".jaeger_agent").exists()
    finally:
        sqlite_store.close()
        workspace._layout = None
