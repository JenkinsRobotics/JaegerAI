"""Tray singleton — one menu-bar icon per host at a time.

The bug we're guarding against: every ``jaeger start`` /
``jaeger restart`` previously fire-and-forgot a new tray process,
adding a fresh ○ icon to the menu bar without checking whether one
was already up. After a few restarts the menu bar fills with stale,
unresponsive icons (the user's screenshot showed eight of them).

Thin wrapper over :mod:`jaeger_os.core.runtime.process_slot` with
the slot name fixed at ``"tray"`` so the tray and the TUI don't
clobber each other's PID files in the same ``run/`` directory.

  * :func:`acquire_tray_slot` — called at rumps startup. Records
    this process's PID at ``<instance>/run/tray.pid``.
  * :func:`existing_tray_pid` — read by ``_spawn_tray`` before
    launching a new tray. Returns the live PID if a tray is already
    in the menu bar, or ``None`` if the slot is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from jaeger_os.core.runtime.process_slot import (
    acquire_slot,
    acquire_slot_exclusive,
    existing_slot_pid,
)


_SLOT = "tray"


def existing_tray_pid(run_dir: Path) -> int | None:
    """Return the live PID of an existing tray for this instance, or
    ``None`` when the slot is free."""
    return existing_slot_pid(run_dir, _SLOT)


def acquire_tray_slot(run_dir: Path) -> Callable[[], None]:
    """Claim the tray slot for this process (non-atomic). See
    :func:`jaeger_os.core.runtime.process_slot.acquire_slot`."""
    return acquire_slot(run_dir, _SLOT)


def claim_tray_slot(run_dir: Path) -> tuple[bool, int | None, Callable[[], None]]:
    """Atomically claim the single tray slot. Returns
    ``(acquired, owner_pid, cleanup)``. The ONLY race-free gate under
    concurrent launches — exactly one process wins; the rest must exit
    without drawing an icon. See :func:`acquire_slot_exclusive`."""
    return acquire_slot_exclusive(run_dir, _SLOT)


__all__ = ["acquire_tray_slot", "claim_tray_slot", "existing_tray_pid"]
