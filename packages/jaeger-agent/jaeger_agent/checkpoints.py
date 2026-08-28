"""Filesystem checkpoints — shadow-git snapshots with rollback.

Ported from hermes-agent ``tools/checkpoint_manager.py``. hermes-agent is MIT
licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

WHAT THIS IS. Automatic snapshots of the working directory taken before
file-mutating work, with rollback to any earlier snapshot. This is NOT a tool
— the model never sees it. It is transparent infrastructure gated on
``checkpoints.enabled`` in the instance config.

Jaeger already had two things called "checkpoint" and neither is this one:
``cognition/runs.py`` checkpoints *agent progress* for crash recovery, and
``workspace.git_autocommit`` commits inside the skills sandbox. Neither can
answer "undo what the last ten minutes of edits did to my project", which is
what this module is for.

STORAGE, following the donor's v2 design::

    <instance>/checkpoints/
        store/                     — one shared bare repo
            refs/jaeger/<hash16>   — per-project branch tip
            indexes/<hash16>       — per-project git index
            projects/<hash16>.json — {workdir, created_at, last_touch}

One shared store rather than a repo per project: git's content-addressable
object database then dedupes blobs across projects and across turns, so a
second worktree of the same repo costs almost nothing. The donor measured
~40 MB per project under the old per-project design.

THE CONFIG-ISOLATION PROPERTY IS LOAD-BEARING. The store is internal
infrastructure and must not inherit the operator's git config. A user-level
``commit.gpgsign = true`` would make every background snapshot try to sign,
which at best fails and at worst spawns an interactive pinentry window
mid-turn. ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` are pointed at
``os.devnull`` and ``GIT_CONFIG_NOSYSTEM=1`` is set for older git.

PORTED / NOT PORTED. Snapshot, list, diff, restore, per-project pruning and
git-config isolation are ported. The donor's legacy pre-v2 store migration,
volume-evidence heuristics for detecting a vanished external drive, and
global size-cap sweeps across all projects are not — they exist to service
installs this code has never had. ``prune`` keeps the per-project snapshot
cap, which is the part that bounds growth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 60
_DEFAULT_MAX_SNAPSHOTS = 20
_REF_PREFIX = "refs/jaeger"


@dataclass(frozen=True)
class Checkpoint:
    """One snapshot."""

    commit: str
    created_at: float
    reason: str

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.created_at)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _normalize(path: Any) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _project_hash(working_dir: Any) -> str:
    return hashlib.sha256(
        str(_normalize(working_dir)).encode("utf-8")).hexdigest()[:16]


def _root() -> Path:
    from jaeger_agent.workspace import get_layout

    return Path(get_layout().root) / "checkpoints"


def store_path() -> Path:
    return _root() / "store"


def _index_path(store: Path, dir_hash: str) -> Path:
    return store / "indexes" / dir_hash


def _meta_path(store: Path, dir_hash: str) -> Path:
    return store / "projects" / f"{dir_hash}.json"


def _ref(dir_hash: str) -> str:
    return f"{_REF_PREFIX}/{dir_hash}"


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------

def _git_env(store: Path, working_dir: Any, index_file: Path | None) -> dict:
    """Env that redirects git at the shadow store.

    See the module docstring: the isolation vars are not optional hygiene,
    they are what stops a signing config from hanging a background snapshot
    on an interactive prompt.
    """
    env = dict(os.environ)
    env["GIT_DIR"] = str(store)
    env["GIT_WORK_TREE"] = str(_normalize(working_dir))
    env.pop("GIT_NAMESPACE", None)
    env.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    else:
        env.pop("GIT_INDEX_FILE", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # Commits are made by the agent, not the operator; a missing user.name
    # in an isolated config would otherwise abort every snapshot.
    env.setdefault("GIT_AUTHOR_NAME", "jaeger-checkpoints")
    env.setdefault("GIT_AUTHOR_EMAIL", "checkpoints@jaeger.local")
    env.setdefault("GIT_COMMITTER_NAME", "jaeger-checkpoints")
    env.setdefault("GIT_COMMITTER_EMAIL", "checkpoints@jaeger.local")
    return env


def _git(args: list[str], store: Path, working_dir: Any,
         index_file: Path | None = None, timeout: int = _GIT_TIMEOUT):
    return subprocess.run(
        ["git", *args],
        env=_git_env(store, working_dir, index_file),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def _repair_bare_dirs(store: Path) -> None:
    """Recreate ``refs/``/``branches/`` that ``git gc`` can remove.

    Straight from the donor: gc on a bare repo whose refs are all packed can
    delete the empty ``refs/heads/`` directory, and git 2.34+ then fails
    ``git add -A`` with "fatal: not a git repository". Cheap to re-create,
    and the failure it prevents looks like total store corruption.
    """
    for sub in ("refs", "refs/heads", "branches"):
        try:
            (store / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def _init_store(store: Path, working_dir: Any) -> bool:
    """Create the bare store if absent. True when usable."""
    try:
        if (store / "HEAD").exists():
            _repair_bare_dirs(store)
            return True
        store.mkdir(parents=True, exist_ok=True)
        # ``git init --bare`` rejects GIT_WORK_TREE, so this one call cannot
        # go through _git(); strip the redirect vars for it.
        env = dict(os.environ)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                  "GIT_NAMESPACE", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            env.pop(k, None)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        res = subprocess.run(
            ["git", "init", "--bare", "--quiet", str(store)],
            env=env, capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        if res.returncode != 0:
            logger.warning("checkpoints: store init failed: %s",
                           res.stderr.strip())
            return False
        _repair_bare_dirs(store)
        (store / "indexes").mkdir(parents=True, exist_ok=True)
        (store / "projects").mkdir(parents=True, exist_ok=True)
        # Default excludes — never snapshot these.
        (store / "info").mkdir(parents=True, exist_ok=True)
        (store / "info" / "exclude").write_text(
            "\n".join((".git/", "node_modules/", "__pycache__/", "*.pyc",
                       ".venv/", "venv/", ".worktrees/", ".DS_Store", "")),
            encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("checkpoints: store init error: %s", exc)
        return False


def _register(store: Path, working_dir: Any, dir_hash: str) -> None:
    meta = _meta_path(store, dir_hash)
    try:
        meta.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {"workdir": str(_normalize(working_dir)),
                   "created_at": now, "last_touch": now}
        if meta.is_file():
            try:
                existing = json.loads(meta.read_text(encoding="utf-8"))
                payload["created_at"] = existing.get("created_at", now)
            except Exception:
                pass
        meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("checkpoints: could not register project: %s", exc)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """Takes at most one snapshot per turn, per working directory."""

    def __init__(self, enabled: bool | None = None,
                 max_snapshots: int = _DEFAULT_MAX_SNAPSHOTS) -> None:
        self._enabled = enabled
        self.max_snapshots = max(1, int(max_snapshots))
        self._turn_taken: set[str] = set()

    # ── gating ──────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        val = os.environ.get("JAEGER_CHECKPOINTS", "").strip().lower()
        if val in ("0", "false", "no", "off"):
            return False
        if val in ("1", "true", "yes", "on"):
            return True
        try:
            from jaeger_agent import instance_config
            block = instance_config.section("checkpoints")
            return bool(getattr(block, "enabled", False))
        except Exception:
            return False

    def new_turn(self) -> None:
        """Reset the once-per-turn guard. Called at the top of each turn."""
        self._turn_taken.clear()

    # ── snapshot ────────────────────────────────────────────────────

    def ensure_checkpoint(self, working_dir: Any,
                          reason: str = "auto") -> str | None:
        """Snapshot *working_dir* unless one was already taken this turn.

        Returns the commit hash, or None when disabled / nothing to do /
        anything went wrong. Never raises: a checkpoint failure must not
        break the tool call it was protecting.
        """
        if not self.enabled:
            return None
        key = str(_normalize(working_dir))
        if key in self._turn_taken:
            return None
        self._turn_taken.add(key)
        try:
            return self._take(working_dir, reason)
        except Exception as exc:
            logger.warning("checkpoints: snapshot failed for %s: %s",
                           working_dir, exc)
            return None

    def _take(self, working_dir: Any, reason: str) -> str | None:
        wd = _normalize(working_dir)
        if not wd.is_dir():
            return None
        store = store_path()
        if not _init_store(store, wd):
            return None
        dir_hash = _project_hash(wd)
        index = _index_path(store, dir_hash)
        index.parent.mkdir(parents=True, exist_ok=True)
        ref = _ref(dir_hash)
        _register(store, wd, dir_hash)

        # Seed the index from the current tip so the commit is a delta.
        parent = self._tip(store, wd, ref)
        if parent:
            _git(["read-tree", parent], store, wd, index)
        else:
            _git(["read-tree", "--empty"], store, wd, index)

        add = _git(["add", "-A", "--", str(wd)], store, wd, index)
        if add.returncode != 0:
            logger.debug("checkpoints: add failed: %s", add.stderr.strip())
            return None

        tree = _git(["write-tree"], store, wd, index)
        if tree.returncode != 0:
            return None
        tree_hash = tree.stdout.strip()

        # Skip a no-op snapshot: identical tree means nothing changed.
        if parent:
            parent_tree = _git(["rev-parse", f"{parent}^{{tree}}"],
                               store, wd, index)
            if parent_tree.returncode == 0 and \
                    parent_tree.stdout.strip() == tree_hash:
                return None

        args = ["commit-tree", tree_hash, "-m", f"checkpoint: {reason}"]
        if parent:
            args += ["-p", parent]
        made = _git(args, store, wd, index)
        if made.returncode != 0:
            logger.debug("checkpoints: commit-tree failed: %s",
                         made.stderr.strip())
            return None
        commit = made.stdout.strip()
        upd = _git(["update-ref", ref, commit], store, wd, index)
        if upd.returncode != 0:
            return None
        self._prune(store, wd, ref, index)
        return commit

    @staticmethod
    def _tip(store: Path, wd: Path, ref: str) -> str | None:
        res = _git(["rev-parse", "--verify", "--quiet", ref], store, wd)
        return res.stdout.strip() if res.returncode == 0 else None

    # ── read ────────────────────────────────────────────────────────

    def list_checkpoints(self, working_dir: Any) -> list[Checkpoint]:
        """Snapshots for *working_dir*, newest first."""
        wd = _normalize(working_dir)
        store = store_path()
        if not (store / "HEAD").exists():
            return []
        ref = _ref(_project_hash(wd))
        res = _git(["log", "--format=%H%x00%ct%x00%s", "-n",
                    str(self.max_snapshots * 2), ref], store, wd)
        if res.returncode != 0:
            return []
        out: list[Checkpoint] = []
        for line in res.stdout.splitlines():
            parts = line.split("\x00")
            if len(parts) != 3:
                continue
            commit, ts, subject = parts
            try:
                created = float(ts)
            except ValueError:
                continue
            out.append(Checkpoint(
                commit=commit, created_at=created,
                reason=subject.removeprefix("checkpoint: ")))
        return out

    def diff(self, working_dir: Any, commit: str) -> str:
        """Diff the working tree against a snapshot."""
        wd = _normalize(working_dir)
        if not _valid_commit(commit):
            return ""
        store = store_path()
        index = _index_path(store, _project_hash(wd))
        res = _git(["diff", commit, "--"], store, wd, index)
        return res.stdout if res.returncode == 0 else ""

    # ── restore ─────────────────────────────────────────────────────

    def restore(self, working_dir: Any, commit: str,
                *, take_safety: bool = True) -> tuple[bool, str]:
        """Roll *working_dir* back to *commit*.

        Takes a safety snapshot of the CURRENT state first so the rollback is
        itself undoable, and fails closed if that snapshot cannot be made —
        the same discipline as the skill ledger's rollback. Refuses an
        unknown or malformed commit rather than letting git interpret it.
        """
        if not _valid_commit(commit):
            return False, f"not a valid commit hash: {commit!r}"
        wd = _normalize(working_dir)
        if not wd.is_dir():
            return False, f"not a directory: {wd}"
        store = store_path()
        if not (store / "HEAD").exists():
            return False, "no checkpoint store for this instance"

        index = _index_path(store, _project_hash(wd))
        known = _git(["cat-file", "-e", f"{commit}^{{commit}}"], store, wd, index)
        if known.returncode != 0:
            return False, f"unknown checkpoint {commit[:12]}"

        safety = None
        if take_safety:
            # Bypass the once-per-turn guard: a restore must always be
            # undoable, even if this turn already snapshotted.
            try:
                safety = self._take(wd, "pre-restore safety")
            except Exception as exc:
                return False, (f"pre-restore safety snapshot failed ({exc}); "
                               "nothing was changed")
            if safety is None and self.list_checkpoints(wd):
                # None with existing history means "no changes to capture",
                # which is fine. Only a hard failure aborts, and that raises.
                safety = None

        res = _git(["checkout", "-f", commit, "--", "."], store, wd, index)
        if res.returncode != 0:
            return False, f"restore failed: {res.stderr.strip()[:300]}"
        msg = f"restored {wd} to checkpoint {commit[:12]}"
        if safety:
            msg += f" (pre-restore state saved as {safety[:12]})"
        return True, msg

    # ── pruning ─────────────────────────────────────────────────────

    def _prune(self, store: Path, wd: Path, ref: str, index: Path) -> None:
        """Keep at most ``max_snapshots`` by re-rooting the ref."""
        try:
            res = _git(["rev-list", ref], store, wd, index)
            if res.returncode != 0:
                return
            commits = res.stdout.split()
            if len(commits) <= self.max_snapshots:
                return
            keep = commits[self.max_snapshots - 1]
            _git(["update-ref", ref, keep], store, wd, index)
        except Exception as exc:
            logger.debug("checkpoints: prune skipped: %s", exc)


def _valid_commit(value: str) -> bool:
    v = (value or "").strip()
    return 7 <= len(v) <= 40 and all(c in "0123456789abcdef" for c in v.lower())


# Process-wide manager — the executor hook and any CLI share one.
_manager: CheckpointManager | None = None


def manager() -> CheckpointManager:
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager


def reset_manager() -> None:
    """Test seam."""
    global _manager
    _manager = None


__all__ = [
    "Checkpoint", "CheckpointManager", "manager", "reset_manager",
    "store_path",
]
