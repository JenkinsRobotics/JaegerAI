"""Sub-agent git worktree isolation.

Ported from hermes-agent ``tools/subagent_worktree.py``. The behaviour these
tests exist to protect is the donor's fail-safe: a destructive prune requires
affirmative proof that the tree is empty and clean. An unmeasured default
must never be read as "the child produced nothing".
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from jaeger_agent import subagent_worktree as wt


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A git repo with one commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "t@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-qm", "init", cwd=root)
    return root


@pytest.fixture(autouse=True)
def _isolation_on(monkeypatch):
    monkeypatch.setenv("JAEGER_SUBAGENT_WORKTREE", "1")


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JAEGER_SUBAGENT_WORKTREE", raising=False)
    assert wt.isolation_enabled() is False


def test_non_git_dir_degrades_silently(tmp_path):
    assert wt.resolve_repo_root(str(tmp_path)) is None
    assert wt.create_subagent_worktree(str(tmp_path), "abc") is None


def test_missing_path_degrades_silently():
    assert wt.resolve_repo_root(None) is None
    assert wt.resolve_repo_root("/no/such/dir/anywhere") is None


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def test_creates_worktree_on_its_own_branch(repo):
    info = wt.create_subagent_worktree(str(repo), "abc123")
    assert info is not None
    assert info["branch"] == "jaeger-subagent/subagent-abc123"
    assert (repo / ".worktrees" / "subagent-abc123").is_dir()
    assert (repo / ".worktrees" / "subagent-abc123" / "README.md").exists()
    assert info["base_commit"]


def test_creation_adds_worktrees_to_gitignore(repo):
    wt.create_subagent_worktree(str(repo), "abc123")
    assert ".worktrees/" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_two_children_get_separate_worktrees(repo):
    a = wt.create_subagent_worktree(str(repo), "aaa")
    b = wt.create_subagent_worktree(str(repo), "bbb")
    assert a["path"] != b["path"]
    assert a["branch"] != b["branch"]


# ---------------------------------------------------------------------------
# Finalize — pruning requires proof
# ---------------------------------------------------------------------------

def test_clean_empty_worktree_is_pruned(repo):
    info = wt.create_subagent_worktree(str(repo), "abc123")
    out = wt.finalize_subagent_worktree(info)
    assert out["pruned"] is True
    assert out["commits"] == 0
    assert out.get("inspection_failed") is not True
    assert not (repo / ".worktrees" / "subagent-abc123").exists()


def test_worktree_with_commits_is_kept(repo):
    info = wt.create_subagent_worktree(str(repo), "abc123")
    path = info["path"]
    (repo / ".worktrees" / "subagent-abc123" / "work.txt").write_text("x", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "child work", cwd=path)

    out = wt.finalize_subagent_worktree(info)
    assert out["commits"] == 1
    assert out["pruned"] is False
    assert (repo / ".worktrees" / "subagent-abc123").exists()


def test_dirty_worktree_is_kept(repo):
    info = wt.create_subagent_worktree(str(repo), "abc123")
    (repo / ".worktrees" / "subagent-abc123" / "scratch.txt").write_text("x", encoding="utf-8")
    out = wt.finalize_subagent_worktree(info)
    assert out["dirty"] is True
    assert out["pruned"] is False
    assert (repo / ".worktrees" / "subagent-abc123").exists()


def test_failed_probe_keeps_worktree_and_flags_unproven(repo):
    """The #88113 fail-safe: no prune without affirmative proof."""
    info = wt.create_subagent_worktree(str(repo), "abc123")

    real = wt._run_git

    def flaky(args, cwd, timeout=30):
        if args and args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad revision")
        return real(args, cwd, timeout)

    with mock.patch.object(wt, "_run_git", side_effect=flaky):
        out = wt.finalize_subagent_worktree(info)

    assert out["inspection_failed"] is True
    assert "commits" in out["note"]
    assert "UNKNOWN" in out["note"]
    assert out["pruned"] is False
    assert (repo / ".worktrees" / "subagent-abc123").exists()


