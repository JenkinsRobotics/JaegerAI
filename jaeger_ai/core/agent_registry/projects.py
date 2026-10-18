"""Projects: a team working in one writable root.

A project binds a root folder, a team (agent ids), owner grants and delegation
limits. Handoffs and tasks that name a ``project_id`` run their child turns with
the project root as the bound workspace (the only writable root), so every
specialist writes into the same app folder.

Roots must sit under an owner-approved base directory
(``JAEGER_PROJECT_BASES``, colon separated). With no base configured, project
creation is refused: the owner opts in per machine.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

#: Commands a project grant may run without a fresh card (first word, plus the
#: allowed subcommands). Segments may be joined with ``&&``, ``||``, ``;`` or
#: ``|`` and redirected into files inside the root (``> f``, ``2> f``,
#: ``2>&1``, ``>/dev/null``); every segment must itself be granted. Command
#: substitution, backticks, process substitution, heredocs, background ``&``,
#: sudo/push/publish, ``find -exec/-delete`` and any path outside the root ask.
DEFAULT_COMMANDS: dict[str, tuple[str, ...]] = {
    "npm": ("test", "run", "start", "init", "ls"),
    "node": (),
    "git": ("init", "status", "diff", "add", "commit", "log", "rev-parse", "show"),
    "ls": (), "cat": (), "pwd": (), "echo": (), "mkdir": (), "head": (), "tail": (),
    "wc": (), "grep": (), "find": (), "test": (), "true": (),
}
_FORBIDDEN = re.compile(r"`|\$\(|<\(|>\(|<<|\bsudo\b|\bgit\s+push\b|\bgit\s+remote\b|\bnpm\s+publish\b")
#: fd duplication (2>&1, >&2) and discarding output touch no file.
_FD_DUP = re.compile(r"(?<![\w/])\d?>&\d\b")
_DEV_NULL = re.compile(r"(?<![\w/])(?:\d|&)?>>?\s*/dev/null(?![\w/])")
#: A remaining file redirection: optional fd, operator, target word.
_REDIRECT = re.compile(r"(?<![\w/])(\d?)(>>|>|<)\s*([^\s|;&<>]+)")
_SEPARATORS = re.compile(r"&&|\|\||\||;")
_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fls"})

HARD_MAX_DEPTH = 5
HARD_MAX_FANOUT = 8
HARD_MAX_CHILD_TIMEOUT_S = 3600


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def default_limits() -> dict[str, int]:
    """Delegation limits when a handoff names no project (env-configurable)."""
    return {
        "max_depth": min(_env_int("JAEGER_DELEGATION_MAX_DEPTH", 3), HARD_MAX_DEPTH),
        "max_fanout": min(_env_int("JAEGER_DELEGATION_MAX_FANOUT", 4), HARD_MAX_FANOUT),
        "child_timeout_s": min(_env_int("JAEGER_DELEGATION_MAX_CHILD_TIMEOUT_S", 1800), HARD_MAX_CHILD_TIMEOUT_S),
    }


def project_bases() -> list[Path]:
    raw = os.environ.get("JAEGER_PROJECT_BASES", "")
    return [Path(p).expanduser().resolve() for p in raw.split(":") if p.strip()]


class ProjectError(ValueError):
    pass


def _within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class ProjectStore:
    """JSON-backed project records next to the gateway session store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "projects": {}}
        return data if isinstance(data, dict) and isinstance(data.get("projects"), dict) else {"version": 1, "projects": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._load()["projects"].values(), key=lambda p: p.get("created_at", 0))

    def get(self, project_id: str) -> dict[str, Any] | None:
        return self._load()["projects"].get(str(project_id or ""))

    def create(self, *, name: str, root: str, team: list[str] | None = None,
               grants: dict[str, Any] | None = None, limits: dict[str, Any] | None = None,
               known_agents: set[str] | None = None) -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise ProjectError("name is required")
        if not root or not os.path.isabs(str(root)):
            raise ProjectError("root must be an absolute path")
        resolved = Path(root).expanduser().resolve()
        bases = project_bases()
        if not bases:
            raise ProjectError("no project base configured (JAEGER_PROJECT_BASES); the owner must approve one")
        if not any(_within(base, resolved) and resolved != base for base in bases):
            raise ProjectError(f"root must be inside an approved base: {', '.join(map(str, bases))}")
        members = [str(a).strip() for a in (team or []) if str(a).strip()]
        if known_agents is not None:
            unknown = [a for a in members if a not in known_agents]
            if unknown:
                raise ProjectError(f"unknown team agents: {unknown}")
        g = dict(grants or {})
        clean_grants = {
            "writes": bool(g.get("writes", True)),
            "handoffs": bool(g.get("handoffs", True)),
            "commands": sorted({str(c) for c in (g.get("commands") or DEFAULT_COMMANDS.keys())}
                               & set(DEFAULT_COMMANDS)),
        }
        base_limits = default_limits()
        lim = dict(limits or {})
        clean_limits = {
            "max_depth": max(1, min(int(lim.get("max_depth", base_limits["max_depth"])), HARD_MAX_DEPTH)),
            "max_fanout": max(1, min(int(lim.get("max_fanout", base_limits["max_fanout"])), HARD_MAX_FANOUT)),
            "child_timeout_s": max(30, min(int(lim.get("child_timeout_s", base_limits["child_timeout_s"])), HARD_MAX_CHILD_TIMEOUT_S)),
        }
        resolved.mkdir(parents=True, exist_ok=True)
        record = {
            "id": f"proj_{uuid.uuid4().hex[:12]}", "name": name[:120], "root": str(resolved),
            "team": members, "grants": clean_grants, "limits": clean_limits,
            "created_at": time.time(),
        }
        with self._lock:
            data = self._load()
            data["projects"][record["id"]] = record
            self._save(data)
        return record


