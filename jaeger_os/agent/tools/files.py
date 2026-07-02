"""Sandboxed file tools — the heart of the v2 safety contract.

  • file_write(path, content)  — write/replace inside <instance>/skills/
  • append_file(path, content) — append inside <instance>/skills/
  • edit_file(path, old, new)  — surgical find/replace inside skills/
  • delete_file(path)          — delete inside <instance>/skills/
  • file_read(path)            — read ANYWHERE except credentials/
  • list_skill_dir(path)       — list any directory (default: skills/)
  • search_files(query, path)  — grep file contents anywhere

The read/write split is deliberate. **Reads are unconfined** — Jaeger
can read its own source, the whole repository it lives in, and the
wider system, so it can reason about the codebase. **Writes are
sandboxed** to <instance>/skills/ — the agent edits its own workspace,
never the framework. The one read it refuses is a credential file.

Every successful write/append/delete lands as a git commit inside the
instance dir, giving the human a real authorship audit trail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_os.core.context import (
    SandboxError,
    _audit,
    _display_path,
    _require_layout,
    _resolve_read,
    _resolve_under,
    _resolve_write,
    git_autocommit,
)

# Directories search_files never descends into — VCS internals, virtual
# envs, caches, and the multi-GB model store would swamp a content grep.
_SEARCH_SKIP = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".jaeger",
    "models", "dist", "build", ".idea",
})


# --- Unchanged-read dedup ------------------------------------------------------
# Re-reading a file that has not changed re-injects its whole content into the
# context for no gain — a common spin. file_read tracks each (file, offset,
# limit) read; once the same unchanged read has been served twice it returns a
# stub instead. ``main._run_via_iter`` calls reset_read_tracker() once per turn
# so dedup only ever fires within a single turn, never across turns.
_READ_TRACKER: dict[tuple[str, int, int | None], dict[str, Any]] = {}
_DEDUP_AFTER_READS = 2   # serve content for the first 2 reads; stub the 3rd+
_READ_TRACKER_CAP = 512  # bound the tracker against a pathological turn


def reset_read_tracker() -> None:
    """Clear the unchanged-read dedup state. Called once per turn."""
    _READ_TRACKER.clear()


def _remember_read(
    key: tuple[str, int, int | None], mtime: float, total_lines: int
) -> None:
    """Record that ``key`` was served fresh content at ``mtime``."""
    prev = _READ_TRACKER.get(key)
    if prev is not None and prev["mtime"] == mtime:
        prev["count"] += 1
        prev["total_lines"] = total_lines
        return
    if len(_READ_TRACKER) >= _READ_TRACKER_CAP:
        _READ_TRACKER.clear()
    _READ_TRACKER[key] = {"mtime": mtime, "count": 1, "total_lines": total_lines}


def _maybe_syntax_check(path_rel: str, content: str) -> dict[str, Any] | None:
    """Run ``compile()`` on Python content so the agent sees syntax
    errors the same turn it wrote them (Phase 2 of the coding-quality
    sprint). Returns a ``{"syntax_ok": bool, "syntax_error": str?}``
    fragment for the caller to merge into its result, or ``None`` if
    the path isn't a .py file (skip the check for text/data files).
    """
    if not path_rel.endswith(".py"):
        return None
    try:
        compile(content, path_rel, "exec")
    except SyntaxError as exc:
        # Show line:col + the offending text fragment so the model has
        # enough to fix it in the retry pass without re-reading the file.
        offender = (exc.text or "").rstrip()
        msg = f"{exc.msg} at line {exc.lineno}, col {exc.offset}"
        if offender:
            msg += f": {offender!r}"
        return {"syntax_ok": False, "syntax_error": msg}
    return {"syntax_ok": True}


def file_write(path: str, content: str) -> dict[str, Any]:
    """Write a text file inside the instance's sandbox.

    Two write destinations, picked by the lead path component:

      - ``workspace/...`` → ``<instance>/workspace/`` — general scratch
        and outputs: reports, downloads, generated data, ad-hoc notes.
      - everything else → ``<instance>/skills/`` — code modules
        (``SKILL.md`` + ``.py``). Backward-compatible default.

    Refuses absolute paths, ``..`` escapes, symlinks that escape the
    sandbox, and any attempt to touch identity.yaml / config.yaml /
    manifest.json / credentials / memory / logs. Every write is
    recorded in ``logs/audit.log`` AND auto-committed to the instance's
    git repo (best-effort) so the agent's authorship history is a real
    audit trail.
    """
    layout = _require_layout()
    try:
        target = _resolve_write(path)
    except SandboxError as exc:
        _audit("file_write_denied", {"path": path, "reason": str(exc)})
        return {"written": False, "error": str(exc)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    # ``_display_path`` falls back to absolute when target lives
    # outside the instance root — happens when the user pointed
    # ``workspace.location`` at a path elsewhere (INST-11).
    rel = _display_path(target, layout)
    bytes_written = len(content.encode("utf-8"))
    _audit("file_write", {"path": rel, "bytes": bytes_written})

    commit_sha = git_autocommit(layout, rel, f"agent: write {rel}")
    result: dict[str, Any] = {"written": True, "path": rel, "bytes": bytes_written}
    if commit_sha:
        result["commit"] = commit_sha
    syntax = _maybe_syntax_check(rel, content)
    if syntax is not None:
        result.update(syntax)
    return result


def append_file(path: str, content: str) -> dict[str, Any]:
    """Append text to an existing file under the instance sandbox.

    Same path-routing as file_write: ``workspace/...`` → workspace,
    anything else → skills. If the file doesn't exist yet, this
    creates it. Every append is audited + git-committed."""
    layout = _require_layout()
    try:
        target = _resolve_write(path)
    except SandboxError as exc:
        _audit("append_file_denied", {"path": path, "reason": str(exc)})
        return {"appended": False, "error": str(exc)}

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    rel = _display_path(target, layout)
    bytes_appended = len(content.encode("utf-8"))
    _audit("append_file", {"path": rel, "bytes": bytes_appended})
    commit_sha = git_autocommit(layout, rel, f"agent: append {rel}")
    result: dict[str, Any] = {"appended": True, "path": rel, "bytes": bytes_appended}
    if commit_sha:
        result["commit"] = commit_sha
    # Syntax-check the FULL post-append content so a half-written .py
    # appended onto a half-written .py still gets a clean pass/fail.
    if rel.endswith(".py"):
        try:
            full = target.read_text(encoding="utf-8")
        except OSError:
            full = None
        if full is not None:
            syntax = _maybe_syntax_check(rel, full)
            if syntax is not None:
                result.update(syntax)
    return result


def edit_file(path: str, old: str, new: str, replace_all: bool = False) -> dict[str, Any]:
    """Make a surgical find-and-replace edit to a file under skills/.

    Prefer this over file_write for changing an EXISTING file — it edits
    one region instead of regenerating the whole file, so a large file
    can't be lost to a truncated rewrite.

    ``old`` must appear EXACTLY once in the file (so the edit is
    unambiguous), unless ``replace_all`` is set. Refuses the edit and
    returns an error if ``old`` is absent, or present more than once
    while ``replace_all`` is false. Same sandbox enforcement, audit
    logging, git auto-commit and .py syntax check as file_write."""
    layout = _require_layout()
    try:
        target = _resolve_write(path)
    except SandboxError as exc:
        _audit("edit_file_denied", {"path": path, "reason": str(exc)})
        return {"edited": False, "error": str(exc)}

    if not target.exists() or not target.is_file():
        return {"edited": False, "error": "not found", "path": path}
    if old == new:
        return {"edited": False, "error": "old and new are identical", "path": path}

    original = target.read_text(encoding="utf-8")
    count = original.count(old)
    if count == 0:
        return {"edited": False, "error": "old text not found in file", "path": path}
    if count > 1 and not replace_all:
        return {
            "edited": False,
            "error": (f"old text appears {count}× — not unique. Pass a longer "
                      "unique snippet, or replace_all=true."),
            "path": path,
        }

    updated = original.replace(old, new)
    target.write_text(updated, encoding="utf-8")
    rel = _display_path(target, layout)
    replacements = count if replace_all else 1
    _audit("edit_file", {"path": rel, "replacements": replacements})

    commit_sha = git_autocommit(layout, rel, f"agent: edit {rel}")
    result: dict[str, Any] = {
        "edited": True, "path": rel, "replacements": replacements,
        "bytes": len(updated.encode("utf-8")),
    }
    if commit_sha:
        result["commit"] = commit_sha
    syntax = _maybe_syntax_check(rel, updated)
    if syntax is not None:
        result.update(syntax)
    return result


def delete_file(path: str) -> dict[str, Any]:
    """Delete a file under <instance>/skills/.

    Same sandbox enforcement as file_write. Refuses to delete:
      • anything outside skills/
      • directories (use rmdir-style ops manually if you really need)
      • non-existent files (returns deleted=False with reason)

    Every delete is audited + git-committed. The v2 contract's "preserve
    rollback paths" rule is satisfied by the git history: even after a
    delete, the file lives in the commit log inside the instance repo."""
    layout = _require_layout()
    try:
        target = _resolve_write(path)
    except SandboxError as exc:
        _audit("delete_file_denied", {"path": path, "reason": str(exc)})
        return {"deleted": False, "error": str(exc)}

    if not target.exists():
        return {"deleted": False, "reason": "not found", "path": path}
    if target.is_dir():
        return {"deleted": False, "reason": "is a directory", "path": path}

    rel = _display_path(target, layout)
    target.unlink()
    _audit("delete_file", {"path": rel})
    commit_sha = git_autocommit(layout, rel, f"agent: delete {rel}")
    result: dict[str, Any] = {"deleted": True, "path": rel}
    if commit_sha:
        result["commit"] = commit_sha
    return result


def file_read(path: str, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    """Read a text file from ANYWHERE — Jaeger's own source code, the
    repository it lives in, the wider system.

    Use this to study the codebase, inspect identity/config/manifest,
    prior skills, anything. The only read it refuses is a credential
    file (a hint points at ``get_credential()``).

    For a large file, page it: ``offset`` is the 0-based first line and
    ``limit`` the number of lines to return (default: the whole file).
    The result then also carries ``total_lines`` so you know how much
    is left.

    Re-reading a file that has not changed since you last read it this
    turn returns a short stub instead of the content again — use what
    you already have, or pass a new offset/limit to see a different part.
    """
    layout = _require_layout()
    try:
        target = _resolve_read(path)
    except SandboxError as exc:
        _audit("file_read_denied", {"path": path, "reason": str(exc)})
        return {"read": False, "error": str(exc)}

    if not target.exists():
        return {"read": False, "error": "not found", "path": path}
    if target.is_dir():
        return {"read": False, "error": "is a directory", "path": path}

    rel = _display_path(target, layout)
    off = max(0, int(offset or 0))
    key = (str(target), off, limit)
    try:
        mtime: float | None = target.stat().st_mtime
    except OSError:
        mtime = None

    # Unchanged-read dedup — stub a repeat read rather than re-inject the
    # whole payload (see the _READ_TRACKER notes above).
    if mtime is not None:
        prev = _READ_TRACKER.get(key)
        if (prev is not None and prev["mtime"] == mtime
                and prev["count"] >= _DEDUP_AFTER_READS):
            prev["count"] += 1
            return {
                "read": True, "path": rel, "unchanged": True,
                "total_lines": prev.get("total_lines"),
                "note": (
                    "Content omitted — this file is byte-for-byte identical "
                    f"to a read you already did this turn ({prev['count']} "
                    "reads). Use the content you already have; re-reading it "
                    "will not change anything. Pass a new offset/limit to "
                    "see a different part."
                ),
            }

    try:
        full = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"read": False, "error": f"unreadable (binary?): {exc}",
                "path": path}

    lines = full.splitlines(keepends=True)
    if off or limit is not None:
        end = len(lines) if limit is None else off + max(0, int(limit))
        content = "".join(lines[off:end])
        result: dict[str, Any] = {
            "read": True, "path": rel, "content": content,
            "bytes": len(content.encode("utf-8")),
            "offset": off, "total_lines": len(lines),
        }
    else:
        result = {
            "read": True, "path": rel, "content": full,
            "bytes": len(full.encode("utf-8")),
        }

    if mtime is not None:
        _remember_read(key, mtime, len(lines))
    return result


def list_skill_dir(path: str = ".") -> dict[str, Any]:
    """List a directory's contents. Defaults to the instance's skills/
    dir; pass any path — a repo subdirectory, an absolute path — to list
    elsewhere. Use it to explore the codebase or to discover existing
    skills before adding a new version (so the agent picks the right
    _vN suffix)."""
    layout = _require_layout()
    try:
        target = layout.skills_dir if path == "." else _resolve_read(path)
    except SandboxError as exc:
        return {"listed": False, "error": str(exc)}
    if not target.exists():
        return {"listed": True, "path": path, "entries": []}
    if not target.is_dir():
        return {"listed": False, "error": "not a directory", "path": path}

    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        entries.append({
            "name": child.name,
            "type": "directory" if child.is_dir() else "file",
            "bytes": child.stat().st_size if child.is_file() else None,
        })
    return {"listed": True, "path": _display_path(target, layout),
            "entries": entries}


def search_files(query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
    """Search file CONTENTS — a recursive, case-insensitive grep over
    the codebase.

    ``path`` defaults to the current directory (the repository when
    Jaeger is launched from its root); pass any directory to narrow it.
    Use this to find where something is defined or used instead of
    reading files one by one. Returns matches as ``{file, line, text}``;
    skips VCS/venv/cache dirs and the model store, binary files, and
    anything over 1 MB; caps at ``max_results``."""
    layout = _require_layout()
    needle = (query or "").lower()
    if not needle:
        return {"searched": False, "error": "empty query"}
    try:
        root = Path.cwd() if path == "." else _resolve_read(path)
    except SandboxError as exc:
        return {"searched": False, "error": str(exc)}
    if not root.exists():
        return {"searched": True, "query": query, "matches": [], "count": 0}

    cap = max(1, min(int(max_results or 50), 500))
    matches: list[dict[str, Any]] = []
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    for child in candidates:
        if not child.is_file():
            continue
        try:
            rel_parts = child.relative_to(root).parts
        except ValueError:
            rel_parts = child.parts
        if any(part in _SEARCH_SKIP for part in rel_parts):
            continue
        try:
            if child.stat().st_size > 1_000_000:
                continue
            text = child.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or binary — skip
        for lineno, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                matches.append({
                    "file": _display_path(child, layout),
                    "line": lineno,
                    "text": line.strip()[:200],
                })
                if len(matches) >= cap:
                    break
        if len(matches) >= cap:
            break
    return {
        "searched": True, "query": query, "matches": matches,
        "count": len(matches), "truncated": len(matches) >= cap,
    }