def test_raised_probe_keeps_worktree(repo):
    info = wt.create_subagent_worktree(str(repo), "abc123")
    with mock.patch.object(wt, "_run_git", side_effect=OSError("boom")):
        out = wt.finalize_subagent_worktree(info)
    assert out["inspection_failed"] is True
    assert out["pruned"] is False
    assert (repo / ".worktrees" / "subagent-abc123").exists()


def test_missing_base_commit_is_unmeasurable_not_empty(repo):
    """Without a base commit the count is a default, not a measurement."""
    info = wt.create_subagent_worktree(str(repo), "abc123")
    info["base_commit"] = ""
    out = wt.finalize_subagent_worktree(info)
    assert out["inspection_failed"] is True
    assert out["pruned"] is False
    assert "commits" in out["note"]
    assert (repo / ".worktrees" / "subagent-abc123").exists()


def test_unproven_payload_names_only_failed_probes():
    payload = wt.mark_worktree_payload_unproven(
        {"path": "/p", "branch": "b", "commits": 0, "dirty": True, "pruned": False},
        "rev-list exit 128", unmeasured="commits",
    )
    assert "commits UNKNOWN" in payload["note"]
    assert payload["dirty"] is True  # a real measurement, preserved


def test_unproven_payload_from_info_omits_internals():
    out = wt.unproven_worktree_payload(
        {"path": "/p", "branch": "b", "repo_root": "/r", "base_commit": "deadbeef"},
        "finalize raised",
    )
    assert out["inspection_failed"] is True
    assert "repo_root" not in out
    assert "base_commit" not in out


def test_finalize_on_vanished_path_reports_pruned():
    out = wt.finalize_subagent_worktree(
        {"path": "/no/such/worktree", "branch": "b", "repo_root": "", "base_commit": "x"})
    assert out["pruned"] is True


# ---------------------------------------------------------------------------
# The Jaeger seam: project-root swap
# ---------------------------------------------------------------------------

def test_isolated_child_swaps_and_restores_project_root(repo, monkeypatch):
    from jaeger_agent import workspace as ws

    ws.set_project_root(repo)
    assert ws.get_project_root() == repo.resolve()

    with wt.isolated_child("abc123") as info:
        assert info is not None
        assert ws.get_project_root() == (repo / ".worktrees" / "subagent-abc123").resolve()
        assert "WORKTREE ISOLATION" in info["context_note"]
        # Child does real work so the worktree survives finalize.
        (repo / ".worktrees" / "subagent-abc123" / "out.txt").write_text("x", encoding="utf-8")

    assert ws.get_project_root() == repo.resolve()
    assert info["result"]["dirty"] is True
    assert info["result"]["pruned"] is False


def test_isolated_child_restores_root_even_when_body_raises(repo):
    from jaeger_agent import workspace as ws

    ws.set_project_root(repo)
    with pytest.raises(RuntimeError):
        with wt.isolated_child("abc123"):
            raise RuntimeError("child blew up")
    assert ws.get_project_root() == repo.resolve()


def test_isolated_child_is_a_noop_when_disabled(repo, monkeypatch):
    from jaeger_agent import workspace as ws

    monkeypatch.delenv("JAEGER_SUBAGENT_WORKTREE", raising=False)
    ws.set_project_root(repo)
    with wt.isolated_child("abc123") as info:
        assert info is None
        assert ws.get_project_root() == repo.resolve()
    assert not (repo / ".worktrees").exists()


def test_isolated_child_noop_outside_a_git_repo(tmp_path):
    from jaeger_agent import workspace as ws

    plain = tmp_path / "plain"
    plain.mkdir()
    ws.set_project_root(plain)
    with wt.isolated_child("abc123") as info:
        assert info is None
        assert ws.get_project_root() == plain.resolve()
