"""Every real jaeger entry point must be recognised as one.

``is_real_jaeger_command`` decides whether the PID recorded in an
instance's ``.lock`` belongs to a live jaeger. When it says no, the lock
is declared stale and BROKEN — which is correct for a recycled PID and
catastrophic for a live holder, because it hands two processes the same
instance.

The allowlist recognised ``-m jaeger_os`` and
``-m jaeger_ai.interfaces.bridge`` but not the ``jaeger_ai.cli.*``
family — which is what ``cli/entry.py`` os.execv's into for the ordinary
terminal agent. ``jaeger`` therefore took the instance lock as a process
that the lock checker did not believe was jaeger, so the next start broke
a live lock instead of refusing.

These cases are the literal argv shapes ``_route`` produces, so the test
fails if routing moves to a module the allowlist does not cover.
"""

from __future__ import annotations

import pytest

from jaeger_ai.cli import entry
from jaeger_ai.core.instance.procshape import is_real_jaeger_command

PY = ("/opt/homebrew/Cellar/python@3.11/3.11.15/Frameworks/Python.framework/"
      "Versions/3.11/Resources/Python.app/Contents/MacOS/Python")


@pytest.mark.parametrize("argv", [
    [],                       # bare `jaeger` — runs the agent, TAKES THE LOCK
    ["setup"],
    ["setup", "tui"],
    ["doctor"],
    ["bridge"],
    ["mcp"],
    ["status"],
    ["skills"],
    ["dev"],
    ["some free-form prompt"],
])
def test_every_routed_entry_point_is_recognised(argv):
    """Whatever _route execs into must be jaeger-shaped to the lock check."""
    routed = entry._route(list(argv), PY)
    cmdline = " ".join(routed)
    assert is_real_jaeger_command(cmdline), (
        f"`jaeger {' '.join(argv) or '(bare)'}` execs to {cmdline!r}, which the "
        "lock checker does not recognise — a live lock held by this process "
        "would be broken as stale")


@pytest.mark.parametrize("cmdline", [
    f"{PY} -m jaeger_ai.cli.run",
    f"{PY} -m jaeger_ai.cli.run agent create",
    f"{PY} -m jaeger_ai.cli",
    f"{PY} -m jaeger_ai.interfaces.bridge ares",
    f"{PY} -m jaeger_os.cli",
    "/Users/x/GitHub/JaegerAI/.venv/bin/jaeger status",
])
def test_known_good_cmdlines(cmdline):
    assert is_real_jaeger_command(cmdline) is True


@pytest.mark.parametrize("cmdline", [
    "/bin/zsh -c 'source snapshot.sh && jaeger_ai'",
    "/bin/bash -c 'echo -m jaeger_os'",
    "/usr/bin/vim jaeger_ai/main.py",
    f"{PY} -c 'import jaeger_ai'",
    "",
])
def test_impostors_are_still_rejected(cmdline):
    """The point of the allowlist: a recycled PID must not hold an instance."""
    assert is_real_jaeger_command(cmdline) is False
