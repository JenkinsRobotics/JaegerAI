"""Bidirectional Hermes-compatible MEMORY.md and USER.md sync over SqliteStateMemory.

Keeps Jaeger's structured SQLite facts and user-owned identity as the primary durable
store while allowing seamless import from and export to Hermes-style Markdown memory
files (`<state_dir>/MEMORY.md` and `<state_dir>/USER.md`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from .store import SqliteStateMemory

__all__ = [
    "export_memory_markdown",
    "import_memory_markdown",
    "sync_memory_markdown",
]

_FACT_LINE_RE = re.compile(r"^\s*[-*]\s+\*\*(?P<key>[^*:\n]{1,120})\*\*:\s*(?P<value>.+?)\s*$")
_SECTION_RE = re.compile(r"^\s*##\s+(?P<subject>[A-Za-z0-9_.-]{1,64})\s*$")
_PLAIN_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<key>[A-Za-z0-9_.-]{1,80}):\s*(?P<value>.+?)\s*$")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def export_memory_markdown(
    memory: SqliteStateMemory,
    target_dir: Path,
    *,
    identity_profile: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Render SQLite facts to `MEMORY.md` and optional identity summary to `USER.md`."""
    out_dir = Path(target_dir).expanduser().resolve()
    with memory._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT subject, key, value, category FROM facts ORDER BY subject ASC, key ASC"
        ).fetchall()

    grouped: dict[str, list[tuple[str, str, str | None]]] = {}
    for subj, key, value, cat in rows:
        grouped.setdefault(str(subj), []).append((str(key), str(value), str(cat) if cat else None))

    mem_lines = [
        "# Jaeger Memory (Hermes-Compatible)",
        "",
        "<!-- Auto-synced with SqliteStateMemory. Edit bullets as `- **key**: value` under `## subject`. -->",
        "",
    ]
    if not grouped:
        mem_lines.append("_No saved facts yet._")
    else:
        for subj, items in grouped.items():
            mem_lines.append(f"## {subj}")
            for key, value, cat in items:
                suffix = f" _(category: {cat})_" if cat else ""
                clean_val = " ".join(value.splitlines()).strip()
                mem_lines.append(f"- **{key}**: {clean_val}{suffix}")
            mem_lines.append("")

    memory_path = out_dir / "MEMORY.md"
    _atomic_write(memory_path, "\n".join(mem_lines).rstrip() + "\n")

    written = {"memory_md": str(memory_path)}
    if identity_profile is not None:
        owner = str(identity_profile.get("owner_name") or "").strip() or "Owner"
        agent = str(identity_profile.get("ai_name") or identity_profile.get("agent_name") or "").strip() or "Jaeger"
        user_lines = [
            "# User Profile (Hermes-Compatible)",
            "",
            f"- **owner_name**: {owner}",
            f"- **ai_name**: {agent}",
        ]
        for field_name in ("personality", "mission", "voice_id"):
            val = str(identity_profile.get(field_name) or "").strip()
            if val:
                user_lines.append(f"- **{field_name}**: {val}")
        user_lines.append("")
        user_path = out_dir / "USER.md"
        _atomic_write(user_path, "\n".join(user_lines))
        written["user_md"] = str(user_path)
    return written


def import_memory_markdown(
    memory: SqliteStateMemory,
    source_path: Path,
    *,
    default_subject: str = "user",
) -> dict[str, Any]:
    """Import `- **key**: value` or `- key: value` entries from a Hermes `MEMORY.md` file."""
    path = Path(source_path).expanduser().resolve()
    if not path.is_file():
        return {"imported": 0, "path": str(path), "existed": False}
    subject = default_subject
    imported = 0
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        sec = _SECTION_RE.match(raw_line)
        if sec:
            subject = sec.group("subject").strip()
            continue
        m = _FACT_LINE_RE.match(raw_line) or _PLAIN_BULLET_RE.match(raw_line)
        if not m:
            continue
        key = m.group("key").strip()
        val = m.group("value").strip()
        cat: str | None = None
        cat_m = re.search(r"\s*_\(category:\s*([^)]+)\)_$", val)
        if cat_m:
            cat = cat_m.group(1).strip()
            val = val[: cat_m.start()].strip()
        if key and val:
            existing = memory.recall(key, subject=subject)
            if existing != val:
                memory.remember(key, val, subject=subject, category=cat)
                imported += 1
    return {"imported": imported, "path": str(path), "existed": True}


def sync_memory_markdown(
    memory: SqliteStateMemory,
    state_dir: Path,
    *,
    identity_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bidirectional sync: import any manual edits from `MEMORY.md`, then re-export cleanly."""
    base = Path(state_dir).expanduser().resolve()
    imp = import_memory_markdown(memory, base / "MEMORY.md")
    exp = export_memory_markdown(memory, base, identity_profile=identity_profile)
    return {"imported": imp["imported"], **exp}
