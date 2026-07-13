"""calendar.py (agent/tools/calendar.py) — 0.9.3 mac-native suite.

All ``osascript`` invocations are mocked — no real Calendar.app call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import calendar
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


# ── get_events ────────────────────────────────────────────────────


def test_get_events_parses_records(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")

    sep_f, sep_r = calendar._FIELD_SEP, calendar._RECORD_SEP
    raw = f"Standup{sep_f}date1{sep_f}date2{sep_f}Work{sep_r}"

    def fake_run(args, **kwargs):
        return _proc(0, stdout=raw)

    monkeypatch.setattr(calendar.subprocess, "run", fake_run)
    result = calendar.get_events(day="today")
    assert result["listed"] is True
    assert result["count"] == 1
    assert result["events"][0]["title"] == "Standup"
    assert result["events"][0]["calendar"] == "Work"


def test_get_events_defaults_to_today(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")
    seen_scripts = []

    def fake_run(args, **kwargs):
        seen_scripts.append(args[-1])
        return _proc(0, stdout="")

    monkeypatch.setattr(calendar.subprocess, "run", fake_run)
    result = calendar.get_events()
    assert result["listed"] is True
    assert result["count"] == 0
    assert "tell application \"Calendar\"" in seen_scripts[-1]


def test_get_events_explicit_start_end(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")
    seen_scripts = []

    def fake_run(args, **kwargs):
        seen_scripts.append(args[-1])
        return _proc(0, stdout="")

    monkeypatch.setattr(calendar.subprocess, "run", fake_run)
    calendar.get_events(start="2026-07-14", end="2026-07-16")
    assert "07/14/2026" in seen_scripts[-1]
    assert "07/16/2026" in seen_scripts[-1]


def test_get_events_bad_date_is_actionable():
    result = calendar.get_events(day="not-a-date")
    assert result["listed"] is False
    assert "could not parse" in result["error"]


def test_get_events_osascript_failure_reported(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(calendar.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="Calendar got an error"))
    result = calendar.get_events()
    assert result["listed"] is False
    assert "Calendar got an error" in result["error"]


def test_get_events_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Linux")
    result = calendar.get_events()
    assert result["listed"] is False
    assert "macOS" in result["error"]


# ── create_event ──────────────────────────────────────────────────


def test_create_event_success(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")
    seen_scripts = []

    def fake_run(args, **kwargs):
        seen_scripts.append(args[-1])
        return _proc(0)

    monkeypatch.setattr(calendar.subprocess, "run", fake_run)
    result = calendar.create_event("Review", "2026-07-16T14:00", "2026-07-16T15:00",
                                    notes="prep the deck")
    assert result["created"] is True
    assert result["title"] == "Review"
    assert "Review" in seen_scripts[-1]
    assert "prep the deck" in seen_scripts[-1]


def test_create_event_requires_title():
    result = calendar.create_event("", "2026-07-16", "2026-07-16")
    assert result["created"] is False
    assert "empty title" in result["error"]


def test_create_event_bad_dates_actionable():
    result = calendar.create_event("Review", "nonsense", "also-nonsense")
    assert result["created"] is False
    assert "could not parse" in result["error"]


def test_create_event_osascript_failure_reported(monkeypatch):
    monkeypatch.setattr(calendar.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calendar.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(calendar.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="no calendar"))
    result = calendar.create_event("Review", "2026-07-16", "2026-07-16")
    assert result["created"] is False
    assert "no calendar" in result["error"]


# ── tier + registration ───────────────────────────────────────────


def test_get_events_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "get_events" in tools
    assert get_tier(tools["get_events"]) == PermissionTier.READ_ONLY


def test_create_event_is_registered_external_effect():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "create_event" in tools
    assert get_tier(tools["create_event"]) == PermissionTier.EXTERNAL_EFFECT
