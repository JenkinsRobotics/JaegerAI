"""Bounded CLI stream collection; the existing adapter owns process lifetime."""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Callable


def text_delta(line: bytes) -> str:
    """Only public response deltas, not reasoning, tool arguments or final replay."""
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
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return ""
    return delta.get("text") if isinstance(delta.get("text"), str) else ""


def collect_stream(proc: subprocess.Popen, stdin: bytes | None, timeout: float,
                   on_delta: Callable[[str], None]) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently so a verbose CLI cannot deadlock streaming.

    Readers are joined before returning; final stdout remains available for the
    adapter's normal response parser. Limits apply to bytes, including long lines.
    """
    output = bytearray()
    errors = bytearray()
    failures: list[BaseException] = []
    def stdout_reader() -> None:
        try:
            assert proc.stdout is not None
            while line := proc.stdout.readline(1_048_577):
                if len(line) > 1_048_576 or len(output) + len(line) > 8_388_608:
                    raise RuntimeError("CLI response exceeded the stream output limit")
                output.extend(line)
                delta = text_delta(line)
                if delta:
                    on_delta(delta)
        except BaseException as exc:
            failures.append(exc)
            proc.terminate()
    def stderr_reader() -> None:
        assert proc.stderr is not None
        while chunk := proc.stderr.read(8192):
            errors.extend(chunk)
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
        proc.wait(timeout=timeout)
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
