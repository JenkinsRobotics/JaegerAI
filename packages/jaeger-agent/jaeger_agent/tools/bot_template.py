"""``export_bot_template`` — a shareable copy of this Jaeger's setup (parity P26).

What goes in: your own instance skills (SKILL.md folders), active routines
(schedule cron + prompt), and config.yaml with every secret-looking key
removed. What never goes in: memory, chats, credentials/vault, tokens,
workspace files. Every text file is run through the redaction check; any
file that still looks like it holds a secret is left out and listed.
Output: ``<workspace>/exports/jaeger-template-<date>.zip`` plus a manifest.
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any

from jaeger_tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import _require_layout

_SECRET_KEY = re.compile(r"(api_?key|_key$|^key$|token(?!s)|secret|password|passwd|credential|cookie|bearer|private)", re.I)
_SKIP_SKILL = re.compile(r"^(test_|self_test|\.)|\.(db|db-shm|db-wal|sqlite3?|pyc)$", re.I)
_MAX_FILE = 512 * 1024


def _redacted(text: str) -> bool:
    try:
        from jaeger_ai.core.redaction import redact_text
    except Exception:  # noqa: BLE001
        return False
    return redact_text(text) != text


def _scrub(value: Any, removed: list[str] | None = None, path: str = "") -> Any:
    """Drop secret-looking keys entirely (their names go in the manifest)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            here = f"{path}.{k}" if path else str(k)
            if _SECRET_KEY.search(str(k)):
                if removed is not None:
                    removed.append(here)
                continue
            out[k] = _scrub(v, removed, here)
        return out
    if isinstance(value, list):
        return [_scrub(v, removed, path) for v in value]
    return value


def export_bot_template(include_routines: bool = True) -> dict[str, Any]:
    layout = _require_layout()
    stamp = time.strftime("%Y-%m-%d-%H%M")
    out_dir = layout.workspace_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"jaeger-template-{stamp}.zip"
    skipped: list[str] = []
    skills: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        sdir = Path(layout.skills_dir)
        if sdir.is_dir():
            for folder in sorted(p for p in sdir.iterdir() if p.is_dir() and not _SKIP_SKILL.search(p.name)):
                if not (folder / "SKILL.md").is_file():
                    continue
                skills.append(folder.name)
                for f in sorted(folder.rglob("*")):
                    if not f.is_file() or _SKIP_SKILL.search(f.name) or f.stat().st_size > _MAX_FILE:
                        continue
                    rel = f"skills/{f.relative_to(sdir)}"
                    try:
                        text = f.read_text("utf-8")
                    except (UnicodeDecodeError, OSError):
                        skipped.append(f"{rel} (binary)")
                        continue
                    if _redacted(text):
                        skipped.append(f"{rel} (looks like it holds a secret)")
                        continue
                    zf.writestr(rel, text)
        routines: list[dict[str, Any]] = []
        if include_routines:
            db = Path(layout.memory_dir) / "state.db"
            if db.is_file():
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
                try:
                    for sid, cron, prompt, tz in con.execute(
                            "select schedule_id, cron, prompt, timezone from schedules where status='active'"):
                        if _redacted(prompt or ""):
                            skipped.append(f"routine {sid} (prompt looks like it holds a secret)")
                            continue
                        routines.append({"name": sid, "cron": cron, "prompt": prompt, "timezone": tz})
                finally:
                    con.close()
            zf.writestr("routines.json", json.dumps(routines, indent=2))
        settings_note = "none"
        removed_keys: list[str] = []
        cfg = Path(layout.config_path)
        if cfg.is_file():
            try:
                import yaml
                data = _scrub(yaml.safe_load(cfg.read_text("utf-8")) or {}, removed_keys)
                text = yaml.safe_dump(data, sort_keys=False)
                if _redacted(text):
                    skipped.append("config.yaml (still looks like it holds a secret)")
                else:
                    zf.writestr("settings.yaml", text)
                    settings_note = "config.yaml with secret-looking keys removed"
            except Exception as exc:  # noqa: BLE001
                skipped.append(f"config.yaml ({type(exc).__name__})")
        manifest = {"format": "jaeger.bot-template", "schema_version": 1, "created": stamp,
                    "skills": skills, "routines": len(routines), "settings": settings_note, "settings_keys_removed": removed_keys,
                    "excluded_always": ["memory", "chats", "credentials / vault", "tokens", "workspace files"],
                    "skipped": skipped}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    target.write_bytes(buf.getvalue())
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size, **manifest}


@register_tool_from_function(name="export_bot_template", side_effect="write")
def _t_export_bot_template(include_routines: bool = True) -> dict:
    """Export a shareable template of this Jaeger's setup to one zip file: your
    own skills, active routines (cron + prompt) and settings with secrets removed.
    Memory, chats, credentials, tokens and workspace files are never included.
    Use when the owner asks to share, export, or copy this bot's setup. Returns
    the zip path and a manifest of what went in and what was skipped."""
    return export_bot_template(include_routines=include_routines)
