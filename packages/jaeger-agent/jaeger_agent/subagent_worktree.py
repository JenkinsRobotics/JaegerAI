"""Opt-in git worktree isolation for delegated sub-agents.

Ported from hermes-agent ``tools/subagent_worktree.py``. hermes-agent is MIT
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

The donor notes its own lineage, which is preserved here: the behaviour is a
clean-room implementation of Muse Code's documented
``--subagent-worktree-isolation`` (Meta, Aug 2026), from
https://dev.meta.ai/docs/muse-code/extending#multi-agent — no Muse Code
source was referenced by either the donor or this port.

When isolation is on, each delegated child gets its own git worktree checked
out from the parent's current commit, so parallel children never contend for
the same working copy and the parent's checkout stays untouched.

Enable with the ``JAEGER_SUBAGENT_WORKTREE`` env var (default: off).

Contract, carried over from the donor unchanged:

- **Opt-in and git-only.** In a non-git workspace the setting is ignored
  without an error and children share the parent's working directory.
- **One worktree per child**, branched from the repo's current ``HEAD`` under
  ``<repo>/.worktrees/subagent-<id>`` on branch ``jaeger-subagent/<id>``.
- **The parent reviews/merges.** Children commit inside their own worktree;
  each result reports worktree path, branch, commit count and dirty state.
- **Clean worktrees are pruned** — but pruning requires affirmative proof. If
  a git inspection probe fails, the state is unknown, so the worktree is kept
  and the payload carries ``inspection_failed`` + ``note``. This is the
  donor's #88113 fix and it is the single most important behaviour in the
  file: a destructive cleanup must never run on an unmeasured default.

ADAPTATIONS for Jaeger:

- The donor gates on its terminal backend being local, because a worktree
  created on the host is invisible inside a docker/ssh sandbox. Jaeger's
  child agents run in-process against the same filesystem
  (``main.py::_delegate_internal``), so there is no remote-backend case to
  exclude and that gate is dropped rather than faked.
- The donor's isolation is applied by handing the child a cwd. Jaeger has no
  per-child cwd — file and code tools resolve against
  ``workspace.get_project_root()``, a ContextVar. So :func:`isolated_child`
  swaps that ContextVar for the duration of the child's turn, which is the
  equivalent seam and is inherited by anything the child spawns.
- Branch namespace renamed ``hermes-subagent`` → ``jaeger-subagent`` so the
  two agents can operate on the same repo without colliding.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 30
_WORKTREES_DIRNAME = ".worktrees"
_BRANCH_NAMESPACE = "jaeger-subagent"


def isolation_enabled() -> bool:
    """Opt-in via ``JAEGER_SUBAGENT_WORKTREE``. Default OFF.

    Matches the donor's ``delegation.worktree_isolation: false`` default:
    isolation changes where a child's writes land, so it is never turned on
    behind the operator's back.
    """
    return os.environ.get(
        "JAEGER_SUBAGENT_WORKTREE", "").strip().lower() in ("1", "true", "yes", "on")


def _run_git(args, cwd: str, timeout: int = _GIT_TIMEOUT):
    """Run a git command, capturing output. Never raises on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def resolve_repo_root(path: str | None) -> str | None:
    """Return the git toplevel for *path*, or None when not in a work tree."""
    if not path:
        return None
    try:
        candidate = os.path.abspath(os.path.expanduser(str(path)))
    except Exception:
        return None
    if not os.path.isdir(candidate):
        return None
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=candidate)
    except Exception as exc:
        logger.debug("subagent worktree: rev-parse failed: %s", exc)
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _ensure_gitignore_entry(repo_root: str) -> None:
    """Best-effort: keep ``.worktrees/`` out of git status."""
    gitignore = Path(repo_root) / ".gitignore"
    entry = f"{_WORKTREES_DIRNAME}/"
    try:
        existing = (
            gitignore.read_text(encoding="utf-8-sig", errors="replace")
            if gitignore.exists()
            else ""
        )
        if entry not in existing.splitlines():
            with open(gitignore, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{entry}\n")
    except Exception as exc:
        logger.debug("subagent worktree: could not update .gitignore: %s", exc)


def create_subagent_worktree(
    parent_cwd: str | None,
    subagent_id: str | None = None,
) -> dict[str, str] | None:
    """Create an isolated worktree for one child agent.

    Returns metadata (``path``, ``branch``, ``repo_root``, ``base_commit``)
    on success, or ``None`` when the workspace is not a git repository or
    worktree creation fails — absence of git downgrades silently to
    shared-workspace behaviour.
    """
    repo_root = resolve_repo_root(parent_cwd)
    if not repo_root:
        return None

    short_id = (subagent_id or uuid.uuid4().hex[:8]).replace("/", "-")
    wt_name = f"subagent-{short_id}"
    branch = f"{_BRANCH_NAMESPACE}/{wt_name}"
    wt_path = Path(repo_root) / _WORKTREES_DIRNAME / wt_name

    try:
        wt_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(
            "subagent worktree: cannot create %s: %s", wt_path.parent, exc)
        return None

    _ensure_gitignore_entry(repo_root)

    try:
        base = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        base_commit = base.stdout.strip() if base.returncode == 0 else ""
        result = _run_git(
            ["worktree", "add", str(wt_path), "-b", branch, "HEAD"],
            cwd=repo_root,
        )
    except Exception as exc:
        logger.warning("subagent worktree: creation failed: %s", exc)
        return None
    if result.returncode != 0:
        # Common on repos with zero commits (unborn HEAD) — degrade silently.
        logger.warning(
            "subagent worktree: git worktree add failed: %s",
            result.stderr.strip(),
        )
        return None

    logger.info("subagent worktree created: %s (branch %s)", wt_path, branch)
    return {
        "path": str(wt_path),
        "branch": branch,
        "repo_root": repo_root,
        "base_commit": base_commit,
    }


def mark_worktree_payload_unproven(
    payload: dict[str, Any], reason: str, *, unmeasured: str = "commits/dirty"
) -> dict[str, Any]:
    """Flag a worktree result payload as un-inspected, in place.

    A failed probe proves nothing about the tree, so the fields it would have
    filled keep their defaults. The parent agent only ever sees this dict — it
    cannot read logs — so the uncertainty has to travel *in the payload*, or
    "0 commits, clean" reads as "the child produced nothing" and the work just
    preserved is never looked at.

    *unmeasured* names only the fields this failure actually left unproven:
    one probe can succeed while the other fails, and claiming a measured value
    is UNKNOWN would be its own kind of misreport.
    """
    path = payload.get("path", "")
    branch = payload.get("branch", "")
    payload["inspection_failed"] = True
    payload["note"] = (
        f"git inspection failed ({reason}): {unmeasured} UNKNOWN — not "
        "proven zero/clean. The worktree and branch were preserved "
        f"— inspect {path} (branch {branch}) before assuming no work."
    )
    logger.warning(
        "subagent worktree: git inspection failed (%s) — keeping %s "
        "(branch %s) for manual review", reason, path, branch,
    )
    return payload


def unproven_worktree_payload(info: dict[str, str], reason: str) -> dict[str, Any]:
    """Build a complete un-inspected payload from creation-side *info*.

    For callers that never got a payload back at all (the delegate fallback
    when :func:`finalize_subagent_worktree` itself raises). Emits exactly the
    schema the parent expects — notably WITHOUT the creation-side
    ``repo_root``/``base_commit`` internals.
    """
    return mark_worktree_payload_unproven(
        {
            "path": info.get("path", ""),
            "branch": info.get("branch", ""),
            "commits": 0,
            "dirty": False,
            "pruned": False,
        },
        reason,
    )


def finalize_subagent_worktree(
    info: dict[str, str], *, prune: bool = True
) -> dict[str, Any]:
    """Inspect (and possibly prune) a child worktree after the child finishes.

    Returns a result-entry payload: path, branch, ``commits`` ahead of the
    base, ``dirty`` (uncommitted changes present), and ``pruned``. A worktree
    with zero commits and a clean tree is removed when *prune* is true **and
    both git probes succeeded**; anything holding work is always kept.

    If ``git rev-list``/``git status`` exits non-zero (or the inspection
    raises), the tree state is unknown, so the worktree and branch are kept
    and the payload carries ``inspection_failed: True`` plus a ``note``.
    ``commits``/``dirty`` are then defaults, NOT measurements.
    """
    path = info.get("path", "")
    branch = info.get("branch", "")
    repo_root = info.get("repo_root", "")
    base_commit = info.get("base_commit", "")

    payload: dict[str, Any] = {
        "path": path,
        "branch": branch,
        "commits": 0,
        "dirty": False,
        "pruned": False,
    }
    if not path or not os.path.isdir(path):
        payload["pruned"] = True  # nothing on disk to review
        return payload

    def _unproven(reason: str, *, unmeasured: str = "commits/dirty") -> dict[str, Any]:
        return mark_worktree_payload_unproven(payload, reason, unmeasured=unmeasured)

    # A worktree whose commit count was never measured must not be pruned
    # either: the prune condition reads payload["commits"], and without a base
    # commit that value is an unproven default.
    if not base_commit:
        return _unproven(
            "no base_commit recorded — commit count unmeasurable",
            unmeasured="commits",
        )

    failed: list[str] = []
    unmeasured: list[str] = []
    try:
        counted = _run_git(["rev-list", "--count", f"{base_commit}..HEAD"], cwd=path)
        if counted.returncode == 0:
            payload["commits"] = int(counted.stdout.strip() or 0)
        else:
            failed.append(
                f"rev-list exit {counted.returncode}: "
                f"{counted.stderr.strip()[:200]}")
            unmeasured.append("commits")
        status = _run_git(["status", "--porcelain"], cwd=path)
        if status.returncode == 0:
            payload["dirty"] = bool(status.stdout.strip())
        else:
            failed.append(
                f"status exit {status.returncode}: {status.stderr.strip()[:200]}")
            unmeasured.append("dirty")
    except Exception as exc:
        # Same unknown state as a non-zero exit (timeout, OSError, or a
        # non-numeric rev-list stdout) — keep the worktree rather than risk
        # deleting work. Which probe raised is unknowable here, so neither
        # value is trustworthy.
        return _unproven(f"inspection raised: {exc}")

    if failed:
        # Fail-safe: a destructive cleanup requires affirmative proof of
        # "zero commits + clean tree"; the defaults prove nothing.
        return _unproven("; ".join(failed), unmeasured="/".join(unmeasured))

    if prune and payload["commits"] == 0 and not payload["dirty"]:
        try:
            removed = _run_git(
                ["worktree", "remove", "--force", path], cwd=repo_root or path)
            if removed.returncode == 0:
                _run_git(["branch", "-D", branch], cwd=repo_root or path)
                payload["pruned"] = True
                logger.info("subagent worktree pruned (no work): %s", path)
            else:
                logger.debug(
                    "subagent worktree: prune failed: %s", removed.stderr.strip())
        except Exception as exc:
            logger.debug("subagent worktree: prune failed: %s", exc)

    return payload


def build_worktree_context_note(info: dict[str, str]) -> str:
    """Context block telling the child to work inside its isolated worktree."""
    return (
        "\n\n[WORKTREE ISOLATION] You are working in an isolated git worktree "
        f"at: {info.get('path')}\n"
        f"Your dedicated branch is: {info.get('branch')}\n"
        "All file edits and shell commands must happen inside this worktree "
        "directory (your workspace already points there). Do NOT cd to the "
        "main repository checkout. Commit your changes to your branch when "
        "done; the parent agent will review and merge your branch. If you "
        "make no commits and leave the tree clean, the worktree is discarded "
        "automatically."
    )


@contextmanager
def isolated_child(subagent_id: str | None = None) -> Iterator[dict[str, Any] | None]:
    """Run a delegated child against its own worktree.

    Yields the creation ``info`` dict (with a ``context_note``), or ``None``
    when isolation is off / unavailable — in which case the child simply runs
    against the parent's workspace, exactly as before.

    This is the Jaeger-side seam the donor did not need: it swaps
    ``workspace.set_project_root`` for the body's duration so the child's
    file and code tools resolve inside the worktree, then restores the
    parent's root and finalizes the worktree on the way out.

    The finalize payload is attached to the yielded dict as ``result`` so the
    caller can surface commits/dirty/pruned to the parent agent.
    """
    from jaeger_agent import workspace as _ws

    if not isolation_enabled():
        yield None
        return

    parent_root = _ws.get_project_root()
    info = create_subagent_worktree(str(parent_root) if parent_root else None,
                                    subagent_id)
    if not info:
        yield None
        return

    payload: dict[str, Any] = dict(info)
    payload["context_note"] = build_worktree_context_note(info)
    try:
        _ws.set_project_root(info["path"])
    except Exception as exc:
        # The worktree exists but we cannot point the child at it. Running
        # the child against the parent root would silently defeat isolation,
        # so finalize (keeping any work) and fall back explicitly.
        logger.warning(
            "subagent worktree: could not rebind project root (%s); "
            "running without isolation", exc)
        payload["result"] = finalize_subagent_worktree(info)
        yield None
        return

    try:
        yield payload
    finally:
        try:
            _ws.set_project_root(parent_root)
        except Exception:  # pragma: no cover — restore is best-effort
            logger.warning("subagent worktree: failed to restore project root")
        try:
            payload["result"] = finalize_subagent_worktree(info)
        except Exception as exc:
            payload["result"] = unproven_worktree_payload(
                info, f"finalize raised: {exc}")


__all__ = [
    "build_worktree_context_note",
    "create_subagent_worktree",
    "finalize_subagent_worktree",
    "isolated_child",
    "isolation_enabled",
    "mark_worktree_payload_unproven",
    "resolve_repo_root",
    "unproven_worktree_payload",
]
