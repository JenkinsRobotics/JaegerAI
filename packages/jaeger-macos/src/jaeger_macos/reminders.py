"""Native macOS Reminders.app adapter using serialized, bounded AppleScript."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from .appleevents import escape_applescript, run_applescript

_FIELD_SEP = "\x1f"
_ROW_SEP = "\x1e"

LIST_REMINDER_LISTS_SCRIPT = """
tell application "Reminders"
    set outList to {}
    repeat with l in lists
        set end of outList to (name of l)
    end repeat
    set AppleScript's text item delimiters to linefeed
    return outList as text
end tell
""".strip()


def _parse_optional_due(value: str | None) -> _dt.datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    cleaned = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = _dt.datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 due_iso: {value!r}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def list_reminder_lists(
    *,
    timeout_seconds: float = 15.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return all reminder list names from macOS Reminders.app."""
    res = run_applescript(
        LIST_REMINDER_LISTS_SCRIPT,
        timeout_seconds=timeout_seconds,
        target="reminders",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "lists": [], "error": res.get("error")}
    names = [line.strip() for line in str(res.get("raw_output") or "").splitlines() if line.strip()]
    return {"ok": True, "lists": names, "count": len(names), "error": None}


def list_reminders(
    *,
    list_name: str | None = None,
    include_completed: bool = False,
    limit: int = 40,
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """List reminders from macOS Reminders.app (bounded by ``limit``)."""
    clamped_limit = max(1, min(int(limit or 40), 100))
    list_filter = (
        f'set targetLists to {{list "{escape_applescript(list_name.strip())}"}}'
        if list_name and list_name.strip()
        else "set targetLists to lists"
    )
    completed_clause = "" if include_completed else " whose completed is false"
    script = f"""
tell application "Reminders"
    {list_filter}
    set rows to {{}}
    set maxRows to {clamped_limit}
    repeat with l in targetLists
        set lName to name of l
        set rems to (every reminder of l{completed_clause})
        repeat with r in rems
            if (count of rows) >= maxRows then exit repeat
            set rId to ""
            try
                set rId to id of r
            end try
            set rName to ""
            try
                set rName to name of r
            end try
            set rDone to "false"
            try
                if completed of r then set rDone to "true"
            end try
            set rDue to ""
            try
                if due date of r is not missing value then set rDue to ((due date of r) as «class isot» as string)
            end try
            set end of rows to (lName & "{_FIELD_SEP}" & rId & "{_FIELD_SEP}" & rName & "{_FIELD_SEP}" & rDone & "{_FIELD_SEP}" & rDue)
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
        target="reminders",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "reminders": [], "error": res.get("error")}
    raw = str(res.get("raw_output") or "")
    items: list[dict[str, Any]] = []
    for row in raw.split(_ROW_SEP):
        if not row.strip():
            continue
        parts = row.split(_FIELD_SEP)
        while len(parts) < 5:
            parts.append("")
        items.append({
            "list": parts[0].strip(),
            "id": parts[1].strip(),
            "title": parts[2].strip(),
            "completed": parts[3].strip().lower() == "true",
            "due": parts[4].strip(),
        })
    return {"ok": True, "reminders": items, "count": len(items), "error": None}


def create_reminder(
    *,
    title: str,
    list_name: str | None = None,
    due_iso: str | None = None,
    notes: str = "",
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Create a reminder in macOS Reminders.app."""
    clean_title = (title or "").strip()
    if not clean_title or len(clean_title) > 200:
        raise ValueError("title must be 1-200 characters")
    due_dt = _parse_optional_due(due_iso)

    list_expr = (
        f'list "{escape_applescript(list_name.strip())}"'
        if list_name and list_name.strip()
        else "default list"
    )
    due_block = ""
    props = [f'name:"{escape_applescript(clean_title)}"']
    if notes and notes.strip():
        props.append(f'body:"{escape_applescript(notes.strip()[:1000])}"')
    if due_dt is not None:
        due_block = (
            "set dueDate to current date\n"
            f"set year of dueDate to {due_dt.year}\n"
            f"set month of dueDate to {due_dt.month}\n"
            f"set day of dueDate to {due_dt.day}\n"
            f"set time of dueDate to {due_dt.hour * 3600 + due_dt.minute * 60 + due_dt.second}\n"
        )
        props.append("due date:dueDate")

    script = f"""
{due_block}tell application "Reminders"
    set targetList to {list_expr}
    set newRem to make new reminder at end of reminders of targetList with properties {{{", ".join(props)}}}
    return (name of targetList) & "{_FIELD_SEP}" & (id of newRem)
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="reminders",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    parts = str(res.get("raw_output") or "").split(_FIELD_SEP)
    return {
        "ok": True,
        "list": parts[0].strip() if parts else (list_name or ""),
        "id": parts[1].strip() if len(parts) > 1 else "",
        "title": clean_title,
        "due": due_dt.isoformat() if due_dt else "",
        "error": None,
    }


def complete_reminder(
    *,
    title: str,
    list_name: str | None = None,
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Mark the first matching incomplete reminder complete in macOS Reminders.app."""
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("title is required")
    list_filter = (
        f'set targetLists to {{list "{escape_applescript(list_name.strip())}"}}'
        if list_name and list_name.strip()
        else "set targetLists to lists"
    )
    escaped = escape_applescript(clean_title)
    script = f"""
tell application "Reminders"
    {list_filter}
    repeat with l in targetLists
        set matches to (every reminder of l whose completed is false and name is "{escaped}")
        if (count of matches) > 0 then
            set completed of (item 1 of matches) to true
            return "completed" & "{_FIELD_SEP}" & (name of l)
        end if
    end repeat
    return "not_found"
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="reminders",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "completed": False, "error": res.get("error")}
    raw = str(res.get("raw_output") or "")
    if raw.startswith("completed"):
        parts = raw.split(_FIELD_SEP)
        return {
            "ok": True,
            "completed": True,
            "list": parts[1].strip() if len(parts) > 1 else "",
            "title": clean_title,
            "error": None,
        }
    return {"ok": False, "completed": False, "error": f"incomplete reminder not found: {clean_title}"}


__all__ = [
    "LIST_REMINDER_LISTS_SCRIPT",
    "complete_reminder",
    "create_reminder",
    "list_reminder_lists",
    "list_reminders",
]
