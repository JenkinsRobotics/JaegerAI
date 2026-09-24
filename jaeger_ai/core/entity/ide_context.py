"""What the operator has open in their IDE, as a bounded block for the model.

The IDE extension sends the active file, the selected lines, the other open files
and the workspace folders with each turn (``options.ide`` on the turn body). That is
what lets "fix this function" or "what's in the file I have open" mean something.

Two rules: everything is size-capped, and only known keys survive :func:`clean`, so a
client (or anything spoofing one) cannot smuggle other execution options through this
door. :func:`format_block` renders plain text; the turn fences it as read-only JSON
data alongside the other background, so selected code is never read as an instruction.
"""
from __future__ import annotations

from typing import Any

MAX_SELECTION_CHARS = 4000
MAX_OPEN_FILES = 12
MAX_FOLDERS = 5
MAX_PATH_CHARS = 400


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _items(value: Any) -> list[Any]:
    """A list, or nothing: a bare string must not be iterated character by character."""
    return value if isinstance(value, list) else []


def _line(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 10_000_000 else None


def clean(raw: Any) -> dict[str, Any] | None:
    """The bounded, allow-listed IDE context, or ``None`` when there is nothing usable."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    folders = [_text(f, MAX_PATH_CHARS) for f in _items(raw.get("workspace_folders")) if isinstance(f, str)]
    if folders := [f for f in folders if f][:MAX_FOLDERS]:
        out["workspace_folders"] = folders
    if active := _text(raw.get("active_file"), MAX_PATH_CHARS):
        out["active_file"] = active
        if language := _text(raw.get("language"), 40):
            out["language"] = language
        if cursor := _line(raw.get("cursor_line")):
            out["cursor_line"] = cursor
    selection = raw.get("selection")
    if isinstance(selection, dict):
        body = str(selection.get("text") or "")
        if body.strip():
            out["selection"] = {
                "text": body[:MAX_SELECTION_CHARS],
                "truncated": len(body) > MAX_SELECTION_CHARS or bool(selection.get("truncated")),
                "start_line": _line(selection.get("start_line")) or 1,
                "end_line": _line(selection.get("end_line")) or 1,
            }
    seen: set[str] = set()
    files: list[str] = []
    for item in _items(raw.get("open_files")):
        path = _text(item, MAX_PATH_CHARS)
        if path and path not in seen and path != out.get("active_file"):
            seen.add(path)
            files.append(path)
        if len(files) >= MAX_OPEN_FILES:
            break
    if files:
        out["open_files"] = files
    return out or None


def format_block(ide: dict[str, Any] | None) -> str:
    """Plain-text description of the cleaned context ('' when empty)."""
    ide = clean(ide)
    if not ide:
        return ""
    lines = ["# IDE context: what the operator has open right now (may be stale; use it to "
             "resolve 'this file', 'the selection', 'my project'):"]
    if ide.get("workspace_folders"):
        lines.append(f"- Workspace: {', '.join(ide['workspace_folders'])}")
    if ide.get("active_file"):
        detail = f" ({ide['language']})" if ide.get("language") else ""
        cursor = f", cursor at line {ide['cursor_line']}" if ide.get("cursor_line") else ""
        lines.append(f"- Active file: {ide['active_file']}{detail}{cursor}")
    if sel := ide.get("selection"):
        lines.append(f"- Selected lines {sel['start_line']}-{sel['end_line']}"
                     f"{' (truncated)' if sel['truncated'] else ''}:\n{sel['text']}")
    if ide.get("open_files"):
        lines.append(f"- Other open files: {', '.join(ide['open_files'])}")
    return "\n".join(lines)
