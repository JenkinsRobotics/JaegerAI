"""Native macOS integration tools via JXA / AppleScript.

Provides safe, audited tools for Calendar, Reminders, Notes, and Shortcuts.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .grants import _audit, _require

MAX_BYTES = 1_000_000

_CALENDAR_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Calendar');
  const start = new Date();
  const end = new Date(start.getTime() + o.days * 86400000);
  const rows = [];
  for (const calendar of app.calendars()) {
    for (const event of calendar.events()) {
      const eventStart = event.startDate();
      if (eventStart >= start && eventStart < end) {
        rows.push({
          id: String(event.uid()),
          calendar: String(calendar.name()),
          summary: String(event.summary()),
          start: eventStart.toISOString(),
          end: event.endDate().toISOString(),
          location: String(event.location() || '')
        });
        if (rows.length >= o.limit) return JSON.stringify(rows);
      }
    }
  }
  rows.sort((a, b) => a.start.localeCompare(b.start));
  return JSON.stringify(rows.slice(0, o.limit));
}
"""

_CALENDAR_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Calendar');
  const calendars = app.calendars();
  const calendar = o.calendar ? calendars.find(c => String(c.name()) === o.calendar) : calendars[0];
  if (!calendar) throw new Error('Calendar not found');
  const event = app.Event({
    summary: o.summary,
    startDate: new Date(o.start),
    endDate: new Date(o.end),
    location: o.location || '',
    description: o.notes || ''
  });
  calendar.events.push(event);
  return JSON.stringify({created: true, id: String(event.uid()), calendar: String(calendar.name())});
}
"""

_NOTES_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  const rows = [];
  for (const account of app.accounts()) {
    for (const folder of account.folders()) {
      for (const note of folder.notes()) {
        rows.push({
          id: String(note.id()),
          title: String(note.name()),
          folder: String(folder.name()),
          modified: String(note.modificationDate())
        });
        if (rows.length >= o.limit) return JSON.stringify(rows);
      }
    }
  }
  return JSON.stringify(rows);
}
"""

_NOTES_READ_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  for (const account of app.accounts()) {
    for (const folder of account.folders()) {
      for (const note of folder.notes()) {
        if (String(note.id()) === o.query || String(note.name()) === o.query) {
          return JSON.stringify({
            id: String(note.id()),
            title: String(note.name()),
            folder: String(folder.name()),
            body: String(note.plaintext())
          });
        }
      }
    }
  }
  throw new Error('Note not found');
}
"""

_NOTES_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Notes');
  let folder = app.defaultAccount.folders()[0];
  if (o.folder) {
    for (const candidate of app.defaultAccount.folders()) {
      if (String(candidate.name()) === o.folder) folder = candidate;
    }
  }
  const note = app.Note({name: o.title, body: o.body || ''});
  folder.notes.push(note);
  return JSON.stringify({created: true, id: String(note.id()), title: String(note.name()), folder: String(folder.name())});
}
"""

