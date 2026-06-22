"""Tray singleton — refuses to spawn a second menu-bar icon.

The bug we're guarding against: every ``jaeger start`` previously
spawned a fresh tray process without checking. After a few restarts
the menu bar filled with stale icons (the screenshot showed 8). The
singleton gate plus the per-launch pre-check in ``_spawn_tray``
closes that surface.

This file pins:
  * the tray slot writes ``tray.pid`` (distinct from TUI's ``tui.pid``)
  * existing_tray_pid returns the live PID when one is held
  * acquire / cleanup follow the same contract as the generic helper
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_os.interfaces.pyside6.tray.singleton import (
    acquire_tray_slot, existing_tray_pid,
)


def test_tray_slot_writes_tray_pid(tmp_path):
    """The tray's PID file is named ``tray.pid`` — distinct from the
    TUI's ``tui.pid`` — so the two singletons coexist in the same
    instance's run/ directory."""
    cleanup = acquire_tray_slot(tmp_path)
    try:
        assert (tmp_path / "tray.pid").is_file()
        assert not (tmp_path / "tui.pid").is_file()
        assert int((tmp_path / "tray.pid").read_text()) == os.getpid()
    finally:
        cleanup()


def test_existing_tray_pid_none_when_empty(tmp_path):
    assert existing_tray_pid(tmp_path) is None


def test_existing_tray_pid_returns_held_pid(tmp_path):
    """A live PID in the slot file surfaces as the existing owner so
    the launcher can skip spawning a duplicate."""
    # PID 1 (init / launchd) is alive on every Unix.
    (tmp_path / "tray.pid").write_text("1")
    assert existing_tray_pid(tmp_path) == 1


def test_stale_tray_pid_is_cleaned_up(tmp_path):
    """A dead PID in the slot file must not block a fresh tray —
    existing_tray_pid clears it as a side effect."""
    (tmp_path / "tray.pid").write_text("999999")
    assert existing_tray_pid(tmp_path) is None
    assert not (tmp_path / "tray.pid").is_file()
