"""``jaeger launcher`` — thin macOS .app. The lsregister / /Applications IO is
not OS-tested; these cover the bundle builders, a temp-dir bundle write, app-dir
resolution, and platform/argument routing."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

from jaeger_ai.cli.verbs import launcher_verb as L


def test_stub_execs_the_jaeger_exe():
    stub = L._stub_script(Path("/x/jaeger/.venv/bin/jaeger"))
    assert stub.startswith("#!/bin/bash")
    assert 'exec "/x/jaeger/.venv/bin/jaeger" "$@"' in stub


def test_info_plist_keys():
    p = L._info_plist()
    assert p["CFBundleExecutable"] == "Jaeger"
    assert p["CFBundleIdentifier"] == L._BUNDLE_ID
    assert p["CFBundleShortVersionString"]            # the live __version__


def test_write_bundle_creates_executable_stub_and_valid_plist(tmp_path):
    app = tmp_path / "Jaeger.app"
    exe = Path("/x/jaeger/.venv/bin/jaeger")
    stub = L._write_bundle(app, exe)
    assert stub == app / "Contents" / "MacOS" / "Jaeger"
    assert str(exe) in stub.read_text()
    assert os.access(stub, os.X_OK)                   # +x bit set
    with open(app / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)                      # parses → valid plist
    assert plist["CFBundleExecutable"] == "Jaeger"


def test_app_dir_prefers_applications_when_writable(monkeypatch):
    monkeypatch.setattr(L.Path, "is_dir", lambda self: True)
    monkeypatch.setattr(L.os, "access", lambda p, m: True)
    assert L._app_dir() == Path("/Applications") / "Jaeger.app"


def test_app_dir_falls_back_to_home_when_not_writable(monkeypatch):
    monkeypatch.setattr(L.os, "access", lambda p, m: False)
    assert L._app_dir() == Path.home() / "Applications" / "Jaeger.app"


def test_routing_unknown_help_and_non_macos(monkeypatch):
    monkeypatch.setattr(L.sys, "platform", "darwin")
    assert L._cmd_launcher_argv([]) == 2              # no action
    assert L._cmd_launcher_argv(["bogus"]) == 2       # unknown action
    assert L._cmd_launcher_argv(["--help"]) == 0
    monkeypatch.setattr(L.sys, "platform", "linux")
    assert L._cmd_launcher_argv(["install"]) == 2     # macOS only


def test_install_routes_on_macos(monkeypatch):
    monkeypatch.setattr(L.sys, "platform", "darwin")
    monkeypatch.setattr(L, "_macos_install", lambda: 0)
    monkeypatch.setattr(L, "_macos_remove", lambda: 0)
    assert L._cmd_launcher_argv(["install"]) == 0
    assert L._cmd_launcher_argv(["remove"]) == 0
