from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from jaeger_agent.delegates import DelegateRequest
from jaeger_agent.delegates.process import CommandSpec, SubprocessDelegateRuntime


def _request(workspace: Path, *, timeout: int = 5) -> DelegateRequest:
    return DelegateRequest(
        task_id="run-1",
        prompt="hello delegate",
        workspace=workspace,
        timeout_seconds=timeout,
        idempotency_key="test-1",
    )


def test_process_runtime_streams_and_returns_summary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_SHOULD_NOT_PASS", "leak")

    def args(request, executable):
        del request, executable
        code = (
            "import json,os,sys; print('progress'); "
            "print(json.dumps({'result': sys.stdin.read(), "
            "'leaked': os.getenv('SECRET_SHOULD_NOT_PASS')}))"
        )
        return ("-c", code)

    runtime = SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="test-process",
            executables=(sys.executable,),
            build_args=args,
            capabilities=frozenset({"test"}),
            local=True,
            prompt_on_stdin=True,
        )
    )

    async def run():
        status = await runtime.probe()
        assert status.available
        handle = await runtime.start(_request(tmp_path))
        events = [event async for event in runtime.stream(handle)]
        result = await runtime.result(handle)
        return events, result

    events, result = asyncio.run(run())
    assert [event.payload["source"] for event in events] == ["stdout", "stdout"]
    assert result.status == "completed"
    assert "hello delegate" in result.summary
    assert '"leaked": "leak"' not in result.summary


def test_process_runtime_enforces_timeout(tmp_path) -> None:
    def args(request, executable):
        del request, executable
        return ("-c", "import time; time.sleep(2)")

    runtime = SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="test-timeout",
            executables=(sys.executable,),
            build_args=args,
            capabilities=frozenset(),
            local=True,
        )
    )

    async def run():
        handle = await runtime.start(_request(tmp_path, timeout=1))
        _ = [event async for event in runtime.stream(handle)]
        return await runtime.result(handle)

    result = asyncio.run(run())
    assert result.status == "failed"
    assert "timed out" in result.summary
