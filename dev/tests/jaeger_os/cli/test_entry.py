"""jaeger console-script dispatcher — the pure routing table.

Pins jaeger_os.cli.entry._route against the historical ./jaeger wrapper's case
statement so the two can never silently diverge.
"""

from jaeger_os.cli import entry

PY = "/venv/bin/python"


def route(argv):
    return entry._route(argv, PY)


def test_console_subcommands_go_to_cli():
    for sub in ("instances", "skills", "personality", "status",
                "roadmap", "avatar", "prompt", "config"):
        assert route([sub, "x"]) == [PY, "-m", "jaeger_os.cli", sub, "x"]


def test_setup_aliases_instances_create():
    assert route(["setup", "bob"]) == [PY, "-m", "jaeger_os.cli",
                                       "instances", "create", "bob"]


def test_doctor_routes_to_runner_with_flag():
    assert route(["doctor"]) == [PY, "-m", "jaeger_os.cli.run", "--doctor"]
    assert route(["doctor", "-v"]) == [PY, "-m", "jaeger_os.cli.run", "--doctor", "-v"]


def test_bridge_and_mcp():
    assert route(["bridge"]) == [PY, "-m", "jaeger_os.interfaces.bridge"]
    assert route(["mcp", "--x"]) == [PY, "-m", "jaeger_os.interfaces.mcp_server", "--x"]


def test_dev_defaults_to_tui_and_passes_flags():
    assert route(["--dev"]) == [PY, "-m", "jaeger_os.cli.devtools"]
    assert route(["--dev", "--status"]) == [PY, "-m", "jaeger_os.cli.devtools", "--status"]


def test_version_and_help_go_to_cli():
    assert route(["--version"]) == [PY, "-m", "jaeger_os.cli", "--version"]
    assert route(["version"]) == [PY, "-m", "jaeger_os.cli", "--version"]
    for h in ("help", "--help", "-h"):
        assert route([h]) == [PY, "-m", "jaeger_os.cli", "--help"]


def test_bare_and_agent_flags_run_the_agent():
    assert route([]) == [PY, "-m", "jaeger_os.cli.run"]
    assert route(["--voice"]) == [PY, "-m", "jaeger_os.cli.run", "--voice"]
    assert route(["--instance", "lilith"]) == [PY, "-m", "jaeger_os.cli.run",
                                               "--instance", "lilith"]
    assert route(["hello world"]) == [PY, "-m", "jaeger_os.cli.run", "hello world"]
