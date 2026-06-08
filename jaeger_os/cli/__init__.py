"""Operator-facing CLI — ``jaeger <subcommand>``.

Operator-locked principle (2026-06-08): every operation the Swift
GUI can do is reachable from the terminal first.  GUI is a VIEW;
CLI is the API.  This package is the API layer.

Subcommands:
  skills        view the skill tree + per-skill detail
  instances     list / show / switch the active instance
  personality   view + adjust the active persona's stats
  status        runtime snapshot
  roadmap       view current roadmap progress

Each subcommand has:
  - A ``register(subparsers)`` function that adds argparse args
  - A ``run(args)`` function that does the work and exits

Entry point:
  ``jaeger`` shell shim → ``python -m jaeger_os.cli``

Headless-safe: nothing here imports the LLM client or the audio
plugins — operators can inspect instance state without booting the
brain.
"""

from __future__ import annotations

__all__ = [
    "main",
]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Dispatched from ``python -m jaeger_os.cli``."""
    import argparse
    import sys

    from . import (
        instances_cmd,
        personality_cmd,
        roadmap_cmd,
        skills_cmd,
        status_cmd,
    )

    parser = argparse.ArgumentParser(
        prog="jaeger",
        description=(
            "JROS operator console.  Every subcommand here is also "
            "reachable from the GUI — terminal-first by design."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        metavar="<subcommand>",
    )
    skills_cmd.register(subparsers)
    instances_cmd.register(subparsers)
    personality_cmd.register(subparsers)
    status_cmd.register(subparsers)
    roadmap_cmd.register(subparsers)

    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help()
        return 0
    handler = args._handler
    return handler(args) or 0
