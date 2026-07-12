"""``jaeger autostart`` — boot/login service for a unit.

The launchctl / systemctl calls are real-OS IO (not tested); these cover the
pure service-file builders, exe resolution, platform routing, and a mocked
macOS enable (asserts the plist is written + load attempted)."""

from __future__ import annotations

from pathlib import Path

from jaeger_ai.cli.verbs import autostart_verb as A


def test_launchd_plist_content():
    txt = A._launchd_plist(Path("/x/jaeger"), Path("/x"), ["--tui"])
    assert "/x/jaeger" in txt and "--tui" in txt
    assert "<key>RunAtLoad</key><true/>" in txt
    assert "<key>KeepAlive</key><true/>" in txt
    assert A._LABEL in txt


def test_systemd_unit_content():
    txt = A._systemd_unit(Path("/x/jaeger"), Path("/x"), ["--voice"])
    assert "ExecStart=/x/jaeger --voice" in txt
    assert "Restart=on-failure" in txt
    assert "WantedBy=default.target" in txt


def test_jaeger_exe_prefers_venv(tmp_path):
    (tmp_path / "jaeger").write_text("wrapper")
    assert A._jaeger_exe(tmp_path) == tmp_path / "jaeger"      # no venv yet
    venvbin = tmp_path / ".venv" / "bin"
    venvbin.mkdir(parents=True)
    (venvbin / "jaeger").write_text("console")
    assert A._jaeger_exe(tmp_path) == venvbin / "jaeger"       # venv wins


def test_unknown_action_and_help():
    assert A._cmd_autostart_argv([]) == 2          # no action → usage, misuse
    assert A._cmd_autostart_argv(["bogus"]) == 2   # unknown action
    assert A._cmd_autostart_argv(["--help"]) == 0  # explicit help


def test_unsupported_platform(monkeypatch):
    monkeypatch.setattr(A.sys, "platform", "win32")
    assert A._cmd_autostart_argv(["enable"]) == 2


def test_dispatch_routes_by_platform(monkeypatch):
    monkeypatch.setattr(A.sys, "platform", "darwin")
    monkeypatch.setattr(A, "_macos_enable", lambda extra: ("mac-enable", extra))
    assert A._cmd_autostart_argv(["enable", "--tui"]) == ("mac-enable", ["--tui"])
    monkeypatch.setattr(A.sys, "platform", "linux")
    monkeypatch.setattr(A, "_linux_status", lambda: "linux-status")
    assert A._cmd_autostart_argv(["status"]) == "linux-status"


def test_macos_enable_writes_plist_and_loads(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".jaeger_os").mkdir(parents=True)
    (home / "jaeger").write_text("#!/bin/sh\n")               # the wrapper exe
    plist = tmp_path / "LaunchAgents" / "jaeger.plist"
    monkeypatch.setattr(A, "_install_root", lambda: home)
    monkeypatch.setattr(A, "_macos_plist_path", lambda: plist)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        A.subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or type(
            "R", (), {"returncode": 0, "stderr": ""})())
    assert A._macos_enable(["--tui"]) == 0
    txt = plist.read_text()
    assert str(home / "jaeger") in txt and "--tui" in txt
    assert "RunAtLoad" in txt
    assert any("load" in c and "-w" in c for c in calls)      # launchctl load -w
