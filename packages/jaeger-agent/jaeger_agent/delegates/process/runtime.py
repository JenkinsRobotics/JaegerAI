"""Async, shell-free process lifecycle for delegate command adapters."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..contracts import (
    DelegateEvent,
    DelegateHandle,
    DelegateRequest,
    DelegateResult,
    RuntimeStatus,
)

CommandBuilder = Callable[[DelegateRequest, str], tuple[str, ...]]
AvailabilityCheck = Callable[[], tuple[bool, str]]

_SAFE_ENV = frozenset(
    {
        "COLORTERM",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "NO_COLOR",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
        "USER",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
)
_OUTPUT_LIMIT = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CommandSpec:
    runtime_id: str
    executables: tuple[str, ...]
    build_args: CommandBuilder
    capabilities: frozenset[str]
    local: bool
    probe_args: tuple[str, ...] = ("--version",)
    credential_env: frozenset[str] = frozenset()
    prompt_on_stdin: bool = False
    availability_check: AvailabilityCheck | None = None


class SubprocessDelegateRuntime:
    """Run a CLI delegate without a shell and stream bounded line events."""

    def __init__(self, spec: CommandSpec, *, receipt_root: Path | None = None) -> None:
        self.spec = spec
        self.runtime_id = spec.runtime_id
        self.receipt_root = receipt_root

    def _executable(self) -> str | None:
        for candidate in self.spec.executables:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    async def probe(self) -> RuntimeStatus:
        executable = self._executable()
        if executable is None:
            names = ", ".join(self.spec.executables)
            return RuntimeStatus(
                False,
                f"executable not found: {names}",
                self.spec.capabilities,
                self.spec.local,
            )
        if self.spec.availability_check is not None:
            available, detail = self.spec.availability_check()
            if not available:
                return RuntimeStatus(
                    False,
                    detail,
                    self.spec.capabilities,
                    self.spec.local,
                )
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *self.spec.probe_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._environment(),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        except (OSError, TimeoutError) as exc:
            return RuntimeStatus(
                False,
                f"probe failed: {type(exc).__name__}: {exc}",
                self.spec.capabilities,
                self.spec.local,
            )
        detail = stdout.decode("utf-8", errors="replace").strip().splitlines()
        return RuntimeStatus(
            process.returncode == 0,
            detail[0][:240] if detail else f"exit code {process.returncode}",
            self.spec.capabilities,
            self.spec.local,
        )

    def _directory(self, handle):
        if handle.runtime_id != self.runtime_id:
            raise ValueError(f"handle belongs to {handle.runtime_id}, not {self.runtime_id}")
        root = self.receipt_root
        if root is None:
            from jaeger_agent.core.workspace import _require_layout
            root = _require_layout().run_dir / 'delegates'
        identity = hashlib.sha256(json.dumps([self.runtime_id, handle.task_id]).encode()).hexdigest()
        return Path(root) / identity

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        from .worker import write_json
        executable = self._executable()
        if executable is None:
            raise RuntimeError(f"delegate executable not found: {self.spec.executables}")
        cwd = request.workspace
        if cwd is not None and (not cwd.exists() or not cwd.is_dir()):
            raise ValueError(f"delegate workspace is not a directory: {cwd}")
        handle = DelegateHandle(request.task_id, self.runtime_id)
        root = self._directory(handle)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        command = {'argv':[executable, *self.spec.build_args(request, executable)],
                   'cwd':str(cwd) if cwd else None, 'timeout':request.timeout_seconds,
                   'prompt':request.prompt if self.spec.prompt_on_stdin else None}
        identity = {'command':command, 'idempotency_key':request.idempotency_key,
                    'allowed_tools':sorted(request.allowed_tools), 'sensitivity':request.sensitivity,
                    'required_capabilities':sorted(request.required_capabilities), 'metadata':request.metadata}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with (root/'admission.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            manifest = root/'admission.json'
            if manifest.exists():
                if json.loads(manifest.read_text())['fingerprint'] != fingerprint:
                    raise ValueError('Delegate task identity conflicts with accepted execution')
                return handle
            write_json(manifest, {'fingerprint':fingerprint, 'created_at':time.time()})
            env = {**self._environment(), 'PYTHONDONTWRITEBYTECODE':'1'}
            worker = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('worker.py')), str(root)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, env=env)
            try:
                worker.stdin.write(json.dumps(command).encode())
                worker.stdin.close()
            except Exception:
                worker.terminate()
                worker.wait()
                raise
            threading.Thread(target=worker.wait, name='delegate-reaper', daemon=True).start()
        return handle

    def _running(self, root):
        if not (root/'admission.json').exists():
            raise KeyError('Unknown delegate handle')
        # Allow launch handoff to acquire the lock. Beyond this window, a free
        # worker lock means an indeterminate process outcome, never permission
        # to launch the command again.
        if time.time() - json.loads((root/'admission.json').read_text())['created_at'] < 5:
            return True
        with (root/'worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True

    async def stream(self, handle: DelegateHandle):
        root = self._directory(handle)
        offset = 0
        while True:
            path = root/'events.jsonl'
            if path.exists():
                with path.open() as stream:
                    stream.seek(offset)
                    while True:
                        line = stream.readline()
                        if not line or not line.endswith('\n'):
                            break
                        row = json.loads(line)
                        offset = stream.tell()
                        yield DelegateEvent(row['sequence'], row['event_type'], row['payload'])
            if (root/'result.json').exists() or not self._running(root):
                return
            await asyncio.sleep(0.05)

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        root = self._directory(handle)
        while not (root/'result.json').exists():
            if not self._running(root):
                return DelegateResult(status='blocked', summary='Worker exited without a terminal receipt; reconcile effects before retry',
                                      metadata={'execution_unknown':True})
            await asyncio.sleep(0.05)
        row = json.loads((root/'result.json').read_text())
        if row.get('timed_out'):
            summary = f"delegate timed out after {row['timeout']} seconds"
        elif row['status'] == 'cancelled':
            summary = 'delegate execution cancelled'
        else:
            summary = _extract_summary(row.get('stdout') or '') if row['status'] == 'completed' else _extract_summary(row.get('stderr') or row.get('stdout') or '')
        return DelegateResult(status=row['status'], summary=summary or 'delegate completed without text output',
            metadata={'exit_code':row.get('exit_code'), 'stderr':row.get('stderr','')[-8000:],
                      'output_truncated':row.get('output_truncated',False)})

    async def cancel(self, handle: DelegateHandle) -> None:
        root = self._directory(handle)
        if not (root/'admission.json').exists():
            raise KeyError('Unknown delegate handle')
        (root/'cancel').touch()
        result = await self.result(handle)
        if result.metadata.get('execution_unknown'):
            raise RuntimeError(result.summary)

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        del handle, message
        raise NotImplementedError(f"{self.runtime_id} CLI sessions are one-shot")

    def _environment(self) -> dict[str, str]:
        allowed = _SAFE_ENV | self.spec.credential_env
        return {key: value for key, value in os.environ.items() if key in allowed}


def _extract_summary(text: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        streamed = _extract_from_jsonl(clean)
        return streamed if streamed else clean[-100_000:]
    extracted = _find_text(value)
    return extracted.strip() if extracted else clean[-100_000:]


def _extract_from_jsonl(text: str) -> str:
    """Pull the assistant's answer out of a JSONL event stream.

    Several agent CLIs (codex among them) emit one JSON object per line
    rather than a single document, so the whole-blob ``json.loads`` above
    fails and the operator gets the raw stream as the "summary". Parse the
    lines instead and prefer the last real assistant message.

    Events that merely narrate the run — usage totals, thread ids, and the
    CLI's own warnings — are skipped: taking the last line with any text at
    all would surface a token count or a truncation notice as the answer.
    """
    events: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        return ""

    for event in reversed(events):
        message = _assistant_message(event)
        if message:
            return message.strip()
    for event in reversed(events):
        if _event_kind(event) in _NARRATION_KINDS:
            continue
        found = _find_text(event)
        if found:
            return found.strip()
    return ""


_ASSISTANT_KINDS = frozenset({"agent_message", "assistant_message", "assistant", "message"})
_NARRATION_KINDS = frozenset({
    "error", "thread.started", "turn.started", "turn.completed", "usage",
})


def _event_kind(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("type", "kind", "event"):
            kind = value.get(key)
            if isinstance(kind, str):
                return kind
    return ""


def _assistant_message(value: Any) -> str:
    """Text from a node explicitly typed as the assistant speaking."""
    if isinstance(value, dict):
        if _event_kind(value) in _ASSISTANT_KINDS:
            for key in ("text", "content", "message"):
                found = _find_text(value.get(key))
                if found:
                    return found
        for child in reversed(tuple(value.values())):
            found = _assistant_message(child)
            if found:
                return found
    if isinstance(value, list):
        for child in reversed(value):
            found = _assistant_message(child)
            if found:
                return found
    return ""


def _find_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("result", "final_response", "response", "message", "content", "text"):
            if key in value:
                found = _find_text(value[key])
                if found:
                    return found
        for child in reversed(tuple(value.values())):
            found = _find_text(child)
            if found:
                return found
    if isinstance(value, list):
        for child in reversed(value):
            found = _find_text(child)
            if found:
                return found
    return ""
