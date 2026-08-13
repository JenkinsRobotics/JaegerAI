"""jaeger console-script dispatcher — the pure routing table.

Pins jaeger_os.cli.entry._route against the historical ./jaeger wrapper's case
statement so the two can never silently diverge.
"""

from jaeger_ai.cli import entry

PY = "/venv/bin/python"


def route(argv):
    return entry._route(argv, PY)


def test_console_subcommands_go_to_cli():
    for sub in ("skills", "personality", "status",
                "roadmap", "avatar", "prompt", "config"):
        assert route([sub, "x"]) == [PY, "-m", "jaeger_ai.cli", sub, "x"]


def test_setup_routes_gui_first_agent_create():
    # GUI-first (2026-07-17): setup goes through `agent create`, which
    # opens the app's onboarding and falls back to the terminal wizard
    # itself when headless / no app.
    assert route(["setup", "bob"]) == [PY, "-m", "jaeger_ai.cli.run",
                                       "agent", "create", "bob"]


def test_setup_tui_forces_terminal_wizard():
    assert route(["setup", "tui"]) == [PY, "-m", "jaeger_ai.cli.run",
                                       "agent", "create", "--tui"]
    # --tui trails so agent-create's positional-name shim still sees the
    # name at rest[0].
    assert route(["setup", "tui", "bob"]) == [PY, "-m", "jaeger_ai.cli.run",
                                              "agent", "create", "bob", "--tui"]


def test_doctor_routes_to_runner_with_flag():
    assert route(["doctor"]) == [PY, "-m", "jaeger_ai.cli.run", "--doctor"]
    assert route(["doctor", "-v"]) == [PY, "-m", "jaeger_ai.cli.run", "--doctor", "-v"]


def test_bridge_and_mcp():
    assert route(["bridge"]) == [PY, "-m", "jaeger_ai.interfaces.bridge"]
    assert route(["mcp", "--x"]) == [PY, "-m", "jaeger_ai.interfaces.mcp_server", "--x"]


def test_dev_defaults_to_tui_and_passes_flags():
    assert route(["--dev"]) == [PY, "-m", "jaeger_ai.cli.devtools"]
    assert route(["--dev", "--status"]) == [PY, "-m", "jaeger_ai.cli.devtools", "--status"]


def test_version_and_help_go_to_cli():
    assert route(["--version"]) == [PY, "-m", "jaeger_ai.cli", "--version"]
    assert route(["version"]) == [PY, "-m", "jaeger_ai.cli", "--version"]
    for h in ("help", "--help", "-h"):
        assert route([h]) == [PY, "-m", "jaeger_ai.cli", "--help"]


def test_bare_and_agent_flags_run_the_agent():
    assert route([]) == [PY, "-m", "jaeger_ai.cli.run"]
    assert route(["--voice"]) == [PY, "-m", "jaeger_ai.cli.run", "--voice"]
    assert route(["--instance", "lilith"]) == [PY, "-m", "jaeger_ai.cli.run",
                                               "--instance", "lilith"]
    assert route(["hello world"]) == [PY, "-m", "jaeger_ai.cli.run", "hello world"]
