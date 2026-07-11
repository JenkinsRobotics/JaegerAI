"""InstanceLock — 0.8.1 field bug #3: stale-holder detection.

Field report: a broken-bundle launch left a headless Python agent
holding the instance lock; every subsequent boot refused to start with
"locked by pid X (still running)" even though nothing useful was
actually running. Two things changed in ``instance.py``:

  1. ``_pid_alive`` now checks PROCESS SHAPE, not just liveness — a
     recorded pid that's alive but NOT a jaeger process (a PID-reuse
     race, or an unrelated squatter) is treated as stale.
  2. ``InstanceLock.acquire()`` BREAKS a stale lock automatically
     (with a loud log) instead of raising and telling the operator to
     ``rm`` it by hand.

These tests cover both the pure ``_pid_alive`` decision function and
the end-to-end ``acquire()`` behaviour (including real flock
contention via a subprocess, for the classic dead-pid case).
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jaeger_os.core.instance import instance as instance_mod
from jaeger_os.core.instance.instance import InstanceLayout, InstanceLock


def _layout(tmp_path: Path) -> InstanceLayout:
    root = tmp_path / "inst"
    root.mkdir()
    return InstanceLayout(root=root)


def _hold_flock(path: Path, pid_text: str):
    """Actually hold the OS-level flock on ``path`` from THIS process,
    via a second independent open-file-description — ``flock()`` is
    per-fd, not per-process, so two opens of the same path in the SAME
    process genuinely conflict. This is what makes ``acquire()`` hit
    its EWOULDBLOCK branch in the tests below; just writing pid text
    to the file with no live flock holder (the naive version of these
    tests) lets a fresh ``acquire()`` succeed immediately without ever
    exercising the stale-detection code at all."""
    fh = path.open("a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    fh.seek(0)
    fh.truncate()
    fh.write(pid_text)
    fh.flush()
    return fh


# ── _pid_alive: pure decision function ──────────────────────────────


def test_pid_alive_none_for_garbage_input():
    assert instance_mod._pid_alive("") is None
    assert instance_mod._pid_alive("not-a-pid") is None
    assert instance_mod._pid_alive("-1") is None
    assert instance_mod._pid_alive("0") is None


def test_pid_alive_none_for_dead_pid():
    # A pid this large is essentially guaranteed not to exist.
    assert instance_mod._pid_alive("999999999") is None


def test_pid_alive_true_for_live_jaeger_shaped_process(monkeypatch):
    monkeypatch.setattr(
        instance_mod, "pid_cmdline",
        lambda pid, **kw: "/usr/bin/python3 -m jaeger_os --voice",
    )
    holder = instance_mod._pid_alive(str(os.getpid()))
    assert holder == os.getpid()


def test_pid_alive_none_for_live_but_not_jaeger_shaped(monkeypatch, capsys):
    """The core of field bug #3: alive != jaeger-shaped."""
    monkeypatch.setattr(
        instance_mod, "pid_cmdline",
        lambda pid, **kw: "/usr/bin/some-unrelated-daemon --foo",
    )
    holder = instance_mod._pid_alive(str(os.getpid()))
    assert holder is None
    err = capsys.readouterr().err
    assert "NOT a jaeger process" in err


def test_pid_alive_fails_closed_when_cmdline_unreadable(monkeypatch):
    """ps unavailable/timeout → can't verify → treat as still held.
    A transient ps hiccup must never break a lock that's genuinely in
    use."""
    monkeypatch.setattr(instance_mod, "pid_cmdline", lambda pid, **kw: None)
    holder = instance_mod._pid_alive(str(os.getpid()))
    assert holder == os.getpid()


# ── InstanceLock.acquire(): end-to-end ──────────────────────────────


def test_acquire_release_round_trip(tmp_path):
    layout = _layout(tmp_path)
    lock = InstanceLock(layout)
    lock.acquire()
    try:
        assert layout.lock_path.exists()
        assert layout.lock_path.read_text().strip() == str(os.getpid())
    finally:
        lock.release()
    assert not layout.lock_path.exists()


def test_acquire_breaks_stale_lock_with_dead_pid_text(tmp_path, capsys):
    """The recorded pid is dead AND something (here: our own second fd,
    standing in for the crashed process's now-orphaned flock) is
    holding the OS lock — acquire() must break it and succeed instead
    of raising "remove the file manually"."""
    layout = _layout(tmp_path)
    holder_fh = _hold_flock(layout.lock_path, "999999999\n")
    try:
        lock = InstanceLock(layout)
        lock.acquire()
        try:
            assert layout.lock_path.read_text().strip() == str(os.getpid())
        finally:
            lock.release()
    finally:
        holder_fh.close()
    err = capsys.readouterr().err
    assert "breaking stale instance lock" in err


def test_acquire_breaks_lock_held_by_non_jaeger_pid(tmp_path, monkeypatch, capsys):
    layout = _layout(tmp_path)
    holder_fh = _hold_flock(layout.lock_path, f"{os.getpid()}\n")
    monkeypatch.setattr(
        instance_mod, "pid_cmdline",
        lambda pid, **kw: "/usr/bin/some-unrelated-daemon",
    )
    try:
        lock = InstanceLock(layout)
        lock.acquire()
        try:
            assert layout.lock_path.read_text().strip() == str(os.getpid())
        finally:
            lock.release()
    finally:
        holder_fh.close()
    err = capsys.readouterr().err
    assert "NOT a jaeger process" in err
    assert "breaking stale instance lock" in err


@pytest.mark.slow
def test_acquire_refuses_then_succeeds_after_real_holder_dies(tmp_path):
    """End-to-end with a REAL contested flock (a subprocess actually
    holds it): acquire() must refuse while the holder is alive and
    jaeger-shaped, then succeed — auto-breaking, no manual `rm` — the
    instant that holder is gone. This is the literal field scenario:
    a crashed launch leaves a dead pid behind the lock file."""
    layout = _layout(tmp_path)
    holder_script = (
        "import fcntl, os, sys, time\n"
        f"fh = open({str(layout.lock_path)!r}, 'a+')\n"
        "fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "fh.seek(0); fh.truncate(); fh.write(str(os.getpid()) + '\\n'); fh.flush()\n"
        "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line.strip() == "ready"
        # Give the holder pid a jaeger-shaped cmdline for this check —
        # a bare `python -c ...` isn't jaeger-shaped, and the point of
        # this test is the "genuinely still running" refusal, not the
        # process-shape check (covered separately above).
        import jaeger_os.core.instance.instance as _inst_mod


        orig = _inst_mod.pid_cmdline
        _inst_mod.pid_cmdline = lambda pid, **kw: (
            "/usr/bin/python3 -m jaeger_os" if pid == proc.pid else orig(pid, **kw)
        )
        try:
            lock = InstanceLock(layout)
            with pytest.raises(RuntimeError, match="still running"):
                lock.acquire()
        finally:
            _inst_mod.pid_cmdline = orig

        proc.kill()
        proc.wait(timeout=5)
        # Kernel releases the child's flock the instant it dies — no
        # sleep/poll needed, acquire() can retry immediately.
        deadline = time.monotonic() + 5.0
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                lock = InstanceLock(layout)
                lock.acquire()
                lock.release()
                return
            except RuntimeError as exc:  # noqa: PERF203 — bounded retry loop
                last_exc = exc
                time.sleep(0.1)
        raise AssertionError(f"lock never became acquirable: {last_exc}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
