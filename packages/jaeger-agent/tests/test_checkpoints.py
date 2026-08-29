"""Shadow-git filesystem checkpoints.

Ported from hermes-agent ``tools/checkpoint_manager.py``. The properties
pinned here are the ones that make a background git process safe to run on
every turn: it must not inherit the operator's git config, it must not
snapshot twice in a turn, and a restore must be undoable.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from jaeger_agent import checkpoints as cp


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: layout)
    monkeypatch.setenv("JAEGER_CHECKPOINTS", "1")
    cp.reset_manager()
    yield layout
    cp.reset_manager()


@pytest.fixture()
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    (p / "a.txt").write_text("original\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def test_disabled_by_default(instance, project, monkeypatch):
    monkeypatch.delenv("JAEGER_CHECKPOINTS", raising=False)
    monkeypatch.setattr(
        "jaeger_agent.instance_config.section", lambda name, layout=None: None)
    m = cp.CheckpointManager()
    assert m.enabled is False
    assert m.ensure_checkpoint(project) is None


def test_env_enables(instance, project):
    assert cp.CheckpointManager().enabled is True


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def test_first_snapshot_creates_a_commit(instance, project):
    m = cp.CheckpointManager()
    commit = m.ensure_checkpoint(project, "test")
    assert commit and len(commit) == 40
    assert (cp.store_path() / "HEAD").exists()


def test_only_one_snapshot_per_turn(instance, project):
    m = cp.CheckpointManager()
    assert m.ensure_checkpoint(project) is not None
    (project / "a.txt").write_text("changed\n", encoding="utf-8")
    assert m.ensure_checkpoint(project) is None  # same turn
    m.new_turn()
    assert m.ensure_checkpoint(project) is not None


def test_unchanged_tree_makes_no_new_snapshot(instance, project):
    m = cp.CheckpointManager()
    m.ensure_checkpoint(project)
    m.new_turn()
    assert m.ensure_checkpoint(project) is None  # nothing changed


def test_history_accumulates(instance, project):
    m = cp.CheckpointManager()
    for i in range(3):
        m.new_turn()
        (project / "a.txt").write_text(f"v{i}\n", encoding="utf-8")
        m.ensure_checkpoint(project, f"edit {i}")
    entries = m.list_checkpoints(project)
    assert len(entries) == 3
    assert entries[0].reason == "edit 2"        # newest first
    assert entries[0].created_at >= entries[-1].created_at


def test_missing_directory_is_a_noop(instance, tmp_path):
    assert cp.CheckpointManager().ensure_checkpoint(tmp_path / "nope") is None


def test_snapshot_failure_never_raises(instance, project, monkeypatch):
    monkeypatch.setattr(cp, "_init_store", lambda *a, **k: False)
    assert cp.CheckpointManager().ensure_checkpoint(project) is None


# ---------------------------------------------------------------------------
# Config isolation — the property that stops pinentry mid-turn
# ---------------------------------------------------------------------------

def test_git_env_neutralises_user_config(instance, project):
    env = cp._git_env(cp.store_path(), project, None)
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_DIR"] == str(cp.store_path())
    assert env["GIT_WORK_TREE"] == str(project)


def test_git_env_drops_inherited_namespace(instance, project, monkeypatch):
    monkeypatch.setenv("GIT_NAMESPACE", "leaked")
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", "/tmp/leak")
    env = cp._git_env(cp.store_path(), project, None)
    assert "GIT_NAMESPACE" not in env
    assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" not in env


def test_snapshot_works_with_gpgsign_forced_on(instance, project, monkeypatch, tmp_path):
    """A signing config in the operator's ~/.gitconfig must not reach us."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".gitconfig").write_text(
        "[commit]\n\tgpgsign = true\n[user]\n\tsigningkey = DEADBEEF\n",
        encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    assert cp.CheckpointManager().ensure_checkpoint(project) is not None


