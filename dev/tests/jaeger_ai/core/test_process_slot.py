"""Generic per-process singleton slot.

The TUI and the tray both need "is one already running?" gates and
the pattern is small enough to share. This file pins:

  * the helper is reusable with different slot names in the same
    run/ directory (TUI and tray don't clobber each other)
  * stale PID files are auto-cleaned
  * cleanup respects ownership (a reclaimed slot isn't clobbered
    by the old owner's atexit)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_ai.core.runtime.process_slot import (
    acquire_slot, acquire_slot_exclusive, existing_slot_pid,
)


def _slot_file(run_dir: Path, name: str) -> Path:
    return run_dir / f"{name}.pid"


def _race_claim_worker(run_dir_str, slot, markers_str, barrier):
    """Child-process body for the concurrency test. Must be module-level
    so ``spawn`` can pickle it. All children rendezvous at the barrier
    to maximise simultaneity, then race to claim the slot. A winner
    drops a marker file and HOLDS the slot briefly so losers resolve
    against a live owner (not a slot freed by an early exit)."""
    import os as _os
    import time as _time
    from pathlib import Path as _Path
    from jaeger_ai.core.runtime.process_slot import acquire_slot_exclusive

    try:
        barrier.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass
    acquired, _owner, _cleanup = acquire_slot_exclusive(_Path(run_dir_str), slot)
    if acquired:
        (_Path(markers_str) / f"won_{_os.getpid()}").write_text("1")
        _time.sleep(1.0)  # hold the slot while the other racers resolve


def test_exclusive_claim_succeeds_when_free(tmp_path):
    acquired, owner, cleanup = acquire_slot_exclusive(tmp_path, "tray")
    assert acquired is True
    assert owner == os.getpid()
    assert _slot_file(tmp_path, "tray").read_text().strip() == str(os.getpid())
    cleanup()


def test_exclusive_claim_refused_when_live_owner_present(tmp_path):
    """A live owner (PID file with this very process's PID, which IS
    alive) must make a second claim fail — no duplicate."""
    _slot_file(tmp_path, "tray").write_text(str(os.getpid()))
    # A *different* notion of owner: simulate another live process by
    # writing our own (alive) pid, then claiming as if we were a new
    # launcher. Since the recorded pid == us, the exclusive path treats
    # it as already-ours and returns acquired (idempotent). To test the
    # refusal path we need a live pid that ISN'T us — use the parent.
    ppid = os.getppid()
    _slot_file(tmp_path, "tray").write_text(str(ppid))
    acquired, owner, _ = acquire_slot_exclusive(tmp_path, "tray")
    assert acquired is False
    assert owner == ppid


def test_exclusive_claim_reclaims_stale(tmp_path):
    """A PID file naming a DEAD process is reclaimed atomically."""
    dead = 2_000_000_000  # almost certainly not a live PID
    _slot_file(tmp_path, "tray").write_text(str(dead))
    acquired, owner, cleanup = acquire_slot_exclusive(tmp_path, "tray")
    assert acquired is True
    assert owner == os.getpid()
    cleanup()


def test_exclusive_claim_exactly_one_winner_under_concurrency(tmp_path):
    """The whole point: N separate PROCESSES racing to claim the SAME
    free slot — exactly one acquires it, the rest are refused. This is
    what the non-atomic acquire_slot could not guarantee (the tray
    pile-up: 8 launches each drew an icon). Uses real processes (not
    threads) because the guarantee is cross-process and racers have
    distinct PIDs."""
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(8)
    markers = tmp_path / "markers"
    markers.mkdir()

    procs = [
        ctx.Process(target=_race_claim_worker,
                    args=(str(tmp_path), "race", str(markers), barrier))
        for _ in range(8)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)

    winners = list(markers.glob("won_*"))
    assert len(winners) == 1, (
        f"expected exactly 1 winner, got {len(winners)}: "
        f"{[w.name for w in winners]}"
    )


def test_acquire_writes_named_pid_file(tmp_path):
    """The slot name controls the filename so multiple kinds of
    singletons can share the same run_dir without colliding."""
    cleanup = acquire_slot(tmp_path, "myslot")
    try:
        assert _slot_file(tmp_path, "myslot").is_file()
        assert int(_slot_file(tmp_path, "myslot").read_text()) == os.getpid()
    finally:
        cleanup()


def test_two_slots_in_same_run_dir_dont_collide(tmp_path):
    """The TUI and tray both live under ``<instance>/run/`` —
    different slot names must produce different files."""
    c1 = acquire_slot(tmp_path, "tui")
    c2 = acquire_slot(tmp_path, "tray")
    try:
        assert _slot_file(tmp_path, "tui").is_file()
        assert _slot_file(tmp_path, "tray").is_file()
        # Independent removal — one cleanup must not touch the other.
        c1()
        assert not _slot_file(tmp_path, "tui").is_file()
        assert _slot_file(tmp_path, "tray").is_file()
    finally:
        c2()


def test_existing_slot_pid_finds_live_holder(tmp_path):
    """Init/launchd (PID 1) is always alive on every Unix host —
    use it as a stand-in for 'some other live process holds the
    slot'."""
    _slot_file(tmp_path, "tray").write_text("1")
    assert existing_slot_pid(tmp_path, "tray") == 1


def test_existing_slot_pid_cleans_up_stale_file(tmp_path):
    """A PID file pointing at a dead process must not block a new
    owner — the lookup deletes the stale file as a side effect."""
    _slot_file(tmp_path, "tray").write_text("999999")
    assert existing_slot_pid(tmp_path, "tray") is None
    assert not _slot_file(tmp_path, "tray").is_file()


def test_existing_slot_pid_returns_none_for_empty_slot(tmp_path):
    assert existing_slot_pid(tmp_path, "anything") is None


def test_cleanup_does_not_clobber_a_reclaimed_slot(tmp_path):
    """If another process reclaimed the slot before we exited, our
    atexit must NOT remove their PID file — only delete it when the
    recorded PID is still ours."""
    cleanup = acquire_slot(tmp_path, "tray")
    # Simulate a takeover.
    _slot_file(tmp_path, "tray").write_text("12345")
    cleanup()
    assert _slot_file(tmp_path, "tray").is_file()
    # Clean up so other tests don't see this file.
    _slot_file(tmp_path, "tray").unlink()
