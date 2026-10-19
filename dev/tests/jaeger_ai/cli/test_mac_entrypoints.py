"""Canonical shell selection must never revive an archived SwiftUI app."""
from pathlib import Path

import pytest


def test_normal_mac_selection_ignores_legacy_build_and_selects_only_shell(tmp_path, monkeypatch):
    from jaeger_ai import main
    from jaeger_ai.core.instance import instance
    monkeypatch.setattr(instance, "install_root", lambda: tmp_path)
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(tmp_path / "external"))
    # install_root is a source checkout, so select an actually external build.
    monkeypatch.setattr(instance, "install_root", lambda: tmp_path / "source")
    old = tmp_path / "external/JaegerAI.app/Contents/MacOS/JaegerAI"
    old.parent.mkdir(parents=True); old.write_text("old")
    assert main._mac_app_binary() is None
    current = tmp_path / "external/JaegerShell.app/Contents/MacOS/JaegerShell"
    current.parent.mkdir(parents=True); current.write_text("current")
    assert main._mac_app_binary() == current


def test_new_shell_build_rejects_repository_output(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_shell_build_dir
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(tmp_path / "nested"))
    with pytest.raises(ValueError, match="outside the repository"):
        mac_shell_build_dir(tmp_path)


def test_launcher_install_does_not_fall_back_to_old_product_identity(monkeypatch, capsys):
    from jaeger_ai.cli.verbs import launcher_verb
    def forbidden(*args, **kwargs):
        pytest.fail("cleanup must not install or invoke an old app")
    monkeypatch.setattr(launcher_verb.subprocess, "run", forbidden)
    assert launcher_verb._macos_install() == 1
    assert "development bundle identity" in capsys.readouterr().err
