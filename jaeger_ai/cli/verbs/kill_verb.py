"""``jaeger kill`` — force-stop every hung jaeger process.

``jaeger stop`` is the graceful path: it SIGTERMs the daemon, waits
for it to clean up, removes the lock + PID files. That works when
the agent loop is responsive.

This verb is the "everything is on fire" path: it SIGKILLs every
python process running ``jaeger_os`` and then sweeps stale lock
files out of every known instance dir, so the next ``jaeger`` boot
finds a clean slate.

When to use:
  * The TUI is hung on a Metal/llama.cpp prefill stall and Ctrl-C
    won't break out (the inner adapter call is uncancellable).
  * A daemon crashed and left ``run/jaeger.lock`` behind, blocking
    fresh starts with "instance is locked by pid X (still running)".
  * You started jaeger from a terminal you've since closed and can
    no longer reach with Ctrl-C.

Safe by design:
  * Matches processes by both ``-f python`` AND the module path
    ``jaeger_os`` — won't kill an unrelated python process that
    happens to mention the string in its argv.
  * Lock file cleanup only removes well-known names
    (``tui.pid``, ``daemon.pid``, ``jaeger.lock``) under any
    discovered ``<instance>/run/`` directory. Never touches anything
    outside ``~/.jaeger/`` and the dev sandbox.
  * Prints what it did so the user knows the blast radius.

Returns rc=0 even when nothing was killed (idempotent: running it
twice is harmless).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from jaeger_ai.core.instance.procshape import is_real_jaeger_command as _is_real_jaeger_command


_LOCK_FILENAMES: frozenset[str] = frozenset({
    "tui.pid",
    "daemon.pid",
    "jaeger.lock",
})


def _cmd_kill_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger kill", add_help=False,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="show what would be killed/cleaned but don't actually do it",
    )
    parser.add_argument(
        "--instance", default=None,
        help="only target this instance's processes/locks (default: all)",
    )
    parser.add_argument(
        "-h", "--help", action="store_true",
    )
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger kill [--dry-run] [--instance NAME]\n"
            "\n"
            "  --dry-run     list targets without killing or sweeping\n"
            "  --instance    only target one instance (default: every jaeger)\n"
            "\n"
            "Force-stops every python process running jaeger_os and clears\n"
            "stale lock/PID files. Idempotent. Safe to run when nothing is\n"
            "running.",
            file=sys.stderr,
        )
        return 0

    own_pid = os.getpid()
    targets = _find_jaeger_pids(exclude={own_pid})
    locks = _find_lock_files(instance=args.instance)

    if not targets and not locks:
        print("nothing to do — no jaeger processes, no stale locks")
        return 0

    if args.dry_run:
        if targets:
            print(f"would SIGKILL {len(targets)} process(es):")
            for pid, cmdline in targets:
                print(f"  pid={pid:<6}  {cmdline[:100]}")
        if locks:
            print(f"would remove {len(locks)} lock file(s):")
            for p in locks:
                print(f"  {p}")
        return 0

    # SIGTERM first (5s grace), then SIGKILL anything that didn't die.
    # A clean shutdown leaves less stale state, even when the user
    # asked for the nuclear option.
    killed: list[int] = []
    for pid, _ in targets:
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            continue  # already gone — fine
        except PermissionError:
            print(f"  (no permission to signal pid={pid})", file=sys.stderr)

    if killed:
        # Up to 2s of grace — most graceful shutdowns are sub-second;
        # a Metal-hung process won't honor SIGTERM anyway so the
        # SIGKILL pass below is what actually kills it.
        time.sleep(2.0)
        for pid in killed:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # already exited cleanly

    # Final sweep: anything that's still alive (a SIGKILL on macOS
    # can be racy when the process is mid-syscall in Metal/llama.cpp).
    still_alive = [pid for pid, _ in _find_jaeger_pids(exclude={own_pid})]
    if still_alive:
        time.sleep(1.0)
        for pid in still_alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    # Sweep lock/PID files. Do this AFTER signal delivery so a daemon
    # that was about to write its lock as part of shutdown finishes
    # first.
    removed: list[Path] = []
    for p in locks:
        try:
            p.unlink()
            removed.append(p)
        except OSError:
            pass

    # Report.
    if killed:
        print(f"killed {len(killed)} jaeger process(es): "
              f"pids={sorted(set(killed))}")
    if removed:
        print(f"removed {len(removed)} stale lock file(s):")
        for p in removed:
            print(f"  {p}")
    if not killed and not removed:
        print("nothing to do")
    return 0


def _find_jaeger_pids(
    *, exclude: set[int] | None = None,
) -> list[tuple[int, str]]:
    """Return ``[(pid, cmdline), ...]`` for every python process whose
    argv mentions ``jaeger_os``. Uses ``ps`` for portability — works
    on macOS + Linux without psutil.

    ``exclude`` is a set of PIDs to skip (e.g. our own PID, so the
    verb doesn't kill itself before finishing the sweep)."""
    exclude = exclude or set()
    try:
        out = subprocess.check_output(
            ["ps", "-Ao", "pid=,command="],
            text=True,
            timeout=5.0,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []
    found: list[tuple[int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_str, cmdline = line.split(None, 1)
            pid = int(pid_str)
        except (ValueError, IndexError):
            continue
        if pid in exclude:
            continue
        if not _is_real_jaeger_command(cmdline):
            continue
        found.append((pid, cmdline))
    return found


def _find_lock_files(*, instance: str | None = None) -> list[Path]:
    """Locate stale lock/PID files under every instance dir we know
    about (``<install_root>/.jaeger_os/instances/*/run/`` + the dev
    sandbox)."""
    roots: list[Path] = []

    # 0.2.6: instance state moved into the operator-state dir under
    # the install root.
    from jaeger_ai.core.instance.instance import user_instances_root
    home_instances = user_instances_root()
    if home_instances.exists():
        roots.append(home_instances)

    # Dev sandbox — JAEGER_INSTANCE_DIR points at a single instance
    # dir (not the parent), so we add it directly rather than as a
    # parent.
    dev_dir = os.environ.get("JAEGER_INSTANCE_DIR")
    if dev_dir:
        roots.append(Path(dev_dir))

    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        # If root is an instance dir (has ``run/``), check it directly;
        # otherwise iterate its children as instance dirs.
        candidates: list[Path] = []
        if (root / "run").exists():
            candidates.append(root)
        else:
            try:
                candidates.extend(p for p in root.iterdir() if p.is_dir())
            except OSError:
                continue
        for inst_dir in candidates:
            if instance is not None and inst_dir.name != instance:
                continue
            run_dir = inst_dir / "run"
            if not run_dir.is_dir():
                continue
            for name in _LOCK_FILENAMES:
                p = run_dir / name
                if p.exists() and p not in seen:
                    seen.add(p)
                    found.append(p)
    return sorted(found)


__all__ = ["_cmd_kill_argv"]
