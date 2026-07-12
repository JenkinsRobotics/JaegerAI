"""TUI singleton — one Jaeger TUI per host at a time.

The bug we're guarding against: clicking the tray's Open TUI twice
spawns two Terminal.app windows, each loading the model into the
same llama-cpp lock → wedge. Lilith solved this with a per-host
PID file; we mirror the pattern, scoped per-instance so two
DIFFERENT instances can still run concurrent TUIs.

This file pins:
  * acquiring the slot writes a PID file
  * existing_tui_pid returns the live PID when one is held
  * a stale PID file (process gone) is cleaned up and treated as free
  * acquiring the same slot from the same process is idempotent
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_ai.interfaces.tui.singleton import (
    acquire_tui_slot,
    existing_tui_pid,
)


def _pid_file(run_dir: Path) -> Path:
    return run_dir / "tui.pid"


# ── slot acquisition ──────────────────────────────────────────────


def test_acquire_writes_the_current_pid(tmp_path):
    """Claiming the slot must persist this process's PID so the next
    spawn can see it. Without the write, two TUIs would race."""
    cleanup = acquire_tui_slot(tmp_path)
    assert _pid_file(tmp_path).is_file()
    assert int(_pid_file(tmp_path).read_text()) == os.getpid()
    cleanup()  # restore state


def test_existing_tui_pid_returns_none_when_no_file(tmp_path):
    """Fresh instance with no prior TUI — slot is free."""
    assert existing_tui_pid(tmp_path) is None


def test_existing_tui_pid_returns_held_pid_when_slot_owned(tmp_path):
    """When another process holds the slot, existing_tui_pid surfaces
    its PID so the tray knows to activate the window instead of
    spawning a duplicate."""
    # Simulate a held slot: write a known-live PID (our own works
    # because is_pid_alive(getpid()) is True) but pretend it's
    # different by reading what existing_tui_pid sees vs. our own pid.
    # The function specifically excludes os.getpid() from "existing"
    # so we have to spoof. Use PID 1 (init / launchd) which is always
    # alive on every Unix host.
    (_pid_file(tmp_path)).write_text("1")
    assert existing_tui_pid(tmp_path) == 1


def test_existing_tui_pid_excludes_own_process(tmp_path):
    """A process that wrote its own PID asking 'is anyone here?'
    should see the slot as free — otherwise re-entering the same
    process couldn't re-acquire."""
    cleanup = acquire_tui_slot(tmp_path)
    try:
        assert existing_tui_pid(tmp_path) is None
    finally:
        cleanup()


def test_stale_pid_file_is_cleaned_up_and_reported_free(tmp_path):
    """A PID file pointing at a dead process must not block a new
    TUI. existing_tui_pid removes the stale file as a side effect so
    the next caller can claim the slot."""
    # PID 999999 is essentially guaranteed to be dead on a fresh test.
    (_pid_file(tmp_path)).write_text("999999")
    assert existing_tui_pid(tmp_path) is None
    assert not _pid_file(tmp_path).exists()


def test_corrupted_pid_file_is_treated_as_free(tmp_path):
    """A PID file with garbage in it (write crashed mid-update, disk
    corruption) must not crash the lookup. We treat unparseable
    contents as a stale file and clean up."""
    (_pid_file(tmp_path)).write_text("not a pid")
    assert existing_tui_pid(tmp_path) is None
    assert not _pid_file(tmp_path).exists()


def test_acquire_is_idempotent_within_same_process(tmp_path):
    """Re-acquiring from the same process overwrites with our own
    PID — useful when a future restart-in-place path re-arms the
    slot without exiting."""
    c1 = acquire_tui_slot(tmp_path)
    c2 = acquire_tui_slot(tmp_path)
    try:
        assert int(_pid_file(tmp_path).read_text()) == os.getpid()
    finally:
        c2()
        c1()


def test_cleanup_only_removes_file_we_own(tmp_path):
    """If another TUI reclaimed the slot before we exited (rare race),
    our cleanup must NOT clobber their PID file — only remove it when
    the recorded PID is ours."""
    cleanup = acquire_tui_slot(tmp_path)
    # Simulate someone else taking over: overwrite with a different PID.
    (_pid_file(tmp_path)).write_text("12345")
    cleanup()
    # File is preserved — we don't own it anymore.
    assert _pid_file(tmp_path).is_file()
    assert _pid_file(tmp_path).read_text() == "12345"
    # Clean up so other tests don't see this file.
    _pid_file(tmp_path).unlink()
