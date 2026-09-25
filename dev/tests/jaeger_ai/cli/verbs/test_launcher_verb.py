"""``jaeger launcher`` — thin macOS .app. The lsregister / /Applications IO is
not OS-tested; these cover the bundle builders, a temp-dir bundle write, app-dir
resolution, and platform/argument routing."""

from __future__ import annotations

import os
import plistlib
import shutil
from pathlib import Path

from jaeger_ai.cli.verbs import launcher_verb as L


def test_native_install_keeps_recoverable_previous_launcher(tmp_path):
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"canonical")
    source = tmp_path / "build/Jaeger AI.app"
    target = tmp_path / "Applications/Jaeger AI.app"
    L._write_bundle(source, Path("/new/jaeger"), icon_source=icon)
    L._write_bundle(target, Path("/old/jaeger"), icon_source=icon)
    backup = L._install_native_bundle(source, target, tmp_path / "backups")
    assert "/old/jaeger" in (backup / "Contents/MacOS/Jaeger AI").read_text()
    assert "/new/jaeger" in (target / "Contents/MacOS/Jaeger AI").read_text()
    assert (target / "Contents/Resources/AppIcon.icns").read_bytes() == b"canonical"


def test_native_install_refuses_unrelated_application(tmp_path):
    import pytest

    source = tmp_path / "source.app"
    L._write_bundle(source, Path("/new/jaeger"))
    target = tmp_path / "Applications/Jaeger AI.app"
    shutil.copytree(source, target)
    with (target / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "someone.else"}, stream)
    with pytest.raises(ValueError, match="unrelated app"):
        L._install_native_bundle(source, target, tmp_path / "backups")
    assert target.exists()


def test_stub_execs_the_jaeger_exe():
    stub = L._stub_script(Path("/x/jaeger/.venv/bin/jaeger"))
    assert stub.startswith("#!/bin/bash")
    assert 'exec "/x/jaeger/.venv/bin/jaeger" "$@"' in stub


def test_info_plist_keys():
    p = L._info_plist()
    assert p["CFBundleExecutable"] == "Jaeger AI"
    assert p["CFBundleDisplayName"] == "Jaeger AI"
    assert p["CFBundleIdentifier"] == L._BUNDLE_ID
    assert p["CFBundleShortVersionString"]            # the live __version__


def test_write_bundle_creates_executable_stub_and_valid_plist(tmp_path):
    app = tmp_path / "Jaeger AI.app"
    exe = Path("/x/jaeger/.venv/bin/jaeger")
    icon = tmp_path / "source.icns"
    icon.write_bytes(b"icon")
    stub = L._write_bundle(app, exe, icon_source=icon)
    assert stub == app / "Contents" / "MacOS" / "Jaeger AI"
    assert str(exe) in stub.read_text()
    assert os.access(stub, os.X_OK)                   # +x bit set
    with open(app / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)                      # parses → valid plist
    assert plist["CFBundleExecutable"] == "Jaeger AI"
    assert plist["CFBundleIconFile"] == "AppIcon"
    assert (app / "Contents" / "Resources" / "AppIcon.icns").read_bytes() == b"icon"


def test_app_dir_prefers_applications_when_writable(monkeypatch):
    monkeypatch.setattr(L.Path, "is_dir", lambda self: True)
    monkeypatch.setattr(L.os, "access", lambda p, m: True)
    assert L._app_dir() == Path("/Applications") / "Jaeger AI.app"


def test_app_dir_falls_back_to_home_when_not_writable(monkeypatch):
    monkeypatch.setattr(L.os, "access", lambda p, m: False)
    assert L._app_dir() == Path.home() / "Applications" / "Jaeger AI.app"


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
