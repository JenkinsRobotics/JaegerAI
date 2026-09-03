"""Async, shell-free process lifecycle for delegate command adapters."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
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


@dataclass(slots=True)
class _Invocation:
    process: asyncio.subprocess.Process
    queue: asyncio.Queue[DelegateEvent | None]
    result_future: asyncio.Future[DelegateResult]
    collector: asyncio.Task[None] | None = None
    output: dict[str, list[str]] = field(
        default_factory=lambda: {"stdout": [], "stderr": []}
    )
    output_bytes: int = 0
    sequence: int = 0


class SubprocessDelegateRuntime:
    """Run a CLI delegate without a shell and stream bounded line events."""

    def __init__(self, spec: CommandSpec) -> None:
        self.spec = spec
        self.runtime_id = spec.runtime_id
        self._invocations: dict[str, _Invocation] = {}

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

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        executable = self._executable()
        if executable is None:
            raise RuntimeError(f"delegate executable not found: {self.spec.executables}")
        cwd = request.workspace
        if cwd is not None and (not cwd.exists() or not cwd.is_dir()):
            raise ValueError(f"delegate workspace is not a directory: {cwd}")
        argv = self.spec.build_args(request, executable)
        process = await asyncio.create_subprocess_exec(
            executable,
            *argv,
            cwd=str(cwd) if cwd else None,
            stdin=asyncio.subprocess.PIPE if self.spec.prompt_on_stdin else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._environment(),
        )
        loop = asyncio.get_running_loop()
        invocation = _Invocation(
            process=process,
            queue=asyncio.Queue(),
            result_future=loop.create_future(),
        )
        self._invocations[request.task_id] = invocation
        if self.spec.prompt_on_stdin and process.stdin is not None:
            process.stdin.write(request.prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        invocation.collector = asyncio.create_task(
            self._collect(request, invocation),
            name=f"delegate:{self.runtime_id}:{request.task_id}",
        )
        return DelegateHandle(request.task_id, self.runtime_id)

    async def _pump(
        self,
        invocation: _Invocation,
        stream: asyncio.StreamReader | None,
        source: str,
    ) -> None:
        if stream is None:
            return
        while line := await stream.readline():
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            encoded_size = len(line)
            if invocation.output_bytes < _OUTPUT_LIMIT:
                remaining = _OUTPUT_LIMIT - invocation.output_bytes
                invocation.output[source].append(line[:remaining].decode("utf-8", errors="replace"))
                invocation.output_bytes += min(encoded_size, remaining)
            invocation.sequence += 1
            await invocation.queue.put(
                DelegateEvent(invocation.sequence, "output", {"source": source, "text": text})
            )

    async def _collect(self, request: DelegateRequest, invocation: _Invocation) -> None:
        timed_out = False
        try:
            async with asyncio.timeout(request.timeout_seconds):
                await asyncio.gather(
                    self._pump(invocation, invocation.process.stdout, "stdout"),
                    self._pump(invocation, invocation.process.stderr, "stderr"),
                )
                return_code = await invocation.process.wait()
        except TimeoutError:
            timed_out = True
            invocation.process.kill()
            await invocation.process.wait()
            return_code = invocation.process.returncode
        except asyncio.CancelledError:
            if invocation.process.returncode is None:
                invocation.process.kill()
                await invocation.process.wait()
            result = DelegateResult(
                status="cancelled",
                summary="delegate execution cancelled",
                metadata={"exit_code": invocation.process.returncode},
            )
            if not invocation.result_future.done():
                invocation.result_future.set_result(result)
            await invocation.queue.put(None)
            raise
        except Exception as exc:  # noqa: BLE001 - preserve arbitrary child I/O failure
            if not invocation.result_future.done():
                invocation.result_future.set_exception(exc)
            await invocation.queue.put(None)
            return

        stdout = "".join(invocation.output["stdout"]).strip()
        stderr = "".join(invocation.output["stderr"]).strip()
        if timed_out:
            status = "failed"
            summary = f"delegate timed out after {request.timeout_seconds} seconds"
        elif return_code == 0:
            status = "completed"
            summary = _extract_summary(stdout) or "delegate completed without text output"
        else:
            status = "failed"
            summary = _extract_summary(stderr) or _extract_summary(stdout) or (
                f"delegate exited with code {return_code}"
            )
        result = DelegateResult(
            status=status,
            summary=summary,
            metadata={
                "exit_code": return_code,
                "stderr": stderr[-8000:],
                "output_truncated": invocation.output_bytes >= _OUTPUT_LIMIT,
            },
        )
        if not invocation.result_future.done():
            invocation.result_future.set_result(result)
        await invocation.queue.put(None)

    async def stream(self, handle: DelegateHandle):
        invocation = self._require_invocation(handle)
        while True:
            event = await invocation.queue.get()
            if event is None:
                break
            yield event

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        invocation = self._require_invocation(handle)
        try:
            return await invocation.result_future
        finally:
            self._invocations.pop(handle.task_id, None)

    async def cancel(self, handle: DelegateHandle) -> None:
        invocation = self._require_invocation(handle)
        if invocation.process.returncode is None:
            invocation.process.terminate()
            try:
                await asyncio.wait_for(invocation.process.wait(), timeout=3)
            except TimeoutError:
                invocation.process.kill()
                await invocation.process.wait()
        if invocation.collector is not None:
            invocation.collector.cancel()

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        del handle, message
        raise NotImplementedError(f"{self.runtime_id} CLI sessions are one-shot")

    def _require_invocation(self, handle: DelegateHandle) -> _Invocation:
        if handle.runtime_id != self.runtime_id:
            raise ValueError(f"handle belongs to {handle.runtime_id}, not {self.runtime_id}")
        invocation = self._invocations.get(handle.task_id)
        if invocation is None:
            raise KeyError(f"unknown delegate handle: {handle.task_id}")
        return invocation

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
        return clean[-100_000:]
    extracted = _find_text(value)
    return extracted.strip() if extracted else clean[-100_000:]


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
