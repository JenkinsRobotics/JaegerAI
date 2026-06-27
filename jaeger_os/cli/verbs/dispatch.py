"""``jaeger <verb>`` dispatch — the in-process CLI verb surface.

``main.py`` peels ``sys.argv[1]`` and calls :func:`dispatch` from here if
the first word is a known verb; otherwise it falls through to the existing
argparse + TUI/voice path so a bare ``jaeger`` keeps booting the in-process
TUI exactly as before.

History: these verbs lived under ``jaeger_os/daemon/`` while a multi-process
daemon split was planned. That architecture was dropped on 2026-06-14 (JROS
converged on fused mode — one process, TUI in foreground); the daemon-process
machinery (socket server/client/protocol, fork lifecycle, attach, the
daemon-attached ``rich_tui`` REPL) was deleted and the in-process verbs were
moved here. ``jaeger start``/``stop``/``status``/``restart``/``tray``/
``attach``/``rich-tui`` are gone with it.

What this module owns
---------------------
  - argv → verb mapping
  - exit codes (0 success, 1 unhealthy, 2 misuse)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


# Verbs that route to this module instead of the main TUI path. A bare
# ``jaeger`` (or any flag-first argv) is NOT here — it falls through to
# ``main.py``'s legacy path and boots the in-process TUI.
SUBCOMMANDS: frozenset[str] = frozenset({
    "bench",
    "agent", "setup", "instance", "migrate",
    "backup", "restore", "update", "reinstall", "uninstall", "autostart",
    "skill", "memory", "kill",
})


def is_daemon_subcommand(argv: Sequence[str]) -> bool:
    """``main.py`` calls this on ``sys.argv[1:]`` — True if the first word
    is one of our verbs. (Name kept for the historical call site in
    ``main.py``; these are plain in-process verbs, no daemon involved.)"""
    return len(argv) >= 1 and argv[0] in SUBCOMMANDS


def dispatch(argv: Sequence[str]) -> int:
    """Run the verb named by ``argv[0]``. Returns the exit code the CLI
    should hand back to the OS."""
    if not argv:
        _print_usage()
        return 2
    # ``bench`` has its own sub-verbs (run/timing/compare/history) and flags.
    if argv[0] == "bench":
        return _cmd_bench(list(argv[1:]))
    # Each verb below owns its own argparse, imported lazily so a single
    # verb never pays for the others' import cost.
    if argv[0] == "agent":
        from jaeger_os.cli.verbs.instance_verbs import _cmd_agent_argv
        return _cmd_agent_argv(list(argv[1:]))
    if argv[0] == "setup":
        from jaeger_os.cli.verbs.instance_verbs import _cmd_setup_argv
        return _cmd_setup_argv(list(argv[1:]))
    if argv[0] == "instance":
        from jaeger_os.cli.verbs.instance_verbs import _cmd_instance_argv
        return _cmd_instance_argv(list(argv[1:]))
    if argv[0] == "migrate":
        from jaeger_os.cli.verbs.instance_verbs import _cmd_migrate_argv
        return _cmd_migrate_argv(list(argv[1:]))
    if argv[0] == "backup":
        from jaeger_os.cli.verbs.backup_restore import _cmd_backup_argv
        return _cmd_backup_argv(list(argv[1:]))
    if argv[0] == "restore":
        from jaeger_os.cli.verbs.backup_restore import _cmd_restore_argv
        return _cmd_restore_argv(list(argv[1:]))
    if argv[0] == "update":
        from jaeger_os.cli.verbs.update_verb import _cmd_update_argv
        return _cmd_update_argv(list(argv[1:]))
    if argv[0] == "reinstall":
        from jaeger_os.cli.verbs.update_verb import _cmd_reinstall_argv
        return _cmd_reinstall_argv(list(argv[1:]))
    if argv[0] == "uninstall":
        from jaeger_os.cli.verbs.uninstall_verb import _cmd_uninstall_argv
        return _cmd_uninstall_argv(list(argv[1:]))
    if argv[0] == "autostart":
        from jaeger_os.cli.verbs.autostart_verb import _cmd_autostart_argv
        return _cmd_autostart_argv(list(argv[1:]))
    if argv[0] == "skill":
        from jaeger_os.cli.verbs.skill_verbs import _cmd_skill_argv
        return _cmd_skill_argv(list(argv[1:]))
    if argv[0] == "memory":
        from jaeger_os.cli.verbs.memory_verbs import _cmd_memory_argv
        return _cmd_memory_argv(list(argv[1:]))
    if argv[0] == "kill":
        from jaeger_os.cli.verbs.kill_verb import _cmd_kill_argv
        return _cmd_kill_argv(list(argv[1:]))
    # ``health`` was folded into ``jaeger doctor`` (one doctor — deps +
    # runtime probe). Removed 2026-06-20.
    _print_usage()
    return 2


def _cmd_bench(argv: list[str]) -> int:
    """``jaeger bench …`` — run the JROS benchmark suites.

      * ``jaeger bench run [--tags …] [--ids …] [--limit N]``
        Flat routing/multistep/multiturn/recovery corpus. Boots its own
        pipeline (cold) so the run reflects a fresh process.
      * ``jaeger bench timing`` — wall-clock-per-prompt timing suite.
      * ``jaeger bench compare`` — pick local GGUFs, bench each, write a
        comparison report.
      * ``jaeger bench history`` — rolling leaderboard across every run.
    """
    if not argv or argv[0] in ("-h", "--help"):
        _print_bench_usage()
        return 0 if argv else 2
    verb = argv[0]
    rest = argv[1:]
    repo = _repo_root()

    if verb == "run":
        # Forward every remaining flag verbatim — ``run_flat_bench.py``
        # owns the argument surface (``--tags`` / ``--ids`` / ``--limit``
        # / ``--no-warmup``); duplicating its argparse here would just
        # mean two places to update on a future flag.
        import subprocess
        script = repo / "dev/benchmark" / "run_flat_bench.py"
        if not script.is_file():
            print(f"bench script missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    if verb == "timing":
        import subprocess
        script = repo / "dev/benchmark" / "timing" / "bench.py"
        if not script.is_file():
            print(f"timing bench missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    if verb == "compare":
        from jaeger_os.cli.verbs.bench_compare_verb import _cmd_bench_compare_argv
        return _cmd_bench_compare_argv(rest)

    if verb == "history":
        from jaeger_os.cli.verbs.bench_history_verb import _cmd_bench_history_argv
        return _cmd_bench_history_argv(rest)

    print(f"unknown bench verb: {verb!r}", file=sys.stderr)
    _print_bench_usage()
    return 2


def _print_bench_usage() -> None:
    print(
        "usage: jaeger bench {run | timing | compare | history} "
        "[bench-specific args]\n"
        "\n"
        "  run     — flat routing/multistep/multiturn/recovery corpus\n"
        "  timing  — wall-clock per-prompt timing suite\n"
        "  compare — pick multiple models from a list, bench each,\n"
        "            write a comparison report (operator-driven)\n"
        "  history — rolling leaderboard across every model ever\n"
        "            benched on this machine (sweep + flat artifacts)\n"
        "\n"
        "  jaeger bench run --tags routing --limit 5\n"
        "  jaeger bench run --ids time_now,calc_sqrt\n"
        "  jaeger bench timing\n",
        file=sys.stderr,
    )


def _repo_root() -> Path:
    """The benchmark scripts live under ``<repo>/dev/benchmark/``. Walk up
    from this module until we find a ``dev/benchmark`` sibling; fall back to
    the install root (``jaeger_os/``'s parent) for unusual layouts."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "dev/benchmark").is_dir():
            return parent
    # jaeger_os/cli/verbs/dispatch.py → parents[3] == install root.
    return here.parents[3]


def _print_usage() -> None:
    print(
        "Usage: jaeger {bench|agent|migrate|backup|restore|update|"
        "reinstall|uninstall|autostart|skill|memory|kill|health} [args]\n"
        "\n"
        "  bench    Run a JROS benchmark — `jaeger bench run|timing|compare|history`.\n"
        "  agent    Create / manage agents — create | list | use | inspect |\n"
        "           delete | clear. (`setup` + `instance` remain as aliases.)\n"
        "  migrate  Run pending agent migrations.\n"
        "  backup   Archive an instance directory to a zip.\n"
        "  restore  Restore an instance from a backup zip.\n"
        "  update   Upgrade the framework and migrate stale instances.\n"
        "  reinstall Clean reinstall of the framework, keeping all agents.\n"
        "  uninstall Remove the framework; keep agents unless --purge.\n"
        "  autostart Run the unit's agent at boot/login — enable|disable|status.\n"
        "  skill    Manage skills — list / clone a bundled skill.\n"
        "  memory   Export or summarise an instance's memory store.\n"
        "  kill     Force-stop every jaeger process + sweep stale lock\n"
        "           files. Use when the TUI is hung on a Metal stall and\n"
        "           Ctrl-C won't break out. Idempotent.\n"
        "  health   Runtime substrate probe (post-boot diagnostics).\n"
        "           Pairs with ``--doctor`` which checks deps BEFORE boot.\n"
        "           ``--deep`` adds live agent-loop turns.\n"
        "\n"
        "Run ``jaeger`` with no subcommand to launch the in-process TUI.",
        file=sys.stderr,
    )


__all__ = ["SUBCOMMANDS", "dispatch", "is_daemon_subcommand"]


# ``python -m jaeger_os.cli.verbs.dispatch health`` — direct entry for
# scripts / smoke tests that want a verb without booting ``jaeger_os.main``.
if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(dispatch(sys.argv[1:]))
