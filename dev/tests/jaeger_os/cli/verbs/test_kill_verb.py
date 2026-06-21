"""``jaeger kill`` — force-stop hung jaeger sessions.

Pin the verb's contract:
  * idempotent (running with nothing to do is rc=0, no errors)
  * --dry-run lists targets without acting
  * lock-file sweep is scoped to known names under instance run/ dirs
  * the process-finder won't accidentally match unrelated python procs
  * never kills its own PID (the verb running this kill scan)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from jaeger_os.cli.verbs import kill_verb


# ── _find_lock_files ─────────────────────────────────────────────


def _make_instance_dir(parent: Path, name: str, *,
                       with_lock: bool = True) -> Path:
    """Build a minimal ``<parent>/<name>/run/`` with stale lock files."""
    inst = parent / name
    (inst / "run").mkdir(parents=True)
    if with_lock:
        (inst / "run" / "tui.pid").write_text("99999")
        (inst / "run" / "jaeger.lock").write_text("99999")
    return inst


def test_find_lock_files_finds_files_under_instance_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    _make_instance_dir(instances, "default")
    _make_instance_dir(instances, "work")

    found = kill_verb._find_lock_files()
    names = sorted(p.name for p in found)
    # Two instances × two lock-file types each.
    assert names == ["jaeger.lock", "jaeger.lock", "tui.pid", "tui.pid"]


def test_find_lock_files_filters_by_instance_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    _make_instance_dir(instances, "default")
    _make_instance_dir(instances, "work")

    found = kill_verb._find_lock_files(instance="work")
    assert all("work" in str(p) for p in found)
    assert len(found) == 2


def test_find_lock_files_handles_dev_sandbox(tmp_path, monkeypatch):
    """JAEGER_INSTANCE_DIR points at a single instance dir (not a
    parent that contains instances). The finder must handle both
    shapes."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # empty home
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    sandbox = tmp_path / "sandbox" / "jros-dev"
    (sandbox / "run").mkdir(parents=True)
    (sandbox / "run" / "tui.pid").write_text("99999")
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(sandbox))

    found = kill_verb._find_lock_files()
    assert len(found) == 1
    assert found[0].name == "tui.pid"


def test_find_lock_files_returns_empty_when_no_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    assert kill_verb._find_lock_files() == []


