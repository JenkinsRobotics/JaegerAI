"""Calendar — two tools over Calendar.app via AppleScript, same one-
``osascript``-round-trip pattern as ``tools/email.py``'s Mail.app
backend.

  • get_events(day=None, start=None, end=None) — READ_ONLY.
  • create_event(title, start, end, notes=None) — EXTERNAL_EFFECT.

Date/time parsing caveat: AppleScript's ``date "..."`` literal is
locale-dependent — this module formats dates as ``MM/DD/YYYY
HH:MM:SS AM/PM`` (US locale, the default on most Macs). On a Mac set to
a different region format, both tools may misparse; the error from
Calendar.app's own rejection surfaces rather than a silent wrong date.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 15
_FIELD_SEP = "␟"   # unlikely to appear in real event text
_RECORD_SEP = "␞"


def _escape_applescript(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _as_applescript_date(dt: datetime) -> str:
    """Render ``dt`` as a US-locale AppleScript date literal string."""
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


def _parse_day_or_iso(value: str) -> datetime:
    """Resolve a friendly day token ('today'/'tomorrow'/'yesterday') or
    an ISO date/datetime string to a datetime (midnight if date-only)."""
    tag = (value or "").strip().lower()
    now = datetime.now()
    today_midnight = datetime(now.year, now.month, now.day)
    if tag == "today":
        return today_midnight
    if tag == "tomorrow":
        return today_midnight + timedelta(days=1)
    if tag == "yesterday":
        return today_midnight - timedelta(days=1)
    return datetime.fromisoformat(value.strip())


def _not_macos_error() -> dict[str, Any]:
    return {"error": f"Calendar.app is only available on macOS (got {platform.system()})"}


def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script], check=False, capture_output=True,
        text=True, timeout=_TIMEOUT_S,
    )


def get_events(
    day: str | None = None, start: str | None = None, end: str | None = None,
) -> dict[str, Any]:
    """List events across ALL calendars in [start, end).

    Resolution order: explicit `start`/`end` (ISO date or datetime
    strings) win; else `day` ('today'/'tomorrow'/'yesterday'/an ISO
    date) is treated as a single-day range; else defaults to today.
    """
    if platform.system() != "Darwin":
        return {"listed": False, **_not_macos_error()}
    if shutil.which("osascript") is None:
        return {"listed": False, "error": "osascript not on PATH (macOS-only utility)"}

    try:
        if start and end:
            range_start = _parse_day_or_iso(start)
            range_end = _parse_day_or_iso(end)
        else:
            day_dt = _parse_day_or_iso(day) if day else _parse_day_or_iso("today")
            range_start = day_dt
            range_end = day_dt + timedelta(days=1)
    except ValueError as exc:
        return {"listed": False, "error": f"could not parse day/start/end: {exc}"}

    start_lit = _as_applescript_date(range_start)
    end_lit = _as_applescript_date(range_end)
    script = (
        'tell application "Calendar"\n'
        f'set theStart to date "{start_lit}"\n'
        f'set theEnd to date "{end_lit}"\n'
        "set output to \"\"\n"
        "repeat with cal in calendars\n"
        "  set theEvents to (every event of cal whose start date >= theStart "
        "and start date < theEnd)\n"
        "  repeat with e in theEvents\n"
        "    set output to output & (summary of e as string) & "
        f'"{_FIELD_SEP}" & ((start date of e) as string) & "{_FIELD_SEP}" & '
        f'((end date of e) as string) & "{_FIELD_SEP}" & (name of cal as string) & '
        f'"{_RECORD_SEP}"\n'
        "  end repeat\n"
        "end repeat\n"
        "return output\n"
        "end tell"
    )
    try:
        out = _run_osascript(script)
    except subprocess.TimeoutExpired:
        return {"listed": False, "error": f"Calendar query timed out after {_TIMEOUT_S}s"}
    except Exception as exc:  # noqa: BLE001
        return {"listed": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"listed": False,
                 "error": (out.stderr or out.stdout or "osascript failed").strip()}

    events: list[dict[str, str]] = []
    raw = out.stdout.strip()
    if raw:
        for record in raw.split(_RECORD_SEP):
            if not record.strip():
                continue
            fields = record.split(_FIELD_SEP)
            if len(fields) < 4:
                continue
            events.append({
                "title": fields[0], "start": fields[1],
                "end": fields[2], "calendar": fields[3],
            })
    return {"listed": True, "range_start": start_lit, "range_end": end_lit,
             "count": len(events), "events": events}


def create_event(
    title: str, start: str, end: str, notes: str | None = None,
) -> dict[str, Any]:
    """Create an event on the default calendar (first calendar in the
    list). `start`/`end` are ISO date or datetime strings."""
    title_clean = (title or "").strip()
    if not title_clean:
        return {"created": False, "error": "empty title"}
    if platform.system() != "Darwin":
        return {"created": False, **_not_macos_error()}
    if shutil.which("osascript") is None:
        return {"created": False, "error": "osascript not on PATH (macOS-only utility)"}

    try:
        start_dt = _parse_day_or_iso(start)
        end_dt = _parse_day_or_iso(end)
    except ValueError as exc:
        return {"created": False, "error": f"could not parse start/end: {exc}"}

    start_lit = _as_applescript_date(start_dt)
    end_lit = _as_applescript_date(end_dt)
    notes_clean = (notes or "").strip()
    notes_prop = f', description:"{_escape_applescript(notes_clean)}"' if notes_clean else ""
    script = (
        'tell application "Calendar"\n'
        "tell calendar 1\n"
        f'make new event with properties {{summary:"{_escape_applescript(title_clean)}", '
        f'start date:date "{start_lit}", end date:date "{end_lit}"{notes_prop}}}\n'
        "end tell\n"
        "end tell"
    )
    try:
        out = _run_osascript(script)
    except subprocess.TimeoutExpired:
        return {"created": False, "error": f"Calendar create timed out after {_TIMEOUT_S}s"}
    except Exception as exc:  # noqa: BLE001
        return {"created": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"created": False,
                 "error": (out.stderr or out.stdout or "osascript failed").strip()}
    return {"created": True, "title": title_clean, "start": start_lit, "end": end_lit}


# ── Agent-facing tool wrappers ────────────────────────────────────────


@register_tool_from_function(name="get_events", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="calendar", operation="get_events",
               summary="read Calendar.app events")
def _t_get_events(day: str | None = None, start: str | None = None, end: str | None = None) -> dict:
    """List calendar events across all calendars — "what's on my
    calendar today/tomorrow", "do I have anything Thursday". Pass
    `day` ('today'/'tomorrow'/'yesterday' or an ISO date) for a single
    day, or `start`/`end` (ISO date/datetime) for a custom range;
    defaults to today. Returns {events: [{title, start, end,
    calendar}]}."""
    return get_events(day=day, start=start, end=end)


@register_tool_from_function(name="create_event")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="calendar", operation="create_event",
               summary="create a Calendar.app event")
def _t_create_event(title: str, start: str, end: str, notes: str | None = None) -> dict:
    """Create a calendar event — "add a review Thursday at 2pm",
    "schedule X". `start`/`end` are ISO date or datetime strings
    ("2026-07-16T14:00"); `notes` is optional. Lands on the default
    (first) calendar. EXTERNAL EFFECT: goes through the standard
    tier-2 confirmation flow. Resolve WHO to invite via lookup_contact
    first if the ask names a person (Calendar invites aren't wired
    through this tool yet — note that in your reply if asked)."""
    return create_event(title=title, start=start, end=end, notes=notes)


__all__ = ["get_events", "create_event"]
