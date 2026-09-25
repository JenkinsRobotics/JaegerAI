"""Persistent command sessions: start a process under a PTY, then read from it
and type into it across tool calls (Codex's ``exec_command`` / ``write_stdin``).

``terminal`` runs a command to completion and returns. That cannot drive a dev
server, a REPL, a build that asks a question, or a test run that takes longer
than one call. Here a command keeps running; each call waits a bounded time for
new output and returns it, plus a ``session_id`` while the process is alive.

Safety is the same as ``terminal``: every start and every keystroke batch passes
the hardline guard and the PRIVILEGED permission tier, and starts are audited.
Reading output with no input (``write_stdin`` with empty ``chars``) sends nothing
to the process, so it needs no approval.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid
from typing import Any

from jaeger_agent.util.tool_interrupt import is_interrupted
from jaeger_agent.core.workspace import _audit, get_project_root
from jaeger_os.core.safety.command_guard import hardline_guard
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

MAX_SESSIONS = 8
IDLE_TIMEOUT_S = 30 * 60
MAX_BUFFER = 1_000_000          # bytes kept per session; oldest dropped past this
MAX_RETURN_CHARS = 16_000       # per call: head + tail kept, middle elided
MAX_YIELD_S = 60.0
QUIET_S = 0.25                  # return early once output arrived and went quiet

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def clean_output(raw: bytes) -> str:
    """Terminal bytes as readable text: no escape sequences, no carriage-return redraws."""
    text = _ANSI.sub("", raw.decode("utf-8", errors="replace")).replace("\r\n", "\n")
    # A bare carriage return redraws the line, so the last non-empty segment is what
    # is on screen; a trailing \r with nothing after it erases nothing.
    return "\n".join(
        next((part for part in reversed(line.split("\r")) if part), "") for line in text.split("\n")
    )


def elide(text: str, limit: int = MAX_RETURN_CHARS) -> tuple[str, int]:
    """Keep the head and tail of long output (build logs fail at the end, start at the top)."""
    if len(text) <= limit:
        return text, 0
    half = limit // 2
    omitted = len(text) - limit
    return f"{text[:half]}\n…[{omitted} characters omitted]…\n{text[-half:]}", omitted


# Make the PTY the child's *controlling terminal* so Ctrl-C, Ctrl-Z and job control
# behave as in a real terminal. Done in a fresh interpreter, not ``preexec_fn``,
# because forking a multi-threaded process (the Gateway) and running Python code
# before exec can deadlock on locks another thread held at fork time.
_LAUNCHER = (
    "import os, sys, fcntl, termios\n"
    "os.setsid()\n"
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"
    "os.execv('/bin/sh', ['/bin/sh', '-c', sys.argv[1]])\n"
)


class PtySession:
    def __init__(self, command: str, cwd: str, env: dict[str, str], scratch: str | None):
        self.command = command
        self.started = time.monotonic()
        self.last_used = self.started
        self._scratch = scratch
        self._buffer = bytearray()
        self._dropped = 0
        self._lock = threading.Lock()
        self._eof = threading.Event()
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-S", "-E", "-c", _LAUNCHER, command],
                stdin=slave, stdout=slave, stderr=slave,
                cwd=cwd, env=env, close_fds=True,
            )
        except Exception:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self._master = master
        self._reader = threading.Thread(target=self._pump, daemon=True, name="pty-reader")
        self._reader.start()

    def _pump(self) -> None:
        while True:
            try:
                ready, _, _ = select.select([self._master], [], [], 0.2)
                if not ready:
                    if self.proc.poll() is not None:
                        # The child is gone; drain what is left, then stop.
                        ready, _, _ = select.select([self._master], [], [], 0.05)
                        if not ready:
                            break
                    else:
                        continue
                chunk = os.read(self._master, 65536)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                raise
            if not chunk:
                break
            with self._lock:
                self._buffer += chunk
                if len(self._buffer) > MAX_BUFFER:
                    cut = len(self._buffer) - MAX_BUFFER
                    del self._buffer[:cut]
                    self._dropped += cut
        self._eof.set()

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def _take(self) -> bytes:
        with self._lock:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

    def _pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    def read(self, yield_s: float) -> dict[str, Any]:
        """Wait up to ``yield_s`` for output; return early when the process exits,
        the turn is cancelled, or output arrived and has gone quiet."""
        self.last_used = time.monotonic()
        deadline = time.monotonic() + max(0.0, min(yield_s, MAX_YIELD_S))
        quiet_since: float | None = None
        seen = self._pending()
        interrupted = False
        while time.monotonic() < deadline:
            if not self.running and self._eof.is_set():
                break
            if is_interrupted():
                interrupted = True
                break
            now = self._pending()
            if now != seen:
                seen, quiet_since = now, time.monotonic()
            elif now and quiet_since and time.monotonic() - quiet_since >= QUIET_S:
                break
            time.sleep(0.03)
        if not self.running:
            self._eof.wait(0.5)
        text, omitted = elide(clean_output(self._take()))
        with self._lock:
            dropped, self._dropped = self._dropped, 0
        result: dict[str, Any] = {"output": text, "wall_time_s": round(time.monotonic() - self.started, 2)}
        if omitted or dropped:
            result["omitted_chars"] = omitted + dropped
        if interrupted:
            result["interrupted"] = True
        if not self.running:
            result["exit_code"] = self.proc.returncode
        return result

    def write(self, chars: str) -> None:
        os.write(self._master, chars.encode("utf-8"))
        self.last_used = time.monotonic()

    def kill(self) -> None:
        if self.running:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                self.proc.wait(timeout=2)
        self.close()

    def close(self) -> None:
        try:
            os.close(self._master)
        except OSError:
            pass
        if self._scratch:
            shutil.rmtree(self._scratch, ignore_errors=True)
            self._scratch = None


class PtyManager:
    """Registry of live sessions. One per process; ids are random and unguessable."""

    def __init__(self) -> None:
        self._sessions: dict[str, PtySession] = {}
        self._lock = threading.Lock()

    def _reap(self) -> None:
        now = time.monotonic()
        for sid, session in list(self._sessions.items()):
            if now - session.last_used > IDLE_TIMEOUT_S or (not session.running and session._pending() == 0):
                self._sessions.pop(sid, None)
                session.kill()

    def start(self, command: str, *, cwd: str | None, yield_s: float) -> dict[str, Any]:
        with self._lock:
            self._reap()
            if len(self._sessions) >= MAX_SESSIONS:
                return {"ok": False, "error": f"too many live command sessions ({MAX_SESSIONS}); "
                        "finish or kill one with kill_command first",
                        "sessions": sorted(self._sessions)}
        scratch = None
        if cwd is None:
            scratch = cwd = tempfile.mkdtemp(prefix="jaeger_pty_")
        elif not os.path.isdir(cwd):
            return {"ok": False, "error": f"workdir does not exist: {cwd}"}
        env = {**os.environ, "TERM": "xterm-256color", "PAGER": "cat", "GIT_PAGER": "cat"}
        try:
            session = PtySession(command, cwd, env, scratch)
        except Exception as exc:  # noqa: BLE001
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return self._finish(uuid.uuid4().hex[:10], session, session.read(yield_s))

    def _finish(self, sid: str, session: PtySession, result: dict[str, Any]) -> dict[str, Any]:
        result["ok"] = result.get("exit_code", 0) == 0
        if session.running:
            with self._lock:
                self._sessions[sid] = session
            result["session_id"] = sid
        else:
            with self._lock:
                self._sessions.pop(sid, None)
            session.close()
        return result

    def get(self, sid: str) -> PtySession | None:
        with self._lock:
            return self._sessions.get(str(sid))

    def poll(self, sid: str, yield_s: float) -> dict[str, Any]:
        session = self.get(sid)
        if session is None:
            return {"ok": False, "error": f"no live command session {sid!r}; it may have finished or been killed"}
        return self._finish(str(sid), session, session.read(yield_s))

    def send(self, sid: str, chars: str, yield_s: float) -> dict[str, Any]:
        session = self.get(sid)
        if session is None:
            return {"ok": False, "error": f"no live command session {sid!r}; it may have finished or been killed"}
        if not session.running:
            return self._finish(str(sid), session, session.read(0.0))
        try:
            session.write(chars)
        except OSError as exc:
            return {"ok": False, "error": f"could not write to the session: {exc}"}
        return self._finish(str(sid), session, session.read(yield_s))

    def kill(self, sid: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.pop(str(sid), None)
        if session is None:
            return {"ok": False, "error": f"no live command session {sid!r}"}
        tail = clean_output(session._take())
        session.kill()
        return {"ok": True, "killed": str(sid), "output": elide(tail)[0]}

    def kill_all(self) -> int:
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for session in sessions:
            session.kill()
        return len(sessions)

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions)


_manager = PtyManager()


def _yield_seconds(yield_time_ms: Any, default_ms: int) -> float:
    try:
        return max(0.0, min(float(yield_time_ms), MAX_YIELD_S * 1000)) / 1000.0
    except (TypeError, ValueError):
        return default_ms / 1000.0


# ── agent-facing tools (gated exactly like ``terminal``) ────────────────────


@hardline_guard("cmd")
@requires_tier(PermissionTier.PRIVILEGED, skill="shell", operation="exec_command",
               summary="start a long-running command session")
def start_session(*, cmd: str, workdir: str | None, yield_time_ms: int) -> dict[str, Any]:
    command = (cmd or "").strip()
    if not command:
        return {"ok": False, "error": "empty command"}
    project = get_project_root()
    cwd = workdir or (str(project) if project is not None else None)
    try:
        _audit("exec_command", {"command": command[:500], "cwd": cwd or "(scratch tempdir)"})
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "audit log unavailable", "command": command}
    return {**_manager.start(command, cwd=cwd, yield_s=_yield_seconds(yield_time_ms, 1000)),
            "command": command}

@hardline_guard("chars")
@requires_tier(PermissionTier.PRIVILEGED, skill="shell", operation="write_stdin",
               summary="type into a running command session")
def type_into(*, chars: str, session_id: str, yield_time_ms: int) -> dict[str, Any]:
    try:
        _audit("write_stdin", {"session_id": str(session_id), "chars": chars[:200]})
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "audit log unavailable"}
    return _manager.send(str(session_id), chars, _yield_seconds(yield_time_ms, 1000))

@register_tool_from_function(name="exec_command", side_effect="external")
def _t_exec_command(cmd: str, workdir: str | None = None, yield_time_ms: int = 1000) -> dict:
    """Start a shell command that may keep running — a dev server, a test
    watcher, a REPL, an installer that asks questions, a build longer than
    one call. Returns the output produced within `yield_time_ms`. If the
    command is still running you get a `session_id`: read more with
    `write_stdin(session_id)` (empty chars), type input with
    `write_stdin(session_id, chars="...\\n")`, or stop it with
    `kill_command`. If it finished you get `exit_code` instead. Runs in the
    selected project. For a quick one-shot command use `terminal`."""
    return start_session(cmd=cmd, workdir=workdir, yield_time_ms=yield_time_ms)

@register_tool_from_function(name="write_stdin", side_effect="external")
def _t_write_stdin(session_id: str, chars: str = "", yield_time_ms: int = 1000) -> dict:
    """Send keystrokes to a running `exec_command` session, or — with empty
    `chars` — just wait `yield_time_ms` and return new output (polling
    needs no approval). Include "\\n" to press Enter; "\\u0003" sends Ctrl-C
    and "\\u0004" Ctrl-D. Returns the new output, and `exit_code` once the
    process has ended."""
    if not chars:
        return _manager.poll(str(session_id), _yield_seconds(yield_time_ms, 1000))
    return type_into(chars=chars, session_id=session_id, yield_time_ms=yield_time_ms)

@register_tool_from_function(name="kill_command", side_effect="external")
def _t_kill_command(session_id: str) -> dict:
    """Stop a running `exec_command` session and return its remaining output."""
    return _manager.kill(str(session_id))

