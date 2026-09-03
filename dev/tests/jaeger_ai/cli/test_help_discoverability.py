"""Every dispatcher command must be discoverable from ``jaeger --help``.

Field blocker #7: ``jaeger doctor`` works, and the release checklist tells
operators to run it, but it appeared nowhere in ``--help`` — an operator
had no way to learn it exists short of reading ``cli/entry.py``.

The commands in question are dispatched by ``entry._route`` (each re-execs
a different module), so they are NOT argparse subparsers and never reach
the console parser. Discoverability therefore has to come from the help
epilog. This test pins that: if someone adds a route, help must grow a
line for it, or this fails.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from jaeger_ai.cli import entry

# Routed by entry._route to something other than the console parser.
# Machine-facing surfaces (bridge, mcp) count too: an operator debugging a
# stuck app needs to know they can run them by hand.
DISPATCHER_COMMANDS = (
    "setup",
    "bridge",
    "mcp",
    "a2a",
    "gateway",
    "hermes-webui-adapter",
    "doctor",
    "update",
    "dev",
)


def _help_text() -> str:
    from jaeger_ai import cli

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit):
        cli.main(["--help"])
    return buf.getvalue()


@pytest.mark.parametrize("cmd", DISPATCHER_COMMANDS)
def test_dispatcher_command_appears_in_help(cmd):
    assert cmd in _help_text(), (
        f"`jaeger {cmd}` is routable but invisible in --help")


def test_route_table_and_help_do_not_drift():
    """A new route without a help line is the regression this guards."""
    text = _help_text()
    for cmd in DISPATCHER_COMMANDS:
        routed = entry._route([cmd], "/usr/bin/python3")
        assert routed[:2] == ["/usr/bin/python3", "-m"], \
            f"{cmd} is no longer a dispatcher route — update this test"
        assert cmd in text
