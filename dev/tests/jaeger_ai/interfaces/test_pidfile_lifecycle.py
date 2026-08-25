"""PID-file lifecycle — the signal ``jaeger status`` reads to see a live bridge.

Field blocker #1: a bridge was running (``python -m
jaeger_ai.interfaces.bridge``) while ``jaeger status`` printed "no process
detected". Root cause: ``status_cmd._find_pid_file`` looks for
``jaeger.pid`` under the instance root, but the bridge never wrote one, so
status was structurally blind and its "stale pid file" branch was dead code.

Blocker #4 rides along: reclaiming a PID file must be DETERMINISTIC — a
stale file is taken over, a file owned by a live bridge is never stolen
(PID numbers are recycled, so liveness alone is not ownership).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_ai.interfaces import pidfile


def _layout(tmp_path: Path):
    class _L:
        root = tmp_path
    return _L()


def test_acquire_writes_pid_status_can_read(tmp_path):
    """The file status reads must exist, and parse as a bare int."""
    with pidfile.acquire(_layout(tmp_path)) as path:
        assert path.exists()
        assert int(path.read_text().strip()) == os.getpid()


def test_status_detects_live_bridge(tmp_path):
    """End-to-end with the real status helpers — the blocker #1 regression."""
    from jaeger_ai.cli import status_cmd

    layout = _layout(tmp_path)
    assert status_cmd._find_pid_file(layout) is None

    with pidfile.acquire(layout):
        found = status_cmd._find_pid_file(layout)
        assert found is not None, "status still cannot see a live bridge"
        assert status_cmd._pid_alive(int(found.read_text().strip()))


def test_release_removes_file(tmp_path):
    layout = _layout(tmp_path)
    with pidfile.acquire(layout) as path:
        pass
    assert not path.exists(), "clean shutdown must not leave a stale pid file"


def test_stale_pid_is_reclaimed(tmp_path):
    """A dead PID is not an owner — startup takes the file over."""
    layout = _layout(tmp_path)
    target = pidfile.pid_path(layout)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("999999\n")          # never alive on macOS/Linux

    with pidfile.acquire(layout) as path:
        assert int(path.read_text().strip()) == os.getpid()


def test_live_foreign_owner_is_not_stolen(tmp_path):
    """A file owned by a live bridge must make startup refuse, not clobber."""
    layout = _layout(tmp_path)
    target = pidfile.pid_path(layout)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("4321\n")

    # 4321 is alive AND looks like a bridge => a real owner.
    pidfile._is_live_bridge = lambda pid: pid == 4321   # type: ignore[assignment]
    try:
        with pytest.raises(pidfile.AlreadyRunning) as err:
            with pidfile.acquire(layout):
                pass
        assert err.value.pid == 4321
        assert target.read_text().strip() == "4321", "owner's file was clobbered"
    finally:
        importlib_reload()


def test_release_does_not_delete_successor_file(tmp_path):
    """If someone else has since claimed the path, we must not delete it."""
    layout = _layout(tmp_path)
    with pidfile.acquire(layout) as path:
        path.write_text("777777\n")        # a successor claimed it
    assert path.exists(), "release deleted a file we no longer owned"


def importlib_reload():
    import importlib
    importlib.reload(pidfile)


# --- end-to-end: the real bridge.main must register itself -----------------

def _drive_main(monkeypatch, root, observer):
    """Run ``bridge.main`` with a faked boot that reports pid-file state.

    Empty stdin means main falls straight through to teardown, and teardown
    waits on ``ctx.booted`` — so the observer always runs first.
    """
    import io
    import types

    from jaeger_ai.interfaces import bridge

    def fake_boot(*, instance_name, **kwargs):
        observer()
        from jaeger_ai.core.instance.instance import (
            InstanceLayout, resolve_instance_dir)
        return types.SimpleNamespace(
            client=object(), layout=InstanceLayout(resolve_instance_dir(instance_name)),
            cleanup=lambda: None)

    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(root))
    monkeypatch.setattr("jaeger_ai.main.boot_for_tui", fake_boot, raising=False)
    monkeypatch.setattr("jaeger_ai.main.run_for_voice",
                        lambda *a, **k: {"text": "", "error": None}, raising=False)
    monkeypatch.setattr("sys.stdout", io.StringIO())
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    return bridge.main(argv=[])


def _minimal_instance(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    for f in ("identity.yaml", "config.yaml", "manifest.json"):
        (root / f).write_text("{}", encoding="utf-8")
    return root


def test_bridge_main_registers_while_running(tmp_path, monkeypatch):
    """Blocker #1 end-to-end: a running bridge is visible to status."""
    from jaeger_ai.cli import status_cmd

    root = _minimal_instance(tmp_path)
    layout = _layout(root)
    seen: dict[str, object] = {}

    def observe():
        seen["found"] = status_cmd._find_pid_file(layout)
        seen["owner"] = pidfile.read_owner(layout)

    _drive_main(monkeypatch, root, observe)

    assert seen["found"] is not None, "a live bridge left no pid file for status"
    assert seen["owner"] == os.getpid()


def test_bridge_main_deregisters_on_clean_exit(tmp_path, monkeypatch):
    root = _minimal_instance(tmp_path)
    layout = _layout(root)

    _drive_main(monkeypatch, root, lambda: None)

    assert not pidfile.pid_path(layout).exists(), \
        "clean shutdown left a stale pid file behind"
