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


# ── JSONL event streams ─────────────────────────────────────────────

from jaeger_agent.delegates.process.runtime import _extract_summary  # noqa: E402

_CODEX_STREAM = """\
{"type":"thread.started","thread_id":"01a06a66"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Skill descriptions were shortened to fit the budget."}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"The walrus operator assigns within an expression."}}
{"type":"turn.completed","usage":{"input_tokens":19196,"output_tokens":21}}"""


def test_summary_reads_the_answer_out_of_a_jsonl_stream() -> None:
    """codex --json emits one object per line, so whole-blob json.loads fails
    and the operator used to get the raw stream as the 'summary'."""
    assert _extract_summary(_CODEX_STREAM) == (
        "The walrus operator assigns within an expression."
    )


def test_summary_ignores_narration_events() -> None:
    """A usage total or a CLI warning must never outrank the real answer."""
    summary = _extract_summary(_CODEX_STREAM)
    assert "input_tokens" not in summary, "usage totals are not the answer"
    assert "Skill descriptions" not in summary, "a CLI warning is not the answer"


def test_summary_falls_back_to_raw_output_when_nothing_answered() -> None:
    """With no assistant message at all, showing the raw stream beats
    showing nothing — the operator still needs to see what happened."""
    narration_only = (
        '{"type":"thread.started","thread_id":"x"}\n'
        '{"type":"turn.completed","usage":{"input_tokens":5}}'
    )
    assert _extract_summary(narration_only).strip() != ""


def test_summary_prefers_the_last_assistant_message() -> None:
    two_turns = (
        '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"second"}}'
    )
    assert _extract_summary(two_turns) == "second"


def test_summary_leaves_plain_text_and_single_json_alone() -> None:
    assert _extract_summary("just some text") == "just some text"
    assert _extract_summary('{"result": "hello"}') == "hello"
    assert _extract_summary("   ") == ""
