"""Mid-tool interrupt signalling for long-running tools.

JROS runs the pydantic-ai agent loop (``agent.iter()``). The loop already
honours a turn-scoped cancel ``Event`` — but only *between* nodes (see
:func:`jaeger_os.main._run_via_iter`). A tool that has already started —
a 60-second ``run_shell``, a slow ``web_fetch``, a vision-model load —
runs to completion before the loop gets another chance to look. The user
can interrupt the agent's *thinking* but not its *doing*.

This module closes that gap. It exposes one process-wide turn-interrupt
flag that a long-running tool can poll *while it works* and bail out of
early.

Design — one Event, no second source of truth
----------------------------------------------
:func:`begin_scope` returns the module-level :class:`threading.Event`,
and :func:`jaeger_os.main.begin_turn_cancel_scope` hands that very object
back as the turn's ``cancel_event``. So the flag the TUI sets to cancel a
turn, the flag ``_run_via_iter`` checks between nodes, and the flag a
tool polls mid-execution are all the *same* Event. Nothing can drift.

The flag is process-wide rather than per-thread (unlike hermes's
``tools/interrupt.py``). JROS serialises turns through
``_pipeline['llm_lock']`` and delegate sub-agents run *nested inside* the
parent turn — so "one user turn at a time" holds, and cancelling that
turn should stop its tools and its delegates' tools alike. A process-wide
flag is both correct here and immune to the thread-identity bookkeeping a
per-thread design needs (pydantic-ai dispatches sync tools onto anonymous
worker threads the loop never names).

Usage in a long-running tool
----------------------------
For a subprocess, use :func:`run_interruptible` as a drop-in for
``subprocess.run`` — it kills the child when the turn is cancelled::

    from jaeger_os.tool_interrupt import run_interruptible
    from jaeger_os.tool_interrupt import ToolInterrupted
    try:
        proc = run_interruptible(cmd, timeout=60, cwd=scratch)
    except ToolInterrupted as exc:
        return {"ok": False, "interrupted": True, "stdout": exc.stdout}

For a Python-side loop (chunked download, polling), check the flag
directly::

    from jaeger_os.tool_interrupt import is_interrupted
    for chunk in stream:
        if is_interrupted():
            break
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ToolInterrupted",
    "begin_scope",
    "clear_interrupt",
    "get_event",
    "is_interrupted",
    "raise_if_interrupted",
    "request_interrupt",
    "run_interruptible",
]


class ToolInterrupted(Exception):
    """Raised by a long-running tool when the turn is cancelled mid-call.

    Carries whatever partial output the tool had captured before it was
    stopped, so the caller can still surface it instead of discarding it.
    """

    def __init__(
        self,
        message: str = "tool interrupted by user",
        *,
        stdout: str | bytes = "",
        stderr: str | bytes = "",
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


# The single turn-interrupt flag. Module-level on purpose — see the
# module docstring. Starts clear; one turn at a time owns it.
_interrupt = threading.Event()


def begin_scope() -> threading.Event:
    """Open a fresh interrupt scope for a new turn; return the shared Event.

    Clears any stale interrupt first so a cancel left over from a prior
    turn cannot leak into this one. :func:`jaeger_os.main.begin_turn_cancel_scope`
    calls this and reuses the returned Event as the turn's cancel scope,
    which is what unifies the cancel flag and the tool-interrupt flag.
    """
    _interrupt.clear()
    return _interrupt


def get_event() -> threading.Event:
    """Return the shared turn-interrupt Event without clearing it."""
    return _interrupt


def request_interrupt() -> None:
    """Signal that the current turn should stop. Safe from any thread."""
    _interrupt.set()


def clear_interrupt() -> None:
    """Clear the interrupt flag (also done by :func:`begin_scope`)."""
    _interrupt.clear()


def is_interrupted() -> bool:
    """True when the current turn has been asked to stop.

    Safe to call from any thread, including a tool worker thread. A tool
    polls this in its work loop and bails out cooperatively.
    """
    return _interrupt.is_set()


def raise_if_interrupted() -> None:
    """Raise :class:`ToolInterrupted` if the current turn was cancelled."""
    if _interrupt.is_set():
        raise ToolInterrupted()


def _signal_tree(proc: subprocess.Popen, sig: int) -> None:
    """Send ``sig`` to the child's whole process GROUP, falling back to the
    child alone.

    Signalling only the direct child is not enough. ``run_shell`` runs
    ``/bin/sh -c "<cmd>"``, and whether the shell *execs* the final command
    (replacing itself, so the child IS the command) or *forks* it is an
    implementation detail that differs between shells — macOS's bash execs,
    Linux's dash forks. When it forks, terminating the shell leaves the
    grandchild alive still holding the write end of our stdout/stderr pipes,
    so the drain below blocks until that grandchild exits on its own. A
    ``run_shell("sleep 10")`` interrupted after 0.3s took the full 10
    seconds to return. Popen sets ``start_new_session=True``, so the child
    leads its own process group and one killpg reaches every descendant.
    """
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        # Group already gone, or we never got our own session — the direct
        # child is still worth signalling.
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


def _drain(proc: subprocess.Popen, *, text: bool) -> tuple[Any, Any]:  # noqa: ANN401
    """Terminate ``proc`` (and everything it spawned) and collect its output."""
    empty: Any = "" if text else b""
    try:
        _signal_tree(proc, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            _signal_tree(proc, signal.SIGKILL)
            out, err = proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        # A grandchild we could not reach still holds the pipes. Do not block
        # the turn on it — the caller wants OUT, now.
        return empty, empty
    except Exception:  # noqa: BLE001 — best-effort cleanup, never re-raise
        return empty, empty
    return out or empty, err or empty


def run_interruptible(
    cmd: Sequence[str],
    *,
    timeout: float,
    text: bool = True,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    poll_interval: float = 0.2,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` replacement that aborts when the turn is interrupted.

    Behaves like ``subprocess.run(cmd, capture_output=True, timeout=timeout,
    text=text, cwd=cwd, env=env)``:

      * returns a :class:`subprocess.CompletedProcess` on normal exit;
      * raises :class:`subprocess.TimeoutExpired` when ``timeout`` elapses.

    Additionally, every ``poll_interval`` seconds it checks
    :func:`is_interrupted`; on an interrupt it terminates (then kills) the
    child and raises :class:`ToolInterrupted` carrying the partial output.
    Interrupt latency is therefore bounded by ``poll_interval``.
    """
    proc = subprocess.Popen(  # noqa: S603 — argv list, caller-controlled
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        # Give the child its own process group so an interrupt can reach the
        # whole tree with one killpg — see _signal_tree.
        start_new_session=True,
    )
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            out, err = proc.communicate(timeout=poll_interval)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            # Child still running — decide whether to keep waiting.
            if is_interrupted():
                out, err = _drain(proc, text=text)
                raise ToolInterrupted(stdout=out, stderr=err) from None
            if time.monotonic() >= deadline:
                out, err = _drain(proc, text=text)
                raise subprocess.TimeoutExpired(
                    cmd, timeout, output=out, stderr=err,
                ) from None
