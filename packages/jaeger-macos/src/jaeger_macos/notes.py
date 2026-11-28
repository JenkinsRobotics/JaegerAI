"""Native macOS Notes.app adapter using serialized, bounded AppleScript."""

from __future__ import annotations

import html
import re
from typing import Any, Callable

from .appleevents import escape_applescript, run_applescript

_FIELD_SEP = "\x1f"
_ROW_SEP = "\x1e"
_HTML_TAG_RE = re.compile(r"<[^>]+>")

LIST_FOLDERS_SCRIPT = """
tell application "Notes"
    set outList to {}
    repeat with f in folders
        set end of outList to (name of f)
    end repeat
    set AppleScript's text item delimiters to linefeed
    return outList as text
end tell
""".strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"<(?:br|div|p|li)[^>]*>", "\n", raw or "", flags=re.IGNORECASE)
    text = html.unescape(_HTML_TAG_RE.sub("", text))
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def list_note_folders(
    *,
    timeout_seconds: float = 15.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return all folder names from macOS Notes.app."""
    res = run_applescript(
        LIST_FOLDERS_SCRIPT,
        timeout_seconds=timeout_seconds,
        target="notes",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "folders": [], "error": res.get("error")}
    names = [line.strip() for line in str(res.get("raw_output") or "").splitlines() if line.strip()]
    return {"ok": True, "folders": names, "count": len(names), "error": None}


def search_notes(
    *,
    query: str = "",
    folder_name: str | None = None,
    limit: int = 20,
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """List or search Apple Notes by title substring (bounded by ``limit``)."""
    clamped_limit = max(1, min(int(limit or 20), 60))
    clean_q = (query or "").strip()
    folder_filter = (
        f'set targetFolders to {{folder "{escape_applescript(folder_name.strip())}"}}'
        if folder_name and folder_name.strip()
        else "set targetFolders to folders"
    )
    query_check = (
        f'if nName contains "{escape_applescript(clean_q)}" then'
        if clean_q
        else "if true then"
    )
    script = f"""
tell application "Notes"
    {folder_filter}
    set rows to {{}}
    set maxRows to {clamped_limit}
    repeat with f in targetFolders
        set fName to name of f
        repeat with n in notes of f
            if (count of rows) >= maxRows then exit repeat
            set nName to ""
            try
                set nName to name of n
            end try
            {query_check}
                set nId to ""
                try
                    set nId to id of n
                end try
                set nMod to ""
                try
                    set nMod to ((modification date of n) as «class isot» as string)
                end try
                set end of rows to (fName & "{_FIELD_SEP}" & nId & "{_FIELD_SEP}" & nName & "{_FIELD_SEP}" & nMod)
            end if
        end repeat
        if (count of rows) >= maxRows then exit repeat
    end repeat
    set AppleScript's text item delimiters to "{_ROW_SEP}"
    return rows as text
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="notes",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "notes": [], "error": res.get("error")}
    raw = str(res.get("raw_output") or "")
    notes: list[dict[str, str]] = []
    for row in raw.split(_ROW_SEP):
        if not row.strip():
            continue
        parts = row.split(_FIELD_SEP)
        while len(parts) < 4:
            parts.append("")
        notes.append({
            "folder": parts[0].strip(),
            "id": parts[1].strip(),
            "title": parts[2].strip(),
            "modified": parts[3].strip(),
        })
    return {"ok": True, "query": clean_q, "notes": notes, "count": len(notes), "error": None}


def read_note(
    *,
    title: str,
    folder_name: str | None = None,
    max_chars: int = 8000,
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read the plaintext body of the first Apple Note matching ``title``."""
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("title is required")
    escaped = escape_applescript(clean_title)
    folder_filter = (
        f'set targetFolders to {{folder "{escape_applescript(folder_name.strip())}"}}'
        if folder_name and folder_name.strip()
        else "set targetFolders to folders"
    )
    script = f"""
tell application "Notes"
    {folder_filter}
    repeat with f in targetFolders
        set matches to (every note of f whose name is "{escaped}")
        if (count of matches) > 0 then
            set n to item 1 of matches
            return (name of f) & "{_FIELD_SEP}" & (id of n) & "{_FIELD_SEP}" & (body of n)
        end if
    end repeat
    return ""
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="notes",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    raw = str(res.get("raw_output") or "")
    if not raw:
        return {"ok": False, "error": f"note not found: {clean_title}"}
    parts = raw.split(_FIELD_SEP, 2)
    body_html = parts[2] if len(parts) > 2 else ""
    plain = _strip_html(body_html)
    cap = max(200, min(int(max_chars or 8000), 32000))
    return {
        "ok": True,
        "folder": parts[0].strip(),
        "id": parts[1].strip() if len(parts) > 1 else "",
        "title": clean_title,
        "content": plain[:cap],
        "truncated": len(plain) > cap,
        "error": None,
    }


def create_note(
    *,
    title: str,
    body: str,
    folder_name: str = "Notes",
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Create a new Apple Note in ``folder_name`` (HTML-escaped safely)."""
    clean_title = (title or "").strip()
    if not clean_title or len(clean_title) > 200:
        raise ValueError("title must be 1-200 characters")
    clean_body = (body or "").strip()
    if len(clean_body) > 20_000:
        raise ValueError("body exceeds 20,000 character limit")
    html_lines = "<br>".join(html.escape(ln) for ln in clean_body.splitlines())
    note_html = f"<h1>{html.escape(clean_title)}</h1><div>{html_lines}</div>"
    target_folder = escape_applescript((folder_name or "Notes").strip())
    script = f"""
tell application "Notes"
    set targetFolder to folder "{target_folder}"
    set newNote to make new note at targetFolder with properties {{body:"{escape_applescript(note_html)}"}}
    return (name of targetFolder) & "{_FIELD_SEP}" & (id of newNote)
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="notes",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    parts = str(res.get("raw_output") or "").split(_FIELD_SEP)
    return {
        "ok": True,
        "folder": parts[0].strip() if parts else folder_name,
        "id": parts[1].strip() if len(parts) > 1 else "",
        "title": clean_title,
        "error": None,
    }


__all__ = [
    "LIST_FOLDERS_SCRIPT",
    "create_note",
    "list_note_folders",
    "read_note",
    "search_notes",
]
