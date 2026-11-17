"""Bounded CLI stream collection; the existing adapter owns process lifetime."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Callable


def stream_delta(line: bytes, channel: str = "text") -> str:
    """Read only top-level provider delta events; never replay final messages."""
    try:
        row = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(row, dict) or row.get("type") != "stream_event" or row.get("parent_tool_use_id"):
        return ""
    event = row.get("event")
    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != channel + "_delta":
        return ""
    return delta.get(channel) if isinstance(delta.get(channel), str) else ""


def text_delta(line: bytes) -> str:
    return stream_delta(line)


# Tool activity seen by the Jaeger MCP executor while a CLI turn runs. A tool
# in flight (or one that just finished) counts as progress, so a long turn
# that keeps working is not killed by the idle limit; a silent spin still is.
_ACTIVITY = {"last": 0.0, "inflight": 0}
_ACTIVITY_LOCK = threading.Lock()


def touch_activity() -> None:
    with _ACTIVITY_LOCK:
        _ACTIVITY["last"] = time.monotonic()


@contextmanager
def tool_in_flight():
    with _ACTIVITY_LOCK:
        _ACTIVITY["inflight"] += 1
        _ACTIVITY["last"] = time.monotonic()
    try:
        yield
    finally:
        with _ACTIVITY_LOCK:
            _ACTIVITY["inflight"] = max(0, _ACTIVITY["inflight"] - 1)
            _ACTIVITY["last"] = time.monotonic()


def collect_stream(proc: subprocess.Popen, stdin: bytes | None, timeout: float,
                   on_delta: Callable[[str], None], on_reasoning=None, on_progress=None,
                   idle_timeout: float | None = None) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently so a verbose CLI cannot deadlock streaming.

    Readers are joined before returning; final stdout remains available for the
    adapter's normal response parser. Limits apply to bytes, including long lines.
    """
    output = bytearray()
    errors = bytearray()
    failures: list[BaseException] = []
    started = time.monotonic()
    seen = [started]
    def stdout_reader() -> None:
        try:
            assert proc.stdout is not None
            while line := proc.stdout.readline(1_048_577):
                seen[0] = time.monotonic()
                if len(line) > 1_048_576 or len(output) + len(line) > 8_388_608:
                    raise RuntimeError("CLI response exceeded the stream output limit")
                output.extend(line)
                if on_progress:
                    on_progress()
                reasoning = stream_delta(line, "thinking")
                if reasoning and on_reasoning:
                    on_reasoning(reasoning)
                delta = text_delta(line)
                if delta:
                    on_delta(delta)
        except BaseException as exc:
            failures.append(exc)
            proc.terminate()
    def stderr_reader() -> None:
        assert proc.stderr is not None
        while chunk := proc.stderr.read1(8192) if hasattr(proc.stderr, "read1") else proc.stderr.read(8192):
            errors.extend(chunk)
            seen[0] = time.monotonic()
            # CLI status/log lines are liveness too (stale detector).
            if on_progress:
                on_progress()
            if len(errors) > 1_048_576:
                del errors[:-1_048_576]
    readers = [threading.Thread(target=stdout_reader, daemon=True),
               threading.Thread(target=stderr_reader, daemon=True)]
    for reader in readers:
        reader.start()
    try:
        if stdin is not None and proc.stdin is not None:
            proc.stdin.write(stdin)
            proc.stdin.close()
        tool_seen = _ACTIVITY["last"]
        while True:
            try:
                proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                # Jaeger tool work inside the CLI is liveness for the loop's
                # stale detector too (it only sees stream lines otherwise).
                if on_progress and (_ACTIVITY["inflight"] or _ACTIVITY["last"] > tool_seen):
                    tool_seen = _ACTIVITY["last"]
                    on_progress()
                if timeout and now - started > timeout:
                    raise
                if idle_timeout and _ACTIVITY["inflight"] == 0:
                    quiet = now - max(seen[0], _ACTIVITY["last"])
                    if quiet > idle_timeout:
                        raise subprocess.TimeoutExpired(proc.args, idle_timeout) from None
        for reader in readers:
            reader.join(timeout=2)
        if any(reader.is_alive() for reader in readers):
            raise RuntimeError("CLI stream did not close after process exit")
        if failures:
            raise failures[0]
        return bytes(output), bytes(errors)
    finally:
        # On timeout, the adapter kills its owned process group. Daemon readers
        # then see EOF; do not close a pipe while its reader holds the IO lock.
        if proc.poll() is not None:
            for reader in readers:
                reader.join(timeout=2)
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None and not any(r.is_alive() for r in readers):
                    pipe.close()


class VisibleTextStream:
    """Keep the existing Hermes tool envelope out of user-visible text deltas.

    This is a presentation filter only. The unchanged final response is parsed
    by the canonical tool-call repair path and executed by the Jaeger loop.
    """
    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        self.pending = ""
        self.in_tool = False

    def feed(self, text: str) -> None:
        self.pending += text
        while self.pending:
            marker = "</tool_call>" if self.in_tool else "<tool_call>"
            index = self.pending.find(marker)
            if index >= 0:
                if not self.in_tool and index:
                    self.emit(self.pending[:index])
                self.pending = self.pending[index + len(marker):]
                self.in_tool = not self.in_tool
                continue
            keep = next((n for n in range(min(len(marker)-1,len(self.pending)),0,-1)
                         if self.pending.endswith(marker[:n])), 0)
            ready = self.pending[:-keep] if keep else self.pending
            if ready and not self.in_tool:
                self.emit(ready)
            self.pending = self.pending[-keep:] if keep else ""
            break

    def finish(self) -> None:
        if self.pending and not self.in_tool:
            self.emit(self.pending)
        self.pending = ""