def path_in_project(project: dict[str, Any], value: str) -> bool:
    root = Path(project["root"])
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = root / p
    try:
        return _within(root, p.resolve())
    except OSError:
        return False


def command_allowed(project: dict[str, Any], command: str) -> tuple[bool, str]:
    """Whether a shell command fits the project's command grant."""
    import shlex

    text = str(command or "").strip()
    if not text:
        return False, "empty command"
    if _FORBIDDEN.search(text):
        return False, "substitution, heredoc, sudo or push needs a fresh approval"
    text = _DEV_NULL.sub(" ", _FD_DUP.sub(" ", text))
    for _fd, _op, target in _REDIRECT.findall(text):
        if not path_in_project(project, target):
            return False, f"redirection outside the project root: {target}"
    text = _REDIRECT.sub(" ", text)
    if re.search(r"[<>]|(?<!&)&(?!&)", text):
        return False, "background job or unparsed redirection needs a fresh approval"
    allowed = set((project.get("grants") or {}).get("commands") or [])
    for segment in _SEPARATORS.split(text):
        try:
            words = shlex.split(segment)
        except ValueError:
            return False, "unparseable command"
        if not words:
            return False, "empty segment"
        if words[0] == "cd" and len(words) == 2 and path_in_project(project, words[1]):
            continue
        head = words[0]
        if head not in allowed or head not in DEFAULT_COMMANDS:
            return False, f"{head!r} is not in the project command grant"
        if head == "find" and _FIND_ACTIONS.intersection(words[1:]):
            return False, "find with -exec/-delete needs a fresh approval"
        subs = DEFAULT_COMMANDS[head]
        if subs:
            sub = next((w for w in words[1:] if not w.startswith("-")), "")
            if sub not in subs:
                return False, f"{head} {sub or '(none)'} is not in the project command grant"
        for word in words[1:]:
            if word.startswith("/") or word.startswith("~") or ".." in Path(word).parts:
                if not path_in_project(project, word):
                    return False, f"path outside the project root: {word}"
    return True, "project grant"
