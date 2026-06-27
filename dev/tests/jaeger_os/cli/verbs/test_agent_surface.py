"""`jaeger agent` — the operator-facing front-end over instance management,
and the `--agent` flag alias of `--instance`. The rename is surface-only:
these assert the delegation, not a renamed backend."""

from __future__ import annotations

from jaeger_os.cli.verbs import instance_verbs as I


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
    import jaeger_os.main as M
    monkeypatch.setattr("sys.argv", ["jaeger", "--agent", "lilith"])
    assert M.parse_args().instance == "lilith"         # --agent → dest=instance
