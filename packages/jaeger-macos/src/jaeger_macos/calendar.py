"""Native macOS Calendar.app adapter using serialized, bounded AppleScript.

All AppleScript calls serialize through ``appleevents_lock("calendar")`` so
parallel threads or Gateway processes never contend on Calendar.app's main
queue. Every query is strictly bounded by date window and result limit.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from .appleevents import escape_applescript, run_applescript

_FIELD_SEP = "\x1f"
_ROW_SEP = "\x1e"

LIST_CALENDARS_SCRIPT = """
tell application "Calendar"
    set outList to {}
    repeat with c in calendars
        set end of outList to (name of c)
    end repeat
    set AppleScript's text item delimiters to linefeed
    return outList as text
end tell
""".strip()


def _parse_iso_datetime(value: str) -> _dt.datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("datetime value is required (ISO-8601, e.g. 2026-11-28T14:00:00)")
    cleaned = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = _dt.datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 datetime: {value!r}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _as_date_block(var_name: str, dt: _dt.datetime) -> str:
    """Build locale-independent AppleScript date construction statements."""
    return (
        f"set {var_name} to current date\n"
        f"set year of {var_name} to {dt.year}\n"
        f"set month of {var_name} to {dt.month}\n"
        f"set day of {var_name} to {dt.day}\n"
        f"set time of {var_name} to {dt.hour * 3600 + dt.minute * 60 + dt.second}"
    )


def list_calendars(
    *,
    timeout_seconds: float = 15.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return all calendar names from macOS Calendar.app."""
    res = run_applescript(
        LIST_CALENDARS_SCRIPT,
        timeout_seconds=timeout_seconds,
        target="calendar",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "calendars": [], "error": res.get("error")}
    names = [line.strip() for line in str(res.get("raw_output") or "").splitlines() if line.strip()]
    return {"ok": True, "calendars": names, "count": len(names), "error": None}


def list_upcoming_events(
    *,
    days: int = 7,
    calendar_name: str | None = None,
    limit: int = 30,
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """List upcoming events within ``days`` (1..90) from Calendar.app."""
    clamped_days = max(1, min(int(days or 7), 90))
    clamped_limit = max(1, min(int(limit or 30), 100))
    now = _dt.datetime.now().replace(microsecond=0)
    end = now + _dt.timedelta(days=clamped_days)

    cal_filter = (
        f'set targetCals to {{calendar "{escape_applescript(calendar_name.strip())}"}}'
        if calendar_name and calendar_name.strip()
        else "set targetCals to calendars"
    )
    script = f"""
{_as_date_block("startDate", now)}
{_as_date_block("endDate", end)}
tell application "Calendar"
    {cal_filter}
    set rows to {{}}
    set maxRows to {clamped_limit}
    repeat with c in targetCals
        set calName to name of c
        set evs to (every event of c whose start date >= startDate and start date <= endDate)
        repeat with e in evs
            if (count of rows) >= maxRows then exit repeat
            set evSummary to ""
            try
                set evSummary to summary of e
            end try
            set evStart to ""
            try
                set evStart to ((start date of e) as «class isot» as string)
            end try
            set evEnd to ""
            try
                set evEnd to ((end date of e) as «class isot» as string)
            end try
            set evLoc to ""
            try
                if location of e is not missing value then set evLoc to location of e
            end try
            set end of rows to (calName & "{_FIELD_SEP}" & evSummary & "{_FIELD_SEP}" & evStart & "{_FIELD_SEP}" & evEnd & "{_FIELD_SEP}" & evLoc)
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
        target="calendar",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "events": [], "error": res.get("error")}

    raw = str(res.get("raw_output") or "")
    events: list[dict[str, str]] = []
    for row in raw.split(_ROW_SEP):
        if not row.strip():
            continue
        parts = row.split(_FIELD_SEP)
        while len(parts) < 5:
            parts.append("")
        events.append({
            "calendar": parts[0].strip(),
            "summary": parts[1].strip(),
            "start": parts[2].strip(),
            "end": parts[3].strip(),
            "location": parts[4].strip(),
        })
    events.sort(key=lambda item: item.get("start") or "")
    return {"ok": True, "days": clamped_days, "events": events, "count": len(events), "error": None}


def create_calendar_event(
    *,
    summary: str,
    start_iso: str,
    end_iso: str | None = None,
    duration_minutes: int = 60,
    calendar_name: str | None = None,
    location: str = "",
    notes: str = "",
    timeout_seconds: float = 20.0,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Create a calendar event in macOS Calendar.app."""
    clean_summary = (summary or "").strip()
    if not clean_summary or len(clean_summary) > 200:
        raise ValueError("summary must be 1-200 characters")
    start_dt = _parse_iso_datetime(start_iso)
    if end_iso and end_iso.strip():
        end_dt = _parse_iso_datetime(end_iso)
    else:
        mins = max(5, min(int(duration_minutes or 60), 24 * 60))
        end_dt = start_dt + _dt.timedelta(minutes=mins)
    if end_dt <= start_dt:
        raise ValueError("end time must be strictly after start time")

    cal_expr = (
        f'calendar "{escape_applescript(calendar_name.strip())}"'
        if calendar_name and calendar_name.strip()
        else "first calendar"
    )
    props = [
        f'summary:"{escape_applescript(clean_summary)}"',
        "start date:startDate",
        "end date:endDate",
    ]
    if location and location.strip():
        props.append(f'location:"{escape_applescript(location.strip()[:200])}"')
    if notes and notes.strip():
        props.append(f'description:"{escape_applescript(notes.strip()[:1000])}"')

    script = f"""
{_as_date_block("startDate", start_dt)}
{_as_date_block("endDate", end_dt)}
tell application "Calendar"
    set targetCal to {cal_expr}
    set newEv to make new event at end of events of targetCal with properties {{{", ".join(props)}}}
    return (name of targetCal) & "{_FIELD_SEP}" & (uid of newEv)
end tell
""".strip()

    res = run_applescript(
        script,
        timeout_seconds=timeout_seconds,
        target="calendar",
        runner=runner,
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    parts = str(res.get("raw_output") or "").split(_FIELD_SEP)
    return {
        "ok": True,
        "calendar": parts[0].strip() if parts else (calendar_name or ""),
        "uid": parts[1].strip() if len(parts) > 1 else "",
        "summary": clean_summary,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "error": None,
    }


__all__ = [
    "LIST_CALENDARS_SCRIPT",
    "create_calendar_event",
    "list_calendars",
    "list_upcoming_events",
]
