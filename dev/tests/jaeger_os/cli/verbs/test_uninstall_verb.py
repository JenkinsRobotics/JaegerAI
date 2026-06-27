"""``jaeger uninstall`` — remove framework, keep/wipe agents. The destructive
+ safety paths: refuse on a dev clone, keep agents by default, --purge wipes,
non-interactive refuses without --yes."""

from __future__ import annotations

from pathlib import Path

from jaeger_os.cli.verbs import uninstall_verb as U

_PKG = "jaeger_os.core.instance.instance.PACKAGE_ROOT"


def _fake_install(tmp_path: Path, *, git: bool = False) -> Path:
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("x")
    (home / ".venv" / "bin").mkdir(parents=True)
    (home / "requirements.txt").write_text("deps")
    agent = home / ".jaeger_os" / "instances" / "default"
    agent.mkdir(parents=True)
    (agent / "identity.yaml").write_text("name: default")
    if git:
        (home / ".git").mkdir()
    return home


def test_uninstall_refuses_dev_clone(tmp_path, monkeypatch, capsys):
    home = _fake_install(tmp_path, git=True)
    monkeypatch.setattr(_PKG, home / "jaeger_os")
    assert U._cmd_uninstall_argv(["--yes"]) == 2
    assert "dev clone" in capsys.readouterr().err
    assert (home / "jaeger_os").exists()              # nothing removed


def test_uninstall_removes_framework_keeps_agents(tmp_path, monkeypatch):
    home = _fake_install(tmp_path)
    monkeypatch.setattr(_PKG, home / "jaeger_os")
    assert U._cmd_uninstall_argv(["--yes"]) == 0
    assert not (home / "jaeger_os").exists()
    assert not (home / ".venv").exists()
    assert not (home / "requirements.txt").exists()
    # agents survive
    assert (home / ".jaeger_os" / "instances" / "default" / "identity.yaml").exists()


def test_uninstall_purge_wipes_agents(tmp_path, monkeypatch):
    home = _fake_install(tmp_path)
    monkeypatch.setattr(_PKG, home / "jaeger_os")
    assert U._cmd_uninstall_argv(["--purge", "--yes"]) == 0
    assert not (home / "jaeger_os").exists()
    assert not (home / ".jaeger_os").exists()         # purged


def test_uninstall_non_interactive_without_yes_refuses(tmp_path, monkeypatch, capsys):
    home = _fake_install(tmp_path)
    monkeypatch.setattr(_PKG, home / "jaeger_os")
    # pytest's captured stdin is not a tty → non-interactive path
    assert U._cmd_uninstall_argv([]) == 2
    assert "non-interactive" in capsys.readouterr().err
    assert (home / "jaeger_os").exists()              # nothing removed
