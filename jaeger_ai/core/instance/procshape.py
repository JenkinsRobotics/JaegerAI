"""Process-shape check: is a PID actually a jaeger process?

Split out of ``cli/verbs/kill_verb.py`` (0.8.1) so the instance lock's
stale-holder detection and ``jaeger kill``'s safe process matching share
ONE definition of "jaeger-shaped" — they must never drift, or a lock
break and a kill sweep could disagree about the same PID. Uses ``ps``
for portability; no psutil dependency.
"""

from __future__ import annotations

import subprocess


def is_real_jaeger_command(cmdline: str) -> bool:
    """True when ``cmdline`` is an actual jaeger entry point.

    A naive ``'python' in cmd and 'jaeger_os' in cmd`` matches shells
    whose ``-c`` argument sources a snapshot that mentions either
    string — false positives we never want to trust (kill_verb) or
    treat as a live lock-holder (instance lock).

    The canonical jaeger commands we DO want:

      - ``... python -m jaeger_os ...``        (module form)
      - ``... python -m jaeger_os.<sub> ...``  (daemon/cli subcommands)
      - ``... python .../jaeger_os/__main__.py ...``
      - ``... bin/jaeger ...``                 (the venv script)

    Anything else (a shell, an editor, an unrelated process that
    happened to inherit a recycled PID) does not match, even if it
    mentions ``jaeger_os`` in argv text.
    """
    head = cmdline.split(None, 1)[0] if cmdline else ""
    head_name = head.rsplit("/", 1)[-1]
    if head_name in ("zsh", "bash", "sh", "fish", "dash"):
        return False
    if " -m jaeger_os" in cmdline:
        return True
    if "/jaeger_os/__main__.py" in cmdline:
        return True
    if head_name == "jaeger":
        return True
    if cmdline.endswith("/jaeger") or " /jaeger " in cmdline:
        return True
    return False


def pid_cmdline(pid: int, *, timeout_s: float = 2.0) -> str | None:
    """Best-effort ``ps -p PID -o command=`` lookup.

    Returns ``None`` when ``ps`` fails, times out, or the PID has no
    entry (already gone) — callers MUST treat ``None`` as "couldn't
    verify", never as "not jaeger": failing open here would let a
    transient ``ps`` hiccup break a lock that's actually still held.
    """
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True, timeout=timeout_s,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    out = out.strip()
    return out or None


__all__ = ["is_real_jaeger_command", "pid_cmdline"]