_REMINDERS_LIST_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Reminders');
  const rows = [];
  for (const list of app.lists()) {
    if (o.list && String(list.name()) !== o.list) continue;
    for (const reminder of list.reminders()) {
      if (!o.include_completed && Boolean(reminder.completed())) continue;
      rows.push({
        id: String(reminder.id()),
        name: String(reminder.name()),
        list: String(list.name()),
        completed: Boolean(reminder.completed()),
        due: reminder.dueDate() ? reminder.dueDate().toISOString() : ''
      });
      if (rows.length >= o.limit) return JSON.stringify(rows);
    }
  }
  return JSON.stringify(rows);
}
"""

_REMINDERS_CREATE_JXA = r"""
function run(argv) {
  const o = JSON.parse(argv[0]);
  const app = Application('Reminders');
  const lists = app.lists();
  const list = lists.find(candidate => String(candidate.name()) === o.list) || lists[0];
  if (!list) throw new Error('Reminder list not found');
  const properties = {name: o.name, body: o.notes || ''};
  if (o.due) properties.dueDate = new Date(o.due);
  const reminder = app.Reminder(properties);
  list.reminders.push(reminder);
  return JSON.stringify({created: true, id: String(reminder.id()), list: String(list.name())});
}
"""


def _run_jxa(source: str, values: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", source, "--", json.dumps(values)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())},
        check=False,
    )
    stdout = completed.stdout[:MAX_BYTES].strip()
    stderr = completed.stderr[:20_000].strip()
    data: Any = None
    if completed.returncode == 0 and stdout:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = stdout
    return {
        "exit_code": completed.returncode,
        "data": data,
        "error": stderr if completed.returncode else "",
    }


def calendar_list(days: int = 7, limit: int = 100) -> dict[str, Any]:
    """List upcoming Apple Calendar events."""
    capability = "calendar.list"
    _require(capability)
    values = {"days": max(1, min(int(days), 365)), "limit": max(1, min(int(limit), 500))}
    result = _run_jxa(_CALENDAR_LIST_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def calendar_create(
    summary: str,
    start_iso: str,
    end_iso: str,
    calendar: str = "",
    location: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create one Apple Calendar event."""
    capability = "calendar.create"
    _require(capability)
    values = {
        "summary": str(summary or "").strip(),
        "start": str(start_iso or "").strip(),
        "end": str(end_iso or "").strip(),
        "calendar": str(calendar or "").strip(),
        "location": str(location or "").strip(),
        "notes": str(notes or "").strip(),
    }
    result = _run_jxa(_CALENDAR_CREATE_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def notes_list(limit: int = 20) -> dict[str, Any]:
    """List Apple Notes headers."""
    capability = "notes.list"
    _require(capability)
    values = {"limit": max(1, min(int(limit), 200))}
    result = _run_jxa(_NOTES_LIST_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def notes_read(query: str) -> dict[str, Any]:
    """Read plaintext content of an Apple Note by title or ID."""
    capability = "notes.read"
    _require(capability)
    values = {"query": str(query or "").strip()}
    result = _run_jxa(_NOTES_READ_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def notes_create(title: str, body: str = "", folder: str = "") -> dict[str, Any]:
    """Create one Apple Note."""
    capability = "notes.create"
    _require(capability)
    values = {
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
        "folder": str(folder or "").strip(),
    }
    result = _run_jxa(_NOTES_CREATE_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def reminders_list(list_name: str = "", include_completed: bool = False, limit: int = 100) -> dict[str, Any]:
    """List Apple Reminders."""
    capability = "reminders.list"
    _require(capability)
    values = {
        "list": str(list_name or "").strip(),
        "include_completed": bool(include_completed),
        "limit": max(1, min(int(limit), 500)),
    }
    result = _run_jxa(_REMINDERS_LIST_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def reminders_create(name: str, list_name: str = "", due: str = "", notes: str = "") -> dict[str, Any]:
    """Create one Apple Reminder."""
    capability = "reminders.create"
    _require(capability)
    values = {
        "name": str(name or "").strip(),
        "list": str(list_name or "").strip(),
        "due": str(due or "").strip(),
        "notes": str(notes or "").strip(),
    }
    result = _run_jxa(_REMINDERS_CREATE_JXA, values)
    _audit(capability, outcome="allowed" if result["exit_code"] == 0 else "failed")
    return result


def shortcuts_list() -> dict[str, Any]:
    """List installed Apple Shortcuts."""
    capability = "shortcuts.list"
    _require(capability)
    completed = subprocess.run(
        ["/usr/bin/shortcuts", "list"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    shortcuts = [line.strip() for line in completed.stdout.splitlines() if line.strip()][:1000]
    _audit(capability, outcome="allowed" if completed.returncode == 0 else "failed")
    return {"exit_code": completed.returncode, "shortcuts": shortcuts, "error": completed.stderr[:2000]}


def shortcuts_run(name: str, input_text: str = "") -> dict[str, Any]:
    """Run one named Apple Shortcut."""
    capability = "shortcuts.run"
    _require(capability)
    completed = subprocess.run(
        ["/usr/bin/shortcuts", "run", name],
        input=input_text or None,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        check=False,
    )
    _audit(capability, outcome="allowed" if completed.returncode == 0 else "failed")
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[:MAX_BYTES],
        "stderr": completed.stderr[:20_000],
    }
