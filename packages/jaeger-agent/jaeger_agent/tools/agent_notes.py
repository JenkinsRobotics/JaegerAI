"""agent_notes — a specialist's own memory file (``memory/agents/<name>/NOTES.md``).

The Gateway (jaegerd) binds the directory for the duration of a specialist
turn; the model never names a path, so one agent cannot read or write another
agent's notes, and outside a specialist turn the tool refuses.
"""
from __future__ import annotations

import contextlib
import contextvars
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

NOTES_MAX_CHARS = 16000
_notes_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar("jaeger_agent_notes_dir", default=None)


@contextlib.contextmanager
def bound_notes_dir(path: Path | None):
    token = _notes_dir.set(Path(path) if path else None)
    try:
        yield
    finally:
        _notes_dir.reset(token)


@register_tool_from_function(name="agent_notes", side_effect="write")
def agent_notes(action: str = "read", text: str = "") -> dict[str, Any]:
    """Your own persistent notes as this specialist agent.

    action: "read" (default), "append" (add a line/paragraph) or "replace"
    (rewrite all notes with ``text``). Keep notes short: preferences, recurring
    facts and open threads for your specialty."""
    root = _notes_dir.get()
    if root is None:
        return {"ok": False, "error": "agent_notes is only available to a specialist agent"}
    path = root / "NOTES.md"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    act = (action or "read").strip().lower()
    if act == "read":
        return {"ok": True, "notes": current}
    if act not in {"append", "replace"}:
        return {"ok": False, "error": "action must be read, append or replace"}
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": "text is required"}
    new = (current.rstrip() + "\n" + body + "\n").lstrip() if act == "append" else body + "\n"
    if len(new) > NOTES_MAX_CHARS:
        return {"ok": False, "error": f"notes would exceed {NOTES_MAX_CHARS} characters; replace with a summary"}
    root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "chars": len(new)}
