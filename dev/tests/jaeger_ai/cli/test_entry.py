"""jaeger console-script dispatcher — the pure routing table.

Pins jaeger_os.cli.entry._route against the historical ./jaeger wrapper's case
statement so the two can never silently diverge.
"""

from jaeger_ai.cli import entry

PY = "/venv/bin/python"


def route(argv):
    return entry._route(argv, PY)


def test_native_run_recovery_route():
    assert route(["runs", "reconcile", "openclaw", "a" * 32]) == [
        PY, "-m", "jaeger_ai.core.frameworks.recovery",
        "reconcile", "openclaw", "a" * 32,
    ]


def test_console_subcommands_go_to_cli():
    for sub in ("skills", "personality",
                "roadmap", "avatar", "prompt", "config",
                "runtime", "backends"):
        assert route([sub, "x"]) == [PY, "-m", "jaeger_ai.cli", sub, "x"]


def test_setup_routes_terminal_first_wizard():
    # Terminal-first (OpenClaw parity): bare `setup` runs the interactive
    # wizard in the terminal. The GUI is the opt-in, not the default —
    # see `_route`'s setup branch in jaeger_ai/cli/entry.py.
    assert route(["setup", "bob"]) == [PY, "-m", "jaeger_ai.cli.run",
                                       "setup", "bob"]
    for alias in ("onboard", "onboarding"):
        assert route([alias]) == [PY, "-m", "jaeger_ai.cli.run", "setup"]


def test_setup_gui_opts_into_agent_create():
    # `gui` (positional) and `--gui` (flag) both opt into the windowed
    # onboarding, and the opt-in token is stripped before dispatch so
    # agent-create's positional-name shim still sees the name at rest[0].
    assert route(["setup", "gui"]) == [PY, "-m", "jaeger_ai.cli.run",
                                       "agent", "create"]
    assert route(["setup", "gui", "bob"]) == [PY, "-m", "jaeger_ai.cli.run",
                                              "agent", "create", "bob"]
    assert route(["setup", "--gui", "bob"]) == [PY, "-m", "jaeger_ai.cli.run",
                                                "agent", "create", "bob"]


def test_doctor_routes_to_runner_with_flag():
    assert route(["doctor"]) == [PY, "-m", "jaeger_ai.cli.run", "--doctor"]
    assert route(["doctor", "-v"]) == [PY, "-m", "jaeger_ai.cli.run", "--doctor", "-v"]


def test_bridge_and_mcp():
    assert route(["bridge"]) == [PY, "-m", "jaeger_ai.interfaces.bridge"]
    assert route(["mcp", "--x"]) == [PY, "-m", "jaeger_ai.interfaces.mcp_server", "--x"]
    assert route(["mcp", "--http"]) == [PY, "-m", "jaeger_ai.interfaces.mcp_server", "--http"]
    assert route(["a2a"]) == [PY, "-m", "jaeger_ai.interfaces.a2a_server"]
    assert route(["gateway", "start"]) == [PY, "-m", "jaeger_ai.features.agentgateway", "start"]


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


def test_update_preserves_help_without_running_update():
    assert route(['update', '--help']) == [PY, '-m', 'jaeger_ai.cli.devtools', '--update', '--help']
