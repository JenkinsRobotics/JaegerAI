"""Detect other agent frameworks on this Mac — presence only, never contents.

Each entry names where a framework keeps its sessions and memory, the CLI it
ships, and its app. ``detect`` stats paths and counts files by name; it opens
nothing. Reading goes through ``connectors`` and needs an owner grant.

Secret-bearing files are on a hard deny list that every reader checks
(``is_denied``) before opening anything.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Framework:
    id: str
    name: str
    roots: tuple[str, ...]  # relative to $HOME
    sessions: tuple[str, ...] = ()  # globs relative to the first existing root
    memory: tuple[str, ...] = ()
    cli: str | None = None
    apps: tuple[str, ...] = ()
    handoff: str | None = None  # how a task is handed over (see delegate.py)
    notes: str = ""
    readable: bool = True


KNOWN: tuple[Framework, ...] = (
    Framework("claude-code", "Claude Code", (".claude",), sessions=("projects/*/*.jsonl",),
              memory=("CLAUDE.md", "projects/*/memory/*.md"), cli="claude", apps=("Claude.app",), handoff="cli"),
    Framework("codex", "Codex", (".codex",), sessions=("sessions/**/*.jsonl",),
              memory=("AGENTS.md", "memories/*.md"), cli="codex", apps=("ChatGPT.app",), handoff="cli"),
    Framework("gemini", "Gemini CLI / Antigravity", (".gemini",),
              sessions=("tmp/*/chats/*.jsonl",), memory=("GEMINI.md", "antigravity/knowledge/**/*.md", "antigravity/brain/**/*.md"),
              cli="gemini", apps=("Antigravity.app", "Antigravity IDE.app"), handoff="cli"),
    Framework("grok", "Grok", (".grok",), sessions=("sessions/**/*.jsonl", "sessions/**/*.json"),
              memory=("memory-v2/**/*.md",), cli="grok", apps=("Grok Bot.app",), handoff="cli"),
    Framework("openclaw", "OpenClaw", (".openclaw",), cli="openclaw", handoff="a2a",
              notes="already a Jaeger third-party agent (tp:openclaw)", readable=False),
    Framework("continue", "Continue", (".continue",), sessions=("sessions/*.json",), readable=False,
              notes="detected only"),
    Framework("cursor", "Cursor", (".cursor",), cli="cursor-agent", apps=("Cursor.app",), readable=False),
    Framework("ollama", "Ollama", (".ollama",), cli="ollama", readable=False, notes="Jaeger's local model host"),
    Framework("lmstudio", "LM Studio", (".lmstudio",), cli="lms", apps=("LM Studio.app",), readable=False),
)

#: Never opened, listed or returned, whatever a grant says.
DENY_GLOBS: tuple[str, ...] = (
    "*auth*.json", "*oauth*", "*token*", "*credential*", "*secret*", "*.pem", "*.key", "*cookie*",
    "*keychain*", ".env", ".env.*", "*.env", "google_accounts.json", "installation_id", "settings*.json",
    "config.toml", "*.sqlite*", "*.db", "*.lock",
)


def is_denied(path: Path) -> bool:
    name = path.name.lower()
    if any(fnmatch.fnmatch(name, g) for g in DENY_GLOBS):
        return True
    return any(part.lower() in {"credentials", "secrets", ".ssh", "keychains"} for part in path.parts)


def by_id(fid: str) -> Framework | None:
    return next((f for f in KNOWN if f.id == fid), None)


def root_of(fw: Framework, home: Path) -> Path | None:
    return next((home / r for r in fw.roots if (home / r).is_dir()), None)


def matching_files(root: Path, globs: tuple[str, ...], limit: int = 5000) -> list[Path]:
    out: list[Path] = []
    for g in globs:
        for p in root.glob(g):
            if p.is_file() and not p.is_symlink() and not is_denied(p.relative_to(root)):
                out.append(p)
                if len(out) >= limit:
                    return out
    return out


def detect(home: Path | None = None, apps_dir: Path = Path("/Applications")) -> list[dict[str, Any]]:
    """Presence report for every known framework (no file contents)."""
    home = Path(home or os.path.expanduser("~"))
    report = []
    for fw in KNOWN:
        root = root_of(fw, home)
        cli = shutil.which(fw.cli) if fw.cli else None
        apps = [a for a in fw.apps if (apps_dir / a).exists()]
        entry: dict[str, Any] = {
            "id": fw.id, "name": fw.name, "installed": bool(root or cli or apps),
            "data_root": str(root) if root else None, "cli": cli, "apps": apps,
            "readable": fw.readable and root is not None, "handoff": fw.handoff if cli else None,
            "notes": fw.notes,
        }
        if root is not None and fw.readable:
            entry["counts"] = {"sessions": len(matching_files(root, fw.sessions)),
                               "memory": len(matching_files(root, fw.memory))}
        report.append(entry)
    return report
