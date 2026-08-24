"""Shared infrastructure for every Jaeger tool module.

Anything used by 2+ tool files lives here:
  • Module-level binding to the active InstanceLayout
  • Sandboxed path resolver (instance/skills/ scope enforcement)
  • Audit logger (logs/audit.log)
  • Git auto-commit helper for file_write

Each tool category file does `from ._common import _audit, ...` rather
than reaching back into the rest of the framework directly. Keeps
category files focused on their tools, free of cross-skill plumbing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only — no runtime dependency on a host
    from jaeger_ai.core.instance.instance import InstanceLayout


# ---------------------------------------------------------------------------
# Module-level binding: which instance does this process serve?
# ---------------------------------------------------------------------------
_layout: InstanceLayout | None = None
# INST-11: optional workspace override. When set, ``_resolve_write``
# routes ``workspace/...`` paths here instead of
# ``<instance>/workspace/``. Populated from ``config.yaml``'s
# ``workspace.location`` field; left None when the user wants the
# default in-instance location.
_workspace_override: Path | None = None
# The PROJECT the agent is currently working in — the directory a surface
# means when it says "switch workspace". Distinct from
# ``_workspace_override``, which only decides where ``workspace/...`` writes
# land inside the sandbox.
#
# Before this existed the two were conflated, and the consequence was that a
# workspace switch changed nothing an agent could observe: ``run_shell`` ran in
# a throwaway tempdir, relative reads resolved against wherever the process was
# launched, and ``grep_files(".")`` searched the instance's skills directory.
# The selector moved a value that no tool consumed.
_project_root: Path | None = None


def bind(layout: InstanceLayout,
         *, workspace_override: Path | str | None = None,
         project_root: Path | str | None = None) -> None:
    """Wire all tool I/O to a specific instance dir. Called once at startup.

    ``workspace_override`` (INST-11) — when non-None, all writes to
    ``workspace/...`` land at this absolute path instead of
    ``<instance>/workspace/``. Useful when the user wants easy Finder
    / Spotlight access to generated outputs (e.g.
    ``~/Documents/Jaeger Outputs/``). The override path is created
    on bind if it doesn't exist.

    ``project_root`` — the directory the agent is CURRENTLY WORKING IN. This is
    what a surface means by "the workspace": shell commands run there, relative
    reads resolve there first, and a default-rooted search starts there. Unlike
    ``workspace_override`` it is never created implicitly — a project directory
    that does not exist is a caller mistake, not something to conjure.

    The two are deliberately separate. ``workspace_override`` is about where
    generated OUTPUT is filed; ``project_root`` is about which codebase the
    agent is looking at. Passing only the former (as every caller did before
    this parameter existed) leaves tools rooted where the process launched.
    """
    from jaeger_agent.memory import memory as mem
    global _layout, _workspace_override, _project_root
    _layout = layout
    if workspace_override is not None:
        path = Path(workspace_override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        _workspace_override = path
    else:
        _workspace_override = None
    if project_root is not None:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project_root is not a directory: {root}")
        _project_root = root
    else:
        _project_root = None
    mem.bind(layout)


def get_project_root() -> Path | None:
    """The directory the agent is working in, or None when unbound.

    None means "no project selected" and every caller must fall back to its
    previous behaviour, so an unbound agent behaves exactly as it did before
    this concept existed.
    """
    return _project_root


def set_project_root(path: Path | str | None) -> None:
    """Rebind the project without re-binding the whole instance.

    A surface switches project far more often than it switches instance, and
    ``bind()`` also rebinds memory — doing that per switch would be both
    wasteful and a wider blast radius than the change deserves.
    """
    global _project_root
    if path is None:
        _project_root = None
        return
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    _project_root = root


class DefaultWorkspace:
    """The seven paths every tool in this module needs, and nothing else.

    That is the whole contract a host has to satisfy — JaegerAI's
    ``InstanceLayout`` satisfies it structurally, and so does this. It
    exists so an embedder is not forced to write a layout class before
    ``read_file`` works.

    Rooted at ``<cwd>/.jaeger_agent`` on purpose. A brain that scatters
    state into ``~`` or a temp directory is one you cannot inspect,
    commit, or delete alongside the project it belongs to; a robot's
    workspace lives with the robot's code. Pass ``root=`` for anywhere
    else.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or Path.cwd() / ".jaeger_agent").expanduser().resolve()
        self.logs_dir = self.root / "logs"
        self.skills_dir = self.root / "skills"
        self.memory_dir = self.root / "memory"
        self.workspace_dir = self.root / "workspace"
        self.audit_log_path = self.logs_dir / "audit.log"
        self.config_path = self.root / "config.yaml"
        self.identity_path = self.root / "identity.yaml"

    def create(self) -> "DefaultWorkspace":
        for directory in (self.logs_dir, self.skills_dir,
                          self.memory_dir, self.workspace_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def ensure_bound(root: Path | str | None = None) -> InstanceLayout:
    """Bind a workspace if the host has not, creating it on disk.

    Idempotent: an application that already called :func:`bind` keeps
    its own layout untouched.
    """
    global _layout
    if _layout is None:
        bind(DefaultWorkspace(root).create())
    return _layout  # type: ignore[return-value]


def _require_layout() -> InstanceLayout:
    """The bound layout, or a clear error.

    Deliberately does NOT auto-create. An earlier cut had it call
    :func:`ensure_bound` so a bare install could write files with no
    setup — which also meant a read-only STATUS probe minted a
    ``.jaeger_agent`` directory as a side effect of rendering a line of
    text. Creating state is not something a getter may do.

    Auto-creation happens once, where an agent is actually built:
    :class:`~jaeger_agent.runtime.DefaultAgentRuntime` calls
    :func:`ensure_bound` in its constructor. An application binds its
    own instance instead and never reaches either path.
    """
    if _layout is None:
        raise RuntimeError(
            "no workspace bound — call jaeger_agent.workspace.ensure_bound() "
            "for a default at <cwd>/.jaeger_agent, or bind(layout) to use "
            "your own"
        )
    return _layout


def get_layout() -> InstanceLayout:
    """Public accessor for tool files that need the active layout."""
    return _require_layout()


# Runtime session key for admin-gated tools (certify_admin). Set per-turn by
# the dispatch layer; read by tools that live in tools/ but need to know WHO
# is asking — without importing main._pipeline (which would invert the
# tool→core layering the way _common did before it moved into core).
_current_session: str = ""


def set_current_session(key: str) -> None:
    """Record the current session key (``channel:id`` or ``local``). Mirrors
    what used to live in ``main._pipeline['current_session']``."""
    global _current_session
    _current_session = key or ""


def get_current_session() -> str:
    """The current session key, or ``''`` when unset."""
    return _current_session


def get_effective_workspace_dir() -> Path:
    """Where ``workspace/...`` writes actually land. Honours the
    override set by ``bind(workspace_override=...)`` if any;
    otherwise returns ``<instance>/workspace/``.
    """
    if _workspace_override is not None:
        return _workspace_override
    return _require_layout().workspace_dir


# ---------------------------------------------------------------------------
# Audit log — every sandbox-relevant operation gets recorded
# ---------------------------------------------------------------------------
def _audit(event: str, payload: dict[str, Any]) -> None:
    layout = _require_layout()
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {"ts": ts, "event": event, **payload}
    # Redact secrets before they land in the tamper-evident audit log —
    # a run_shell command or tool arg can carry an API key (audit A3).
    from jaeger_os.core.safety.redact import redact_obj
    entry = redact_obj(entry)
    # Canonical append-only JSONL — forensic record, never skipped.
    with layout.audit_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
    # DB-7: mirror into SQL so ``--doctor`` + ``jaeger memory export``
    # can query without scanning JSONL. Best-effort; the JSONL above
    # is the source of truth.
    try:
        from jaeger_agent.memory import memory as _mem
        # Pull session_key out of the payload if present so it lands in
        # its own column for cheap WHERE filtering.
        sk = entry.get("session_key") if isinstance(entry, dict) else None
        # Build the SQL payload from the redacted entry minus the
        # already-extracted columns.
        sql_payload = {
            k: v for k, v in entry.items()
            if k not in ("ts", "event", "session_key")
        }
        _mem.record_audit_event(
            event=event, payload=sql_payload, session_key=sk, ts=ts,
        )
    except Exception:  # noqa: BLE001 — JSONL is canonical; SQL is advisory
        pass


# ---------------------------------------------------------------------------
# Sandboxed path resolver (used by file_write / file_read / list_skill_dir)
# ---------------------------------------------------------------------------
class SandboxError(ValueError):
    """Raised when a path argument escapes the allowed zone."""


def _resolve_under(root: Path, path: str) -> Path:
    """Resolve `path` relative to `root` and verify the result lives inside
    `root`. Rejects absolute paths, `..` escapes, and symlinks that point
    outside the sandbox.

    Strips a leading `<root.name>/` prefix to make agent-supplied paths
    idempotent — Gemma 4 routinely says `skills/foo.txt` even though our
    file tools already sandbox to skills/. Without this, that produced
    `skills/skills/foo.txt`. Safe because we only strip when the first
    path component equals the sandbox root's own basename.
    """
    if not path:
        raise SandboxError("path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise SandboxError("absolute paths are not allowed")
    if any(part == ".." for part in p.parts):
        raise SandboxError("'..' is not allowed in paths")
    if p.parts and p.parts[0] == root.name:
        p = Path(*p.parts[1:]) if len(p.parts) > 1 else Path(".")

    full = (root / p).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError as exc:
        raise SandboxError(f"path escapes the sandbox: {path!r}") from exc
    return full


def _resolve_write(path: str) -> Path:
    """Resolve a path for an agent WRITE operation. Picks the
    sandbox root from the lead path component (INST-11):

      - ``workspace/...`` → the effective workspace dir. Default is
        ``<instance>/workspace/``; user can point this elsewhere via
        ``config.yaml``'s ``workspace.location`` (e.g.
        ``~/Documents/Jaeger Outputs/``) for easy Finder / Spotlight
        access to generated outputs.
      - everything else → ``<instance>/skills/`` — code modules
        (``SKILL.md`` + ``.py`` files). Backward-compatible default
        — bare paths (e.g. ``my_skill.py``) still land here so the
        library of authored skills isn't disturbed.

    Routing the lead path component keeps the boundary explicit:
    the model sees a path and knows where it goes, the sandbox
    enforces the choice.

    Returns the absolute path; raises :class:`SandboxError` on any
    boundary violation. Caller does the actual write.
    """
    layout = _require_layout()
    if not path:
        raise SandboxError("path must be non-empty")
    p = Path(path)
    # Lead component picks the sandbox root.
    if p.parts and p.parts[0] == "workspace":
        # Strip the ``workspace/`` prefix BEFORE passing to
        # ``_resolve_under``. The leading-strip inside that helper
        # only fires when the sandbox root happens to be named
        # ``workspace`` — true for the default
        # ``<instance>/workspace/`` location, but not when the user
        # pointed ``workspace.location`` at ``~/Documents/Outputs``
        # or similar. Explicit strip keeps the routing predictable.
        rest = Path(*p.parts[1:]) if len(p.parts) > 1 else Path(".")
        return _resolve_under(get_effective_workspace_dir(), str(rest))
    # Option A (validated): a bare path that ALREADY exists in the
    # workspace is a workspace write. New bare names still land in
    # skills/ so authored skills keep working. The stricter
    # alternative — never writing a bare name to workspace, even
    # when the file is sitting there — broke "append to the files
    # you just listed" for batch jobs seeded in workspace/.
    if p.parts and p.parts[0] != "skills":
        try:
            existing = _resolve_under(get_effective_workspace_dir(), path)
        except SandboxError:
            existing = None
        if existing is not None and existing.exists():
            return existing
    return _resolve_under(layout.skills_dir, path)


def _resolve_read(path: str) -> Path:
    """Resolve a path for a READ operation.

    Reads are deliberately **unconfined** — Jaeger can read its own
    source, the whole repository it lives in, and the wider system, so
    it can reason about the codebase. Writes stay sandboxed (see
    :func:`_resolve_under`). The one carve-out: never a file inside a
    ``credentials/`` directory — secrets go through ``get_credential``.

    Path resolution: an absolute path (and ``~``) is honoured as-is. A
    relative path is tried **cwd-first** (so ``src/jaeger_os/main.py``
    reads the repo naturally), then falls back to the **instance root**
    (so a workspace-relative path like ``skills/foo.py`` still resolves
    even when cwd isn't the instance)."""
    if not path:
        raise SandboxError("path must be non-empty")
    p = Path(path).expanduser()
    if p.is_absolute():
        full = p.resolve()
    else:
        # Project root first when one is bound. A relative read like
        # ``src/main.py`` means "in the project I am working on"; resolving it
        # against ``Path.cwd()`` meant "wherever this process happened to be
        # launched", which for an app opened from Finder is the user's home.
        # Falls through to the old cwd behaviour when nothing is bound.
        full = None
        if _project_root is not None:
            candidate = (_project_root / p).resolve()
            if candidate.exists():
                full = candidate
        if full is None:
            full = (Path.cwd() / p).resolve()
        if not full.exists() and _layout is not None:
            # Fall back through the instance-relative roots a WRITE could
            # have targeted, so a bare relative name round-trips with the
            # write tools. ``_resolve_write`` sends bare names (e.g.
            # ``status.txt``) to ``skills/`` and ``workspace/...`` paths to
            # the effective workspace dir; a read of the same bare name must
            # find them. Try each root in turn — first existing wins. Without
            # the skills/ fallback, ``write_file("x.txt")`` then
            # ``read_file("x.txt")`` missed (tool-conditional, 2026-07-06).
            for base in (_layout.root,
                         get_effective_workspace_dir(),
                         _layout.skills_dir):
                cand = (base / p).resolve()
                if cand.exists():
                    full = cand
                    break
    if "credentials" in full.parts[:-1]:
        raise SandboxError(
            "credentials/ is off-limits to direct reads — "
            "use get_credential(name) instead"
        )
    # Reads are unconfined, but never an OS-level secret store —
    # ~/.ssh, .aws/credentials, a .env, … (audit A5).
    from jaeger_os.core.safety.file_safety import is_sensitive_path
    _sensitive = is_sensitive_path(full)
    if _sensitive:
        raise SandboxError(f"refused — {_sensitive}")
    return full


def _display_path(target: Path, layout: InstanceLayout) -> str:
    """Path for a tool result — relative to the instance root when the
    target lives inside it, otherwise the absolute path (so reads of the
    wider repo / system still report a sensible location)."""
    try:
        return str(target.relative_to(layout.root))
    except ValueError:
        return str(target)


# ---------------------------------------------------------------------------
# Git auto-commit — pairs with file_write to make every agent-authored
# change a real audit trail (commit per write, jaeger-agent author).
# ---------------------------------------------------------------------------
def git_autocommit(layout: InstanceLayout, rel_path: str, message: str) -> str | None:
    """Add + commit the agent-written file inside the instance's git repo.

    Best-effort: if git isn't available, or the repo wasn't initialized,
    or the staged content is unchanged, we silently return None. We never
    want a git hiccup to fail the agent's write — the on-disk content is
    the source of truth; git is the audit trail.
    """
    git_dir = layout.root / ".git"
    if not git_dir.exists() or shutil.which("git") is None:
        return None
    try:
        # INST-4: if the user opted into a per-instance HOME (via
        # the wizard's Step 6), let git pick up that identity. Otherwise
        # fall back to the legacy hardcoded "jaeger-agent" so agent
        # commits are still identifiable and don't accidentally use
        # the operating user's real .gitconfig.
        from jaeger_ai.core.instance.subprocess_env import (
            has_instance_home, subprocess_env_for_instance,
        )
        if has_instance_home(layout):
            env = subprocess_env_for_instance(layout)
        else:
            env = {
                "GIT_AUTHOR_NAME": "jaeger-agent",
                "GIT_AUTHOR_EMAIL": "agent@local",
                "GIT_COMMITTER_NAME": "jaeger-agent",
                "GIT_COMMITTER_EMAIL": "agent@local",
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(layout.root),
            }
        subprocess.run(
            ["git", "-C", str(layout.root), "add", rel_path],
            check=True, capture_output=True, timeout=5, env=env,
        )
        result = subprocess.run(
            ["git", "-C", str(layout.root), "commit", "-m", message],
            capture_output=True, timeout=5, env=env, text=True,
        )
        if result.returncode != 0:
            if "nothing to commit" in (result.stdout + result.stderr):
                return None
            _audit("git_commit_failed", {"path": rel_path, "stderr": result.stderr[:200]})
            return None
        sha = subprocess.run(
            ["git", "-C", str(layout.root), "rev-parse", "HEAD"],
            check=True, capture_output=True, timeout=5, text=True, env=env,
        ).stdout.strip()
        return sha[:12]
    except (subprocess.SubprocessError, OSError) as exc:
        _audit("git_commit_failed", {"path": rel_path, "error": str(exc)})
        return None
