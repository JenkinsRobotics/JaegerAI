#!/usr/bin/env python3
"""Restart-on-crash supervisor for the agent process.

For a robot left running unattended, segfaults inside llama-cpp / Metal
shouldn't kill the assistant. This supervisor wraps any agent command and
restarts the child with exponential backoff on non-zero exit.

Usage:
    python supervisor.py -- python -m python_jaeger.plugins.voice_loop
    python supervisor.py --max-restarts 50 -- python main.py python_pydantic_ai

Exits 0 only when the child exits 0 voluntarily (clean shutdown). Exits 1
if `--max-restarts` is exhausted. Ctrl-C in the supervisor forwards SIGTERM
to the child and exits with the child's signal.

Design:
  - Backoff doubles each successive crash, capped at 60 s.
  - Backoff resets after a run that stayed up for > `--good-run-s` seconds.
  - Crash details (exit code, last 80 lines of stderr) get appended to
    `logs/supervisor.crash.log`.
"""

from __future__ import annotations

import argparse
import collections
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CRASH_LOG = PROJECT_ROOT / "logs" / "supervisor.crash.log"


def _record_crash(crash_log: Path, exit_code: int, tail: list[str]) -> None:
    crash_log.parent.mkdir(parents=True, exist_ok=True)
    with crash_log.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {datetime.now(timezone.utc).isoformat(timespec='seconds')} exit={exit_code} ---\n")
        for line in tail:
            fh.write(line if line.endswith("\n") else line + "\n")
        fh.write("\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-restarts", type=int, default=20,
                   help="Give up after this many consecutive crashes (default: 20).")
    p.add_argument("--good-run-s", type=float, default=60.0,
                   help="A run lasting this long resets the backoff counter.")
    p.add_argument("--initial-backoff-s", type=float, default=1.0)
    p.add_argument("--max-backoff-s", type=float, default=60.0)
    p.add_argument("--crash-log", type=Path, default=DEFAULT_CRASH_LOG)
    p.add_argument("--tail-lines", type=int, default=80,
                   help="How many lines of stderr to capture in the crash log.")
    p.add_argument("child", nargs=argparse.REMAINDER,
                   help="The command to supervise (after `--`).")
    args = p.parse_args()

    if not args.child:
        print("error: missing child command — pass it after `--`", file=sys.stderr)
        return 2
    # argparse REMAINDER includes the leading `--` if the caller used one. Strip it.
    cmd = list(args.child)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("error: empty child command", file=sys.stderr)
        return 2

    crashes = 0
    backoff = args.initial_backoff_s

    while True:
        started = time.perf_counter()
        print(f"[supervisor] starting {cmd!r} (crash #{crashes})", flush=True)
        # We stream stdout straight through, but tail stderr so we can include
        # context in the crash log without losing the live view.
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )
        tail: collections.deque[str] = collections.deque(maxlen=args.tail_lines)
        try:
            assert proc.stderr is not None
            for line in iter(proc.stderr.readline, ""):
                sys.stderr.write(line)
                sys.stderr.flush()
                tail.append(line)
            exit_code = proc.wait()
        except KeyboardInterrupt:
            print("\n[supervisor] Ctrl-C — forwarding to child", flush=True)
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 130  # 128 + SIGINT(2)

        ran_s = time.perf_counter() - started
        if exit_code == 0:
            print(f"[supervisor] child exited cleanly after {ran_s:.1f}s — done", flush=True)
            return 0

        _record_crash(args.crash_log, exit_code, list(tail))
        crashes += 1
        if ran_s > args.good_run_s:
            print(f"[supervisor] child ran {ran_s:.0f}s before crashing — resetting backoff", flush=True)
            crashes = 1
            backoff = args.initial_backoff_s

        if crashes >= args.max_restarts:
            print(f"[supervisor] {crashes} consecutive crashes — giving up", flush=True)
            return 1

        sleep_s = min(args.max_backoff_s, backoff)
        print(f"[supervisor] child crashed (exit={exit_code}) — sleeping {sleep_s:.1f}s then restarting", flush=True)
        time.sleep(sleep_s)
        backoff = min(args.max_backoff_s, backoff * 2)


if __name__ == "__main__":
    raise SystemExit(main())
