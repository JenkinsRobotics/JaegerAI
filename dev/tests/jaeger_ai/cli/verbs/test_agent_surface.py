"""`jaeger agent` — the operator-facing front-end over instance management,
and the `--agent` flag alias of `--instance`. The rename is surface-only:
these assert the delegation, not a renamed backend."""

from __future__ import annotations

from jaeger_ai.cli.verbs import instance_verbs as I


def test_agent_create_maps_positional_name_to_setup(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(I, "_cmd_setup_argv",
                        lambda argv: seen.update(argv=argv) or 0)
    assert I._cmd_agent_argv(["create", "jarvis"]) == 0
    assert seen["argv"] == ["--name", "jarvis"]        # positional → --name


def test_agent_create_passes_flags_through(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(I, "_cmd_setup_argv",
                        lambda argv: seen.update(argv=argv) or 0)
    assert I._cmd_agent_argv(["create", "--force"]) == 0
    assert seen["argv"] == ["--force"]                 # flags untouched


def test_agent_create_gui_first(monkeypatch, tmp_path):
    """0.7.1: with the product app built and the target instance missing,
    `agent create <name>` launches the app (pinned to <name>) instead of
    the terminal wizard."""
    from pathlib import Path

    import jaeger_ai.core.instance.instance as inst
    import jaeger_ai.main as M

    monkeypatch.delenv("JAEGER_NO_GUI", raising=False)
    monkeypatch.setattr(M, "_swift_app_binary", lambda: Path("/fake/app"))
    seen: dict = {}
    monkeypatch.setattr(M, "_launch_swift_app",
                        lambda app, name: seen.update(name=name) or 0)
    monkeypatch.setattr(inst, "resolve_instance_dir",
                        lambda name: tmp_path / name)   # never exists
    assert I._cmd_agent_argv(["create", "jarvis"]) == 0
    assert seen == {"name": "jarvis"}


def test_agent_create_tui_flag_forces_terminal_wizard(monkeypatch):
    monkeypatch.delenv("JAEGER_NO_GUI", raising=False)
    seen: dict = {}
    monkeypatch.setattr(I, "_cmd_setup_argv",
                        lambda argv: seen.update(argv=argv) or 0)
    assert I._cmd_agent_argv(["create", "jarvis", "--tui"]) == 0
    assert seen["argv"] == ["--name", "jarvis"]        # --tui consumed


def test_agent_verbs_delegate_to_instance(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(I, "_cmd_instance_argv",
                        lambda argv: seen.update(argv=argv) or 0)
    for verb in ("list", "use", "inspect", "delete", "clear"):
        seen.clear()
        assert I._cmd_agent_argv([verb, "x"]) == 0
        assert seen["argv"] == [verb, "x"]             # full argv, verb included


def test_agent_unknown_and_help():
    assert I._cmd_agent_argv([]) == 2                  # no command → misuse
    assert I._cmd_agent_argv(["bogus"]) == 2           # unknown command
    assert I._cmd_agent_argv(["--help"]) == 0


def test_agent_flag_aliases_instance(monkeypatch):
    import jaeger_ai.main as M
    monkeypatch.setattr("sys.argv", ["jaeger", "--agent", "lilith"])
    assert M.parse_args().instance == "lilith"         # --agent → dest=instance