def test_find_lock_files_only_picks_known_names(tmp_path, monkeypatch):
    """A file called ``some_other.pid`` under run/ must not be
    swept — only the documented names."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    inst = instances / "default"
    (inst / "run").mkdir(parents=True)
    (inst / "run" / "tui.pid").write_text("99999")            # IN
    (inst / "run" / "user_unrelated.pid").write_text("123")   # OUT
    (inst / "run" / "scratch.txt").write_text("nothing")      # OUT

    found = kill_verb._find_lock_files()
    names = {p.name for p in found}
    assert names == {"tui.pid"}


# ── _find_jaeger_pids ────────────────────────────────────────────


def test_find_jaeger_pids_excludes_own_pid(monkeypatch):
    """The verb must skip its own PID — otherwise it would SIGKILL
    itself before completing the sweep. The function takes an
    ``exclude`` set; the dispatcher always passes ``{os.getpid()}``."""
    # Stub ps output: a python jaeger_os process at our own PID.
    own = os.getpid()
    fake_out = f"{own} python /path/to/jaeger_os/__main__.py\n"
    monkeypatch.setattr(
        kill_verb.subprocess, "check_output",
        lambda *a, **kw: fake_out,
    )
    out = kill_verb._find_jaeger_pids(exclude={own})
    assert out == []


def test_find_jaeger_pids_matches_jaeger_entrypoints_only(monkeypatch):
    """Strict matching against the canonical entrypoint shapes:
       * ``python -m jaeger_os ...``
       * ``python .../jaeger_os/__main__.py ...``
       * ``... bin/jaeger ...``

    A shell whose ``-c`` argument happens to mention 'python' AND
    'jaeger_os' (e.g. activating a venv) MUST NOT match — that was
    a real false positive that almost killed an unrelated zsh."""
    fake_out = (
        "100 /bin/bash -c 'echo jaeger_os'\n"              # OUT: shell
        "101 python /unrelated/script.py\n"                # OUT: not jaeger
        "102 python /repo/jaeger_os/__main__.py\n"         # IN
        "103 /opt/python3.11 -m jaeger_os start\n"         # IN
        "104 /opt/python3.11 -m jaeger_os.cli.verbs.dispatch kill\n"  # IN
        "105 /repo/.venv/bin/jaeger start\n"               # IN
        "106 /bin/zsh -c source /x/snap.zsh && /py/python -m jaeger_os\n"  # OUT: zsh
        "107 /usr/bin/vim /Users/x/jaeger_os/main.py\n"    # OUT: editor
    )
    monkeypatch.setattr(
        kill_verb.subprocess, "check_output",
        lambda *a, **kw: fake_out,
    )
    out = kill_verb._find_jaeger_pids(exclude=set())
    pids = sorted(pid for pid, _ in out)
    assert pids == [102, 103, 104, 105]


def test_is_real_jaeger_command_rejects_shells_with_jaeger_in_argv():
    """Regression for the false positive that almost killed a zsh
    whose ``-c`` argument referenced a snapshot path containing
    both 'python' and 'jaeger_os'."""
    cases = [
        # (cmdline, expected)
        ("/bin/zsh -c source /x/python-jaeger_os.zsh", False),
        ("/bin/bash -c 'source venv && jaeger_os'", False),
        ("/usr/bin/zsh", False),
        ("/usr/bin/python -m jaeger_os start", True),
        ("/usr/bin/python -m jaeger_os.cli.verbs.dispatch kill", True),
        ("/repo/.venv/bin/jaeger", True),
        ("/repo/.venv/bin/jaeger start --instance default", True),
        ("/path/to/python /repo/src/jaeger_os/__main__.py", True),
        ("vim /repo/src/jaeger_os/main.py", False),
    ]
    for cmd, expected in cases:
        got = kill_verb._is_real_jaeger_command(cmd)
        assert got == expected, f"{cmd!r} → {got}, expected {expected}"


def test_find_jaeger_pids_returns_empty_on_ps_failure(monkeypatch):
    """``ps`` failing for any reason must not crash the verb."""
    def _raise(*a, **kw):
        raise OSError("ps not found")
    monkeypatch.setattr(kill_verb.subprocess, "check_output", _raise)
    assert kill_verb._find_jaeger_pids() == []


# ── _cmd_kill_argv ───────────────────────────────────────────────


def test_kill_with_nothing_to_do_returns_zero(tmp_path, monkeypatch, capsys):
    """No processes, no locks → clean exit, rc=0, no error noise."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.setattr(
        kill_verb, "_find_jaeger_pids", lambda **_kw: [],
    )
    rc = kill_verb._cmd_kill_argv([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing to do" in out


def test_kill_dry_run_lists_but_does_not_act(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    _make_instance_dir(instances, "default")

    monkeypatch.setattr(
        kill_verb, "_find_jaeger_pids",
        lambda **_kw: [(12345, "python /x/jaeger_os/__main__.py")],
    )
    # Spy on os.kill so we can prove it wasn't called.
    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        kill_verb.os, "kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )

    rc = kill_verb._cmd_kill_argv(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would SIGKILL" in out
    assert "12345" in out
    assert "would remove" in out
    # No actual kills, no actual unlinks (lock files still there).
    assert kill_calls == []
    assert (instances / "default" / "run" / "tui.pid").exists()


def test_kill_removes_stale_lock_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    inst = _make_instance_dir(instances, "default")

    # No processes — just lock-file sweep.
    monkeypatch.setattr(
        kill_verb, "_find_jaeger_pids", lambda **_kw: [],
    )

    rc = kill_verb._cmd_kill_argv([])
    assert rc == 0
    assert not (inst / "run" / "tui.pid").exists()
    assert not (inst / "run" / "jaeger.lock").exists()


def test_kill_signals_targeted_pids(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)

    monkeypatch.setattr(
        kill_verb, "_find_jaeger_pids",
        lambda **_kw: [(12345, "python /x/jaeger_os/__main__.py")],
    )
    signals: list[tuple[int, int]] = []
    def _spy(pid, sig):
        signals.append((pid, sig))
    monkeypatch.setattr(kill_verb.os, "kill", _spy)
    # Skip the grace sleep so the test stays fast.
    monkeypatch.setattr(kill_verb.time, "sleep", lambda _s: None)

    rc = kill_verb._cmd_kill_argv([])
    assert rc == 0
    sent = {sig for _pid, sig in signals if _pid == 12345}
    # SIGTERM grace pass + SIGKILL hard pass.
    import signal as _signal
    assert _signal.SIGTERM in sent
    assert _signal.SIGKILL in sent


def test_kill_help_returns_zero(capsys):
    rc = kill_verb._cmd_kill_argv(["-h"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "jaeger kill" in err
    assert "dry-run" in err


def test_kill_handles_processes_already_gone(tmp_path, monkeypatch):
    """If a process exited between the ps scan and the SIGTERM, the
    ProcessLookupError must be swallowed — the verb keeps going and
    still cleans locks."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    instances = tmp_path / ".jaeger_os" / "instances"
    instances.mkdir(parents=True)
    inst = _make_instance_dir(instances, "default")

    monkeypatch.setattr(
        kill_verb, "_find_jaeger_pids",
        lambda **_kw: [(99999, "python /x/jaeger_os/__main__.py")],
    )

    def _raise(pid, sig):
        raise ProcessLookupError(f"no such pid {pid}")
    monkeypatch.setattr(kill_verb.os, "kill", _raise)
    monkeypatch.setattr(kill_verb.time, "sleep", lambda _s: None)

    rc = kill_verb._cmd_kill_argv([])
    # rc=0 — and the lock files still got swept despite the kill failing.
    assert rc == 0
    assert not (inst / "run" / "tui.pid").exists()


# ── dispatcher integration ───────────────────────────────────────


def test_cli_dispatcher_registers_kill():
    from jaeger_os.cli.verbs import dispatch as cli
    assert "kill" in cli.SUBCOMMANDS
    assert cli.is_daemon_subcommand(["kill"]) is True
    assert cli.is_daemon_subcommand(["kill", "--dry-run"]) is True
