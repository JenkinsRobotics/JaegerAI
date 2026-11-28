"""Bounded interactive PTY session manager for jaeger-tools (stdlib-only).

Supports interactive CLI prompts, REPLs, and background local dev servers while
enforcing:
- Strict session cap (`max_sessions`, default 4) and idle TTL auto-reaping.
- Dedicated background drain thread per PTY with bounded ring buffer (prevents deadlocks).
- Optional SandboxPort wrapping (macOS Seatbelt) and workspace-pinned working directory.
- Clean process-group teardown (`SIGTERM` -> `SIGKILL`) on `stop()` or `close_all()`.
"""

from __future__ import annotations

import errno
import os
import pty
import select
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jaeger_contracts import SandboxPort, SandboxProfile

__all__ = ["PtySessionError", "PtySessionManager"]


class PtySessionError(RuntimeError):
    """Raised on invalid PTY operations, capacity exhaustion, or unknown session IDs."""


@dataclass
class _PtyRecord:
    pty_id: str
    command: str
    cwd: Path
    proc: subprocess.Popen[bytes]
    master_fd: int
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    buffer: str = ""
    read_cursor: int = 0
    closed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader_thread: threading.Thread | None = None


class PtySessionManager:
    """Lifecycle-managed pool of interactive PTY sessions."""

    def __init__(
        self,
        workspace: Path,
        *,
        sandbox: SandboxPort | None = None,
        max_sessions: int = 4,
        idle_ttl_s: float = 600.0,
        max_buffer_chars: int = 65_536,
    ) -> None:
        self._workspace = Path(workspace).expanduser().resolve()
        self._sandbox = sandbox
        self._max_sessions = max(1, int(max_sessions))
        self._idle_ttl_s = max(5.0, float(idle_ttl_s))
        self._max_buffer_chars = max(4096, int(max_buffer_chars))
        self._lock = threading.RLock()
        self._sessions: dict[str, _PtyRecord] = {}

    def _resolve_cwd(self, cwd: str | None) -> Path:
        if not cwd or not str(cwd).strip():
            return self._workspace
        raw = Path(str(cwd)).expanduser()
        target = raw.resolve() if raw.is_absolute() else (self._workspace / raw).resolve()
        if target == self._workspace or self._workspace in target.parents:
            if not target.is_dir():
                raise PtySessionError(f"Working directory does not exist: {cwd!r}")
            return target
        raise PtySessionError(f"Working directory {cwd!r} escapes workspace {self._workspace}")

    def _reap_idle_locked(self) -> None:
        now = time.time()
        expired: list[str] = []
        for pid, rec in self._sessions.items():
            if (now - rec.last_activity) > self._idle_ttl_s:
                expired.append(pid)
        for pid in expired:
            rec = self._sessions.pop(pid, None)
            if rec is not None:
                self._terminate_record(rec)

    def _drain_loop(self, rec: _PtyRecord) -> None:
        fd = rec.master_fd
        while True:
            try:
                rlist, _, _ = select.select([fd], [], [], 0.15)
            except (OSError, ValueError):
                break
            if not rlist:
                if rec.closed or rec.proc.poll() is not None:
                    # Do one last non-blocking drain check before exiting.
                    try:
                        r2, _, _ = select.select([fd], [], [], 0.02)
                        if not r2:
                            break
                    except (OSError, ValueError):
                        break
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            with rec.lock:
                rec.buffer += text
                if len(rec.buffer) > self._max_buffer_chars:
                    overflow = len(rec.buffer) - self._max_buffer_chars
                    rec.buffer = rec.buffer[overflow:]
                    rec.read_cursor = max(0, rec.read_cursor - overflow)
                rec.last_activity = time.time()

    @staticmethod
    def _terminate_record(rec: _PtyRecord) -> None:
        rec.closed = True
        if rec.proc.poll() is None:
            try:
                os.killpg(rec.proc.pid, signal.SIGTERM)
            except OSError:
                try:
                    rec.proc.terminate()
                except OSError:
                    pass
            try:
                rec.proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(rec.proc.pid, signal.SIGKILL)
                except OSError:
                    try:
                        rec.proc.kill()
                    except OSError:
                        pass
                try:
                    rec.proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        try:
            os.close(rec.master_fd)
        except OSError:
            pass
        if rec.reader_thread is not None and rec.reader_thread.is_alive():
            rec.reader_thread.join(timeout=1.0)

    def _snapshot(self, rec: _PtyRecord, *, unread_only: bool = True, tail_chars: int = 8000) -> dict[str, Any]:
        rc = rec.proc.poll()
        with rec.lock:
            if unread_only:
                out = rec.buffer[rec.read_cursor :]
                rec.read_cursor = len(rec.buffer)
            else:
                out = rec.buffer[-tail_chars:]
        return {
            "pty_id": rec.pty_id,
            "pid": rec.proc.pid,
            "running": rc is None,
            "exit_code": rc,
            "output": out[-tail_chars:],
        }

    def start(
        self,
        command: str,
        *,
        cwd: str | None = None,
        initial_wait_s: float = 0.25,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        cmd = (command or "").strip()
        if not cmd:
            raise PtySessionError("command is required")
        work_dir = self._resolve_cwd(cwd)
        with self._lock:
            self._reap_idle_locked()
            active = [r for r in self._sessions.values() if r.proc.poll() is None]
            if len(active) >= self._max_sessions:
                raise PtySessionError(
                    f"Maximum active PTY sessions ({self._max_sessions}) reached; stop an existing session first."
                )

        argv: list[str] = ["/bin/sh", "-c", cmd]
        if self._sandbox is not None:
            profile = SandboxProfile(workspace=self._workspace, allow_network=bool(allow_network))
            spec = self._sandbox.prepare(argv, profile)
            argv = list(spec.argv)

        master_fd, slave_fd = pty.openpty()
        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(work_dir),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
                env=env,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        pty_id = f"pty_{uuid.uuid4().hex[:8]}"
        rec = _PtyRecord(pty_id=pty_id, command=cmd[:240], cwd=work_dir, proc=proc, master_fd=master_fd)
        t = threading.Thread(target=self._drain_loop, args=(rec,), name=f"jaeger-{pty_id}", daemon=True)
        rec.reader_thread = t
        t.start()
        with self._lock:
            self._sessions[pty_id] = rec

        wait_s = max(0.0, min(float(initial_wait_s), 5.0))
        if wait_s > 0:
            time.sleep(wait_s)
        return self._snapshot(rec, unread_only=True)

    def send(
        self,
        pty_id: str,
        data: str,
        *,
        enter: bool = True,
        wait_s: float = 0.25,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self._sessions.get(pty_id)
        if rec is None:
            raise PtySessionError(f"Unknown PTY session: {pty_id!r}")
        if rec.proc.poll() is not None:
            return self._snapshot(rec, unread_only=True)
        payload = str(data or "")
        if enter and not payload.endswith(("\n", "\r")):
            payload += "\n"
        try:
            os.write(rec.master_fd, payload.encode("utf-8"))
        except OSError as exc:
            raise PtySessionError(f"Failed writing to PTY {pty_id!r}: {exc}") from exc
        rec.last_activity = time.time()
        delay = max(0.0, min(float(wait_s), 5.0))
        if delay > 0:
            time.sleep(delay)
        return self._snapshot(rec, unread_only=True)

    def read(
        self,
        pty_id: str,
        *,
        wait_s: float = 0.1,
        tail_chars: int = 8000,
        full_tail: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self._sessions.get(pty_id)
        if rec is None:
            raise PtySessionError(f"Unknown PTY session: {pty_id!r}")
        delay = max(0.0, min(float(wait_s), 5.0))
        if delay > 0 and rec.proc.poll() is None:
            time.sleep(delay)
        rec.last_activity = time.time()
        return self._snapshot(rec, unread_only=not full_tail, tail_chars=max(256, min(int(tail_chars), 32_000)))

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            self._reap_idle_locked()
            items: list[dict[str, Any]] = []
            for rec in self._sessions.values():
                rc = rec.proc.poll()
                items.append({
                    "pty_id": rec.pty_id,
                    "pid": rec.proc.pid,
                    "command": rec.command,
                    "running": rc is None,
                    "exit_code": rc,
                    "created_at": rec.created_at,
                })
            return items

    def stop(self, pty_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._sessions.pop(pty_id, None)
        if rec is None:
            raise PtySessionError(f"Unknown PTY session: {pty_id!r}")
        self._terminate_record(rec)
        return self._snapshot(rec, unread_only=False)

    def close_all(self) -> None:
        with self._lock:
            records = list(self._sessions.values())
            self._sessions.clear()
        for rec in records:
            self._terminate_record(rec)
