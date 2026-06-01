"""TUI singleton — one Jaeger TUI per host at a time.

Thin wrapper over :mod:`jaeger_os.core.runtime.process_slot` with the
slot name fixed at ``"tui"``. Same pattern used for the tray slot —
both gates share the underlying read/write/atexit logic so a bug fix
to one improves the other.

  * :func:`acquire_tui_slot` — written at TUI startup. Records this
    process's PID at ``<instance>/run/tui.pid``. Returns a teardown
    callable the caller registers via ``atexit`` (already done by
    the helper).
  * :func:`existing_tui_pid` — read by the tray before spawning a
    new window. Returns the live PID if an existing TUI is running,
    or ``None`` if the slot is free. Stale PID files (process gone)
    are cleaned up so the next spawn can take the slot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from jaeger_os.core.runtime.process_slot import acquire_slot, existing_slot_pid


_SLOT = "tui"


def existing_tui_pid(run_dir: Path) -> int | None:
    """Return the live PID of an existing TUI for this instance, or
    ``None`` when the slot is free."""
    return existing_slot_pid(run_dir, _SLOT)


def acquire_tui_slot(run_dir: Path) -> Callable[[], None]:
    """Claim the TUI slot for this process. See
    :func:`jaeger_os.core.runtime.process_slot.acquire_slot` for the
    full contract."""
    return acquire_slot(run_dir, _SLOT)


__all__ = ["acquire_tui_slot", "existing_tui_pid"]
