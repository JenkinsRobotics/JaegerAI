"""``jaeger`` — the single command dispatcher.

Behind BOTH the installed ``jaeger`` console script (pyproject
``[project.scripts]``) and the ``./jaeger`` wrapper, which now delegates here.
Before 0.6 the dispatch lived only in the bash wrapper, so the command worked
only from inside the repo; moving it into Python lets one ``jaeger`` work from
anywhere on PATH.

It mirrors the historical wrapper routing 1:1: each subcommand re-execs
``python -m <module>`` (via :func:`os.execv`, exactly like the wrapper's
``exec``), so command behaviour is byte-identical to before — only the dispatch
moved. Management subcommands go to :mod:`jaeger_os.cli`; everything else runs
the agent via :mod:`jaeger_os.cli.run`.

:func:`_route` is PURE (argv -> the argv to exec), so the whole routing table is
unit-testable without spawning anything; :func:`main` just execs what it returns.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Operator-console subcommands handled by jaeger_os.cli (argparse subparsers).
# (0.9.6: "instances" removed — `jaeger agent` is the one management
# surface; it rides the run path's verb dispatch, not this console.)
_CONSOLE = (
    "skills", "personality", "status",
    "roadmap", "avatar", "prompt", "config",
)


def _route(argv: list[str], py: str) -> list[str]:
    """Map the operator's argv to the ``python -m …`` (or launch.py) argv to
    exec. Mirrors the ./jaeger wrapper's case statement exactly."""
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    if cmd in _CONSOLE:
        return [py, "-m", "jaeger_ai.cli", *argv]
    if cmd == "setup":
        # GUI-first (operator call 2026-07-17): plain `jaeger setup` opens
        # the app's onboarding window via the agent-create path, which
        # falls back to the terminal wizard on its own when there's no
        # built app / headless / JAEGER_NO_GUI. `jaeger setup tui` (or
        # --tui) forces the terminal wizard explicitly.
        if rest[:1] == ["tui"]:
            # --tui goes LAST: agent-create's positional-name shim only
            # looks at rest[0], so a name must stay in front.
            rest = [*rest[1:], "--tui"]
        return [py, "-m", "jaeger_ai.cli.run", "agent", "create", *rest]
    if cmd == "bridge":
        return [py, "-m", "jaeger_ai.interfaces.bridge", *rest]
    if cmd == "mcp":
        return [py, "-m", "jaeger_ai.interfaces.mcp_server", *rest]
    if cmd == "doctor":
        return [py, "-m", "jaeger_ai.cli.run", "--doctor", *rest]
    if cmd == "update":
        # Two updaters, one word: in a DEV CHECKOUT `jaeger update` is the
        # git-pull dev loop (devtools); in a clean product install it must
        # fall through to the real end-user updater (cli/verbs/update_verb,
        # reached via the main dispatch). Detect the checkout by the repo
        # markers next to this package — a pip install has neither.
        _repo = Path(__file__).resolve().parents[2]
        if (_repo / "pyproject.toml").exists() and (_repo / ".git").exists():
            return [py, "-m", "jaeger_ai.cli.devtools", "--update"]
        return [py, "-m", "jaeger_ai.cli.run", "update", *rest]
    if cmd in ("--dev", "dev"):
        # Developer toolbox (dev TUI, dev-state app build/run, health,
        # stop/status) — lives IN the package since launch.py was removed.
        return [py, "-m", "jaeger_ai.cli.devtools", *rest]
    if cmd in ("--version", "version"):
        return [py, "-m", "jaeger_ai.cli", "--version"]
    if cmd in ("help", "--help", "-h"):
        return [py, "-m", "jaeger_ai.cli", "--help"]
    # bare, --instance, --voice, a one-shot prompt, … → run the agent
    return [py, "-m", "jaeger_ai.cli.run", *argv]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = _route(argv, sys.executable)
    os.execv(cmd[0], cmd)        # replaces this process — never returns
    return 0                     # unreachable; keeps type-checkers happy


if __name__ == "__main__":
    raise SystemExit(main())
