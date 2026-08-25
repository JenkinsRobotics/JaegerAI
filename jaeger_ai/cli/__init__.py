"""Operator-facing CLI — ``jaeger <subcommand>``.

Operator-locked principle (2026-06-08): every operation the Swift
GUI can do is reachable from the terminal first.  GUI is a VIEW;
CLI is the API.  This package is the API layer.

Subcommands:
  avatar        render an animated demo of Lilith's face + open it
  skills        view the skill tree + per-skill detail
  instances     list / show / switch the active instance
  personality   view + adjust the active persona's stats
  status        runtime snapshot
  roadmap       view current roadmap progress
  prompt        inspect the system prompt the LLM receives (per fragment)
  config        view effective settings + defaults + descriptions
  runtime       inspect + select inference engines (the Runtime panel)

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
        avatar_cmd,
        config_cmd,
        personality_cmd,
        prompt_cmd,
        roadmap_cmd,
        runtime_cmd,
        skills_cmd,
        status_cmd,
    )

    from jaeger_ai import __version__

    # The subcommands below are argparse subparsers. A SECOND set of
    # commands is dispatched earlier, by ``cli.entry._route``, which
    # re-execs a different module for each — so argparse never sees them
    # and they cannot be registered here without breaking that routing.
    # They were therefore invisible in --help: `jaeger doctor` worked, and
    # the release checklist told operators to run it, but nothing short of
    # reading entry.py revealed it existed (field blocker #7). List them in
    # the epilog so every routable command is discoverable from one place.
    # ``test_help_discoverability`` fails if a route is added without a
    # line here.
    epilog = (
        "other commands (dispatched before this console):\n"
        "  setup       run first-run onboarding (GUI; `setup tui` forces terminal)\n"
        "  doctor      check dependencies, permissions, and install health\n"
        "  update      update JaegerAI in place\n"
        "  bridge      run the NDJSON stdio bridge the desktop app speaks\n"
        "  mcp         run the MCP server\n"
        "  dev         developer toolbox (dev TUI, build/run, health, stop)\n"
        "\nrun `jaeger <command> --help` for a command's own options."
    )

    parser = argparse.ArgumentParser(
        prog="jaeger",
        description=(
            "JaegerAI operator console.  Every subcommand here is also "
            "reachable from the GUI — terminal-first by design."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"jaeger-ai {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        metavar="<subcommand>",
    )
    avatar_cmd.register(subparsers)
    skills_cmd.register(subparsers)
    personality_cmd.register(subparsers)
    status_cmd.register(subparsers)
    roadmap_cmd.register(subparsers)
    prompt_cmd.register(subparsers)
    config_cmd.register(subparsers)
    runtime_cmd.register(subparsers)

    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help()
        return 0
    handler = args._handler
    return handler(args) or 0
