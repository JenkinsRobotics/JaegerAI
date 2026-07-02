"""Remote-execution tools — running commands on other hosts.

Today this file has one tool: ``ssh_exec(host, command, timeout_s)``.
It's a thin wrapper around the local ``ssh`` binary — we shell out
instead of using ``paramiko`` / ``asyncssh`` for one reason: ``ssh(1)``
already knows how to read ``~/.ssh/config``, walk the user's keychain,
honour ``known_hosts``, forward the agent, and respect ``ControlMaster``.
A pure-Python client would reimplement all of that and never quite match.

Scope is deliberately small. No file transfer, no streaming, no
host-allowlist — those are separate features with separate security
shapes and we'll add them when there's a concrete need. The agent gets:

  ssh_exec("host", "uptime") -> {ok, exit_code, stdout, stderr, ...}

Safety: tier-4 (PRIVILEGED) just like ``run_shell``. Every call audits
*before* the subprocess starts, so the record exists even if the SSH
process never returns. Same hardline-guard wraps as run_shell, applied
to the remote command string — a fork bomb is a fork bomb whether it
runs locally or one hop away.
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from jaeger_os.core.context import _audit, _require_layout
from jaeger_os.core.safety.command_guard import hardline_guard
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.runtime.tool_interrupt import ToolInterrupted, run_interruptible


# ssh's destination grammar is ``[user@]host[:port]`` plus a handful of
# aliases (``ssh://...`` URIs, ``Host`` config nicknames). We don't try
# to validate the full grammar — ssh will reject what it doesn't like.
# But we DO reject anything that looks like it carries shell metachars
# or leading dashes, because both can smuggle ssh CLI flags or shell
# escapes into the argv we build.
_BAD_HOST_CHARS = re.compile(r"[\s;&|`$()<>\"'\\]")


def _validate_host(host: str) -> str:
    """Strip and sanity-check the destination. Raises ValueError on
    anything dangerous; returns the cleaned string."""
    cleaned = (host or "").strip()
    if not cleaned:
        raise ValueError("empty host")
    # A leading dash would make ssh parse the host as a flag (the same
    # class of bug that bit ``--`` arg parsers in the early 2010s).
    if cleaned.startswith("-"):
        raise ValueError(f"host cannot start with '-': {cleaned!r}")
    if _BAD_HOST_CHARS.search(cleaned):
        raise ValueError(
            f"host contains shell metacharacters: {cleaned!r}. "
            "Use only [user@]host[:port] or a Host alias from ~/.ssh/config."
        )
    return cleaned


@hardline_guard("command")
@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="ssh",
    operation="ssh_exec",
    summary="execute a command on a remote host via ssh",
)
def ssh_exec(host: str, command: str, timeout_s: float = 60.0) -> dict[str, Any]:
    """Run ``command`` on ``host`` over SSH. Returns
    ``{ok, host, command, exit_code, stdout, stderr, elapsed_s, timed_out, interrupted}``.

    The remote command is passed as a single argv element after ``--``,
    so the LOCAL shell does not parse it. The REMOTE side will still run
    it through the remote shell — same as ``ssh host '<command>'`` from
    a terminal. If you want raw exec without a remote shell, that's a
    different ssh invocation and a different tool.

    ``host`` follows ssh's destination grammar — ``[user@]host[:port]``
    or any ``Host`` alias the local ``~/.ssh/config`` defines. Auth uses
    the local user's ssh keychain + agent — we never prompt for a
    password, and ``BatchMode=yes`` is forced so a missing key fails fast
    instead of hanging on a prompt the agent can't answer.

    ``timeout_s`` covers the whole connection + remote work. We also set
    ``ConnectTimeout=10`` so a dead host fails in ~10s rather than the
    OS default ~75s.
    """
    try:
        dest = _validate_host(host)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "host": host}

    cleaned = (command or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty command", "host": dest}

    timeout = max(1.0, min(float(timeout_s or 60.0), 600.0))

    # Audit BEFORE we shell out — if the network hangs, we still have a
    # record that the agent attempted this. Mirrors run_shell's pattern.
    try:
        _require_layout()
        _audit("ssh_exec", {
            "host": dest,
            "command": cleaned[:500],
            "timeout_s": timeout,
        })
    except Exception:  # noqa: BLE001 — audit failure must not block the call
        pass

    # Build argv. -o flags pin behaviour so the tool's contract doesn't
    # silently change based on the user's ssh_config:
    #   BatchMode=yes        — never prompt for a password
    #   ConnectTimeout=10    — fail fast on unreachable hosts
    #   StrictHostKeyChecking=accept-new — first-time hosts get added,
    #                          but a CHANGED key still aborts (MITM guard)
    # ``--`` ends ssh's own flag parsing, so the remote command can begin
    # with a dash without confusing the local ssh binary.
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        "--",
        dest,
        cleaned,
    ]

    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    interrupted = False
    stdout = stderr = ""
    exit_code = -1
    try:
        proc = run_interruptible(argv, timeout=timeout)
        stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = -1
        stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                  else (exc.stdout or "")) or ""
        stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                  else (exc.stderr or "")) or ""
    except ToolInterrupted as exc:
        # Turn was cancelled mid-call — the ssh child has been killed.
        # exit_code 130 mirrors the run_shell convention so callers can
        # treat both as "user-cancelled".
        interrupted = True
        exit_code = 130
        stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                  else (exc.stdout or "")) or ""
        stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                  else (exc.stderr or "")) or ""
    except FileNotFoundError:
        # No ``ssh`` on PATH. Surface this clearly rather than as an
        # opaque OSError — the most likely deployment-time mistake.
        return {
            "ok": False,
            "error": "ssh binary not found on PATH",
            "host": dest, "command": cleaned,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "host": dest, "command": cleaned,
        }

    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out and not interrupted,
        "host": dest,
        "command": cleaned,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
        "interrupted": interrupted,
    }