def test_no_git_state_leaks_into_the_project(instance, project):
    cp.CheckpointManager().ensure_checkpoint(project)
    assert not (project / ".git").exists()


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def test_restore_brings_content_back(instance, project):
    m = cp.CheckpointManager()
    good = m.ensure_checkpoint(project, "good state")
    (project / "a.txt").write_text("ruined\n", encoding="utf-8")

    ok, msg = m.restore(project, good)
    assert ok, msg
    assert (project / "a.txt").read_text(encoding="utf-8") == "original\n"


def test_restore_takes_a_safety_snapshot_first(instance, project):
    m = cp.CheckpointManager()
    good = m.ensure_checkpoint(project, "good")
    (project / "a.txt").write_text("ruined\n", encoding="utf-8")

    ok, msg = m.restore(project, good)
    assert ok
    assert "pre-restore state saved as" in msg
    # And that safety snapshot is real: restoring it returns the bad content.
    safety = [c for c in m.list_checkpoints(project)
              if c.reason == "pre-restore safety"]
    assert safety
    m.restore(project, safety[0].commit, take_safety=False)
    assert (project / "a.txt").read_text(encoding="utf-8") == "ruined\n"


def test_restore_rejects_a_malformed_hash(instance, project):
    m = cp.CheckpointManager()
    m.ensure_checkpoint(project)
    for bad in ("", "zzz", "../../etc", "HEAD", "x" * 41):
        ok, msg = m.restore(project, bad)
        assert not ok
        assert "not a valid commit" in msg


def test_restore_rejects_an_unknown_commit(instance, project):
    m = cp.CheckpointManager()
    m.ensure_checkpoint(project)
    ok, msg = m.restore(project, "a" * 40)
    assert not ok
    assert "unknown checkpoint" in msg


def test_restore_without_a_store_is_refused(instance, project):
    ok, msg = cp.CheckpointManager().restore(project, "a" * 40)
    assert not ok
    assert "no checkpoint store" in msg


# ---------------------------------------------------------------------------
# Pruning + store health
# ---------------------------------------------------------------------------

def test_prune_caps_history(instance, project):
    m = cp.CheckpointManager(max_snapshots=3)
    for i in range(6):
        m.new_turn()
        (project / "a.txt").write_text(f"v{i}\n", encoding="utf-8")
        m.ensure_checkpoint(project, f"edit {i}")
    assert len(m.list_checkpoints(project)) <= 3


def test_two_projects_share_one_store_without_colliding(instance, tmp_path):
    a = tmp_path / "a"; a.mkdir(); (a / "f").write_text("A", encoding="utf-8")
    b = tmp_path / "b"; b.mkdir(); (b / "f").write_text("B", encoding="utf-8")

    m = cp.CheckpointManager()
    m.ensure_checkpoint(a, "a")
    m.ensure_checkpoint(b, "b")

    assert len(m.list_checkpoints(a)) == 1
    assert len(m.list_checkpoints(b)) == 1
    stores = list((cp.store_path() / "projects").glob("*.json"))
    assert len(stores) == 2


def test_repair_recreates_refs_dirs(instance, project):
    m = cp.CheckpointManager()
    m.ensure_checkpoint(project)
    import shutil
    shutil.rmtree(cp.store_path() / "refs", ignore_errors=True)

    m.new_turn()
    (project / "a.txt").write_text("more\n", encoding="utf-8")
    # gc can delete refs/; the next snapshot must repair rather than fail.
    assert m.ensure_checkpoint(project) is not None


def test_excludes_keep_junk_out(instance, project):
    (project / "node_modules").mkdir()
    (project / "node_modules" / "big.js").write_text("x" * 1000, encoding="utf-8")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "m.pyc").write_text("y", encoding="utf-8")

    m = cp.CheckpointManager()
    commit = m.ensure_checkpoint(project)
    res = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit],
        env=cp._git_env(cp.store_path(), project, None),
        capture_output=True, text=True)
    listed = res.stdout
    assert "a.txt" in listed
    assert "node_modules" not in listed
    assert "__pycache__" not in listed
