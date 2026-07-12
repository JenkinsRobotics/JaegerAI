"""Hermes-adoption pass (2026-06) — regression pins.

Each test pins one mechanism ported from the Hermes agent after the
side-by-side review: warn-before-halt guardrails, result-hash-aware
no-progress detection, error-classified adapter retry, the post-tool
empty-response nudge, the wind-down grace call, read-batch dedup,
3-stage context compaction, estimator calibration, surrogate
scrubbing, and the truncated-JSON argument repair.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_ai.agent import (
    JaegerAgent,
    Message,
    ProviderAdapter,
    ToolDef,
    clear_registry,
    register_tool_instance,
)
from jaeger_ai.agent.util.context_guard import (
    DIGEST_PREFIX,
    ContextBudget,
    ContextGuard,
)


class _ScriptedAdapter(ProviderAdapter):
    name = "scripted"

    def __init__(self, script: list[Message | Exception]) -> None:
        self._script = list(script)
        self.call_count = 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        self.last_tools = list(tools)
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


class _Args(BaseModel):
    value: str = Field(default="x")


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def _register(name: str, fn, *, side_effect: str = "write") -> None:
    register_tool_instance(ToolDef(
        name=name, description=name, args_model=_Args, fn=fn,
        side_effect=side_effect,
    ))


def _tc(name: str, value: str, tc_id: str = "") -> dict[str, Any]:
    return {"id": tc_id, "name": name, "arguments": {"value": value}}


def _assistant_call(*tcs: dict[str, Any]) -> Message:
    return {"role": "assistant", "content": None, "tool_calls": list(tcs)}


# ── warn-before-halt ───────────────────────────────────────────────


def test_failure_warns_in_result_before_semantic_halt():
    """Semantic failures halt at 2, so the FIRST failure is the only
    pre-halt slot — it must carry loop guidance in the tool result so
    the model can change course while it still can."""
    _register("flaky", lambda value="x": {"ok": False, "error": "disk on fire"})
    adapter = _ScriptedAdapter([
        _assistant_call(_tc("flaky", "a")),
        _assistant_call(_tc("flaky", "b")),   # same error, different args
        {"role": "assistant", "content": "gave up"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("try the thing")

    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert "loop warning" in tool_msgs[0]["content"]
    assert "Do not abandon tools" in tool_msgs[0]["content"]
    # Halt threshold unchanged: 2 identical failures still halt.
    assert agent.last_halt_reason is not None
    assert "failure" in agent.last_halt_reason


def test_identical_write_call_warns_at_two_halts_at_four():
    calls: list[str] = []
    _register("poke", lambda value="x": calls.append(value) or {"ok": True})
    same = lambda: _assistant_call(_tc("poke", "same"))  # noqa: E731
    adapter = _ScriptedAdapter([
        same(), same(), same(), same(),
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("poke it")

    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert "loop warning" not in tool_msgs[0]["content"]
    assert "loop warning" in tool_msgs[1]["content"]
    assert agent.last_halt_reason is not None
    assert "identical" in agent.last_halt_reason


# ── result-hash no-progress for read tools ─────────────────────────


def test_polling_read_with_changing_results_does_not_halt():
    """Identical READ calls whose results CHANGE are legitimate polling
    — the identical-call halt must not fire."""
    ticks = iter(range(10))
    _register(
        "check_status",
        lambda value="x": {"ok": True, "tick": next(ticks)},
        side_effect="read",
    )
    poll = lambda: _assistant_call(_tc("check_status", "job1"))  # noqa: E731
    adapter = _ScriptedAdapter([
        poll(), poll(), poll(), poll(), poll(),
        {"role": "assistant", "content": "job finished"},
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("watch the job")
    assert answer == "job finished"
    assert agent.last_halt_reason is None


def test_read_with_static_results_still_halts():
    _register(
        "read_thing",
        lambda value="x": {"ok": True, "data": "unchanging"},
        side_effect="read",
    )
    rep = lambda: _assistant_call(_tc("read_thing", "same"))  # noqa: E731
    adapter = _ScriptedAdapter([
        rep(), rep(), rep(), rep(), rep(),
        {"role": "assistant", "content": "never reached"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("read it")
    assert agent.last_halt_reason is not None
    assert "identical" in agent.last_halt_reason


# ── error-classified retry ─────────────────────────────────────────


class _RateLimitError(Exception):
    status_code = 429


class _AuthenticationError(Exception):
    status_code = 401


def test_rate_limit_retries_same_adapter_then_succeeds(monkeypatch):
    import jaeger_ai.agent.loop.jaeger_agent as loop_mod
    monkeypatch.setattr(loop_mod, "_retry_delay", lambda kind, attempt: 0.01)

    primary = _ScriptedAdapter([
        _RateLimitError("429 slow down"),
        _RateLimitError("429 slow down"),
        {"role": "assistant", "content": "made it"},
    ])
    backup = _ScriptedAdapter([{"role": "assistant", "content": "fallback"}])
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup])
    answer = agent.run_turn("hello")
    assert answer == "made it"
    assert primary.call_count == 3
    assert backup.call_count == 0


def test_auth_error_skips_retry_and_falls_back_immediately(monkeypatch):
    import jaeger_ai.agent.loop.jaeger_agent as loop_mod
    monkeypatch.setattr(loop_mod, "_retry_delay", lambda kind, attempt: 0.01)

    primary = _ScriptedAdapter([
        _AuthenticationError("bad key"),
        {"role": "assistant", "content": "should not be used"},
    ])
    backup = _ScriptedAdapter([{"role": "assistant", "content": "fallback won"}])
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup])
    answer = agent.run_turn("hello")
    assert answer == "fallback won"
    assert primary.call_count == 1
    assert backup.call_count == 1


# ── post-tool empty-response nudge ─────────────────────────────────


def test_empty_after_tool_results_gets_one_nudge_and_recovers():
    _register("echo", lambda value="x": {"ok": True, "echoed": value})
    adapter = _ScriptedAdapter([
        _assistant_call(_tc("echo", "a")),
        {"role": "assistant", "content": None},       # the silent stall
        {"role": "assistant", "content": "all done"},  # after the nudge
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("do it")
    assert answer == "all done"
    assert adapter.call_count == 3
    # The synthetic nudge never persists.
    contents = [str(m.get("content")) for m in agent.messages]
    assert not any("Your last response was empty" in c for c in contents)
    assert agent.last_halt_reason is None


def test_empty_without_prior_tool_results_keeps_placeholder_path():
    adapter = _ScriptedAdapter([{"role": "assistant", "content": None}])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("hello?")
    assert answer == ""
    assert agent.last_halt_reason == "empty_response"
    assert adapter.call_count == 1


# ── wind-down grace call ───────────────────────────────────────────


def test_max_iterations_winds_down_with_toolless_summary():
    _register("echo", lambda value="x": {"ok": True})
    adapter = _ScriptedAdapter([
        _assistant_call(_tc("echo", "1")),
        _assistant_call(_tc("echo", "2")),
        {"role": "assistant", "content": "I fetched two things; next I'd merge them."},
    ])
    agent = JaegerAgent(adapter=adapter, max_iterations=2)
    answer = agent.run_turn("long task")
    assert "merge them" in answer
    assert "max_iterations" in (agent.last_halt_reason or "")
    # The wind-down call saw NO tools, and the synthetic prompt is gone.
    assert adapter.last_tools == []
    contents = [str(m.get("content")) for m in agent.messages]
    assert not any("tool-call budget" in c for c in contents)
    assert agent.messages[-1]["role"] == "assistant"


# ── read-batch dedup ───────────────────────────────────────────────


def test_identical_read_calls_in_one_batch_dispatch_once():
    hits: list[str] = []
    _register(
        "look", lambda value="x": hits.append(value) or {"ok": True, "v": value},
        side_effect="read",
    )
    adapter = _ScriptedAdapter([
        _assistant_call(
            _tc("look", "same", "c1"),
            _tc("look", "same", "c2"),
            _tc("look", "other", "c3"),
        ),
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("look twice")
    assert hits == ["same", "other"]
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 3  # every call id still gets a result
    assert "duplicate" in tool_msgs[1]["content"]


# ── 3-stage compaction ─────────────────────────────────────────────


def test_stage1_prunes_old_tool_results_before_dropping():
    g = ContextGuard(ContextBudget(
        ctx_window=450, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,
    ))
    msgs = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "read_file", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file",
         "content": '{"artifact_path": "/tmp/big.json", "preview": "' + "z" * 400 + '"}'},
        {"role": "assistant", "content": "summarised it"},
        {"role": "user", "content": "current question"},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    assert result.pruned_count == 1
    assert result.dropped_count == 0
    stub = result.messages[2]["content"]
    assert "pruned for context" in stub
    # The on-disk reference survives compaction.
    assert "/tmp/big.json" in stub
    # Input list untouched.
    assert "z" * 400 in msgs[2]["content"]


def test_stage2_drops_into_digest_and_never_stacks():
    g = ContextGuard(ContextBudget(
        ctx_window=400, reserve_for_completion=0, safety_margin=0,
        chars_per_token=3.0,
    ))
    msgs = [
        {"role": "user", "content": "please reticulate the splines " + "pad " * 200},
        {"role": "assistant", "content": "reticulating " + "pad " * 200},
        {"role": "user", "content": "current question"},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    assert result.digested is True
    # Drops as LITTLE as possible — at least the oldest message went.
    assert result.dropped_count >= 1
    head = result.messages[0]
    assert head["role"] == "user"
    assert head["content"].startswith(DIGEST_PREFIX)
    assert "reticulate the splines" in head["content"]

    # Re-compaction folds the old digest instead of stacking a second.
    msgs2 = [
        *result.messages[:-1],
        {"role": "user", "content": "another old q " + "pad " * 250},
        {"role": "assistant", "content": "another old a " + "pad " * 250},
        {"role": "user", "content": "newest question"},
    ]
    result2 = g.trim_to_fit(msgs2, system_prompt="", tools=[])
    digests = [
        m for m in result2.messages
        if str(m.get("content") or "").startswith(DIGEST_PREFIX)
    ]
    assert len(digests) <= 1


def test_calibration_moves_estimator_toward_real_usage():
    g = ContextGuard(ContextBudget(ctx_window=8192))
    before = g.estimate_text_tokens("w" * 3000)
    # Provider says those ~3000 chars were 750 tokens (4.0 chars/token).
    g.observed_call(
        750,
        [{"role": "user", "content": "w" * 3000}],
        system_prompt="", tools=[],
    )
    after = g.estimate_text_tokens("w" * 3000)
    # Estimator relaxed toward reality (fewer estimated tokens), but
    # stays conservative (still >= the real 750).
    assert after < before
    assert after >= 750


# ── surrogate scrubbing ────────────────────────────────────────────


def test_lone_surrogates_scrubbed_before_model_call():
    adapter = _ScriptedAdapter([{"role": "assistant", "content": "ok"}])
    agent = JaegerAgent(adapter=adapter)
    agent.messages.append({"role": "user", "content": "bad paste \ud83d here"})
    agent.run_turn("hello")
    for m in agent.messages:
        content = m.get("content")
        if isinstance(content, str):
            assert not any("\ud800" <= ch <= "\udfff" for ch in content)


# ── argument repair upgrades ───────────────────────────────────────


def test_repair_recovers_truncated_tool_args():
    from jaeger_ai.agent.dialects import repair_arguments
    args, ok = repair_arguments('{"path": "notes.txt", "content": "abc')
    assert ok is True
    assert args["path"] == "notes.txt"
    assert args["content"] == "abc"


def test_repair_recovers_control_chars_with_truncation():
    from jaeger_ai.agent.dialects import repair_arguments
    args, ok = repair_arguments('{"text": "line one\nline two", "n": 2')
    assert ok is True
    assert args["n"] == 2
    assert "line one" in args["text"]


# ── parallel dispatch (robot-hardening pass) ───────────────────────


def test_all_read_batch_dispatches_concurrently():
    """An all-read batch runs on the pool — wall-clock approaches the
    slowest call, not the sum. Three 0.15s reads must finish well
    under 3×0.15s, and the transcript stays ordered + complete."""
    import time as _time

    def _slow_read(value: str = "x") -> dict:
        _time.sleep(0.15)
        return {"ok": True, "v": value}

    register_tool_instance(ToolDef(
        name="slow_read", description="r", args_model=_Args,
        fn=_slow_read, side_effect="read",
    ))
    adapter = _ScriptedAdapter([
        _assistant_call(
            _tc("slow_read", "a", "c1"),
            _tc("slow_read", "b", "c2"),
            _tc("slow_read", "c", "c3"),
        ),
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    t0 = _time.perf_counter()
    answer = agent.run_turn("read three things")
    elapsed = _time.perf_counter() - t0
    assert answer == "done"
    assert elapsed < 0.40, f"batch took {elapsed:.2f}s — not parallel"
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2", "c3"]
    assert all('"ok": true' in m["content"].lower() for m in tool_msgs)


def test_mixed_batch_stays_sequential():
    """One unclassified (write-side) tool in the batch forces the whole
    batch sequential — order of side effects is preserved."""
    order: list[str] = []

    def _read(value: str = "x") -> dict:
        order.append(f"read:{value}")
        return {"ok": True}

    def _write(value: str = "x") -> dict:
        order.append(f"write:{value}")
        return {"ok": True}

    register_tool_instance(ToolDef(
        name="r1", description="r", args_model=_Args, fn=_read,
        side_effect="read",
    ))
    register_tool_instance(ToolDef(
        name="w1", description="w", args_model=_Args, fn=_write,
    ))  # side_effect unclassified → write-side
    adapter = _ScriptedAdapter([
        _assistant_call(_tc("r1", "a"), _tc("w1", "b"), _tc("r1", "c")),
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("mixed work")
    assert order == ["read:a", "write:b", "read:c"]


def test_parallel_batch_dedupes_identical_reads():
    hits: list[str] = []

    def _read(value: str = "x") -> dict:
        hits.append(value)
        return {"ok": True, "v": value}

    register_tool_instance(ToolDef(
        name="pread", description="r", args_model=_Args, fn=_read,
        side_effect="read",
    ))
    adapter = _ScriptedAdapter([
        _assistant_call(
            _tc("pread", "same", "c1"),
            _tc("pread", "same", "c2"),
        ),
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("read twice")
    assert hits == ["same"]
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert "duplicate" in tool_msgs[1]["content"]


# ── mid-turn steer ─────────────────────────────────────────────────


def test_steer_lands_before_next_model_step():
    """A steer queued while tools run is injected as a user message
    before the following model call — the model sees it mid-turn."""
    agent_box: dict[str, Any] = {}

    def _tool_that_steers(value: str = "x") -> dict:
        accepted = agent_box["agent"].steer("actually use metric units")
        return {"ok": True, "steer_accepted": accepted}

    register_tool_instance(ToolDef(
        name="worker", description="w", args_model=_Args,
        fn=_tool_that_steers,
    ))

    class _SteerAwareAdapter(_ScriptedAdapter):
        def __init__(self) -> None:
            super().__init__([])
            self.saw_steer_at_call: int | None = None

        def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
            self.call_count += 1
            msgs = formatted["messages"]
            if any(
                m.get("role") == "user"
                and "metric units" in str(m.get("content"))
                for m in msgs
            ) and self.saw_steer_at_call is None:
                self.saw_steer_at_call = self.call_count
            if self.call_count == 1:
                return _assistant_call(_tc("worker", "go"))
            return {"role": "assistant", "content": "done in metric"}

    adapter = _SteerAwareAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent_box["agent"] = agent
    answer = agent.run_turn("do the thing")
    assert answer == "done in metric"
    # The steer was visible to the SECOND model call.
    assert adapter.saw_steer_at_call == 2
    # And it persists in history as real user content.
    assert any(
        m.get("role") == "user" and "metric units" in str(m.get("content"))
        for m in agent.messages
    )


def test_steer_outside_turn_returns_false():
    agent = JaegerAgent(adapter=_ScriptedAdapter([]))
    assert agent.steer("too late") is False


# ── LLM compaction digest (deep think) ─────────────────────────────


def test_summarizer_digest_used_when_wired():
    calls: list[str] = []

    def _summarizer(prompt: str) -> str:
        calls.append(prompt)
        return "User wanted splines reticulated; agent reticulated them."

    g = ContextGuard(
        ContextBudget(
            ctx_window=400, reserve_for_completion=0, safety_margin=0,
            chars_per_token=3.0,
        ),
        summarizer=_summarizer,
    )
    msgs = [
        {"role": "user", "content": "please reticulate " + "pad " * 200},
        {"role": "assistant", "content": "reticulating " + "pad " * 200},
        {"role": "user", "content": "current question"},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    assert result.digested is True
    assert calls, "summarizer was not invoked"
    head = result.messages[0]["content"]
    assert head.startswith(DIGEST_PREFIX)
    assert "reticulated them" in head


def test_summarizer_failure_falls_back_to_deterministic_digest():
    def _broken(prompt: str) -> str:
        raise RuntimeError("aux model down")

    g = ContextGuard(
        ContextBudget(
            ctx_window=400, reserve_for_completion=0, safety_margin=0,
            chars_per_token=3.0,
        ),
        summarizer=_broken,
    )
    msgs = [
        {"role": "user", "content": "please reticulate the splines " + "pad " * 200},
        {"role": "assistant", "content": "reticulating " + "pad " * 200},
        {"role": "user", "content": "current question"},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    assert result.digested is True
    head = result.messages[0]["content"]
    assert head.startswith(DIGEST_PREFIX)
    # Deterministic digest carried the user ask despite the broken LLM.
    assert "reticulate the splines" in head


# ── tail pass: stream deltas + partial recovery ────────────────────


def test_loop_passes_on_delta_only_when_listener_installed():
    from jaeger_ai.agent import AgentCallbacks

    captured: dict[str, Any] = {}

    class _KwargCapture(_ScriptedAdapter):
        def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return super().call(formatted, interrupt_event)

    # No listener → None (adapters skip per-chunk callback cost).
    agent = JaegerAgent(adapter=_KwargCapture([
        {"role": "assistant", "content": "hi"}]))
    agent.run_turn("x")
    assert captured.get("on_delta") is None

    # Listener installed → a callable arrives at the adapter.
    captured.clear()
    deltas: list[str] = []
    cb = AgentCallbacks(stream_delta=deltas.append)
    agent = JaegerAgent(adapter=_KwargCapture([
        {"role": "assistant", "content": "hi"}]), callbacks=cb)
    agent.run_turn("x")
    assert callable(captured.get("on_delta"))
    captured["on_delta"]("tok")
    assert deltas == ["tok"]


def test_aggregator_emits_text_deltas():
    import threading
    from jaeger_ai.agent.adapters.openai import _aggregate_chat_stream
    from jaeger_ai.agent.loop.interrupt import CallProgress
    from types import SimpleNamespace

    def _chunk(text):
        delta = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=None)],
            usage=None,
        )

    pieces: list[str] = []
    out = _aggregate_chat_stream(
        iter([_chunk("Hel"), _chunk("lo")]),
        threading.Event(), CallProgress(), pieces.append,
    )
    assert pieces == ["Hel", "lo"]
    assert out["choices"][0]["message"]["content"] == "Hello"


def test_aggregator_partial_stream_recovery_text_only():
    import threading
    from jaeger_ai.agent.adapters.openai import _aggregate_chat_stream
    from jaeger_ai.agent.loop.interrupt import CallProgress
    from types import SimpleNamespace

    def _chunk(text):
        delta = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=None)],
            usage=None,
        )

    def _dying_stream():
        yield _chunk("The answer is forty-")
        yield _chunk("two")
        raise ConnectionError("tcp reset mid-stream")

    out = _aggregate_chat_stream(
        _dying_stream(), threading.Event(), CallProgress(),
    )
    msg = out["choices"][0]["message"]
    assert msg["content"] == "The answer is forty-two"
    assert out["choices"][0]["finish_reason"] == "partial_stream"


def test_aggregator_partial_with_tool_call_in_flight_reraises():
    import threading
    from jaeger_ai.agent.adapters.openai import _aggregate_chat_stream
    from jaeger_ai.agent.loop.interrupt import CallProgress
    from types import SimpleNamespace

    def _tool_chunk():
        tc = SimpleNamespace(
            index=0, id="c1",
            function=SimpleNamespace(name="write_file", arguments='{"pa'),
        )
        delta = SimpleNamespace(content=None, tool_calls=[tc])
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=None)],
            usage=None,
        )

    def _dying_stream():
        yield _tool_chunk()
        raise ConnectionError("tcp reset mid tool call")

    with pytest.raises(ConnectionError):
        _aggregate_chat_stream(
            _dying_stream(), threading.Event(), CallProgress(),
        )


# ── tail pass: file-mutation verifier footer ───────────────────────


def test_failed_mutation_appends_verifier_footer():
    def _fail_write(value: str = "x") -> dict:
        return {"ok": False, "error": "disk full"}

    register_tool_instance(ToolDef(
        name="write_file", description="w", args_model=_Args, fn=_fail_write,
    ))
    adapter = _ScriptedAdapter([
        _assistant_call(_tc("write_file", "notes.txt")),
        {"role": "assistant", "content": "Done! I've updated notes.txt."},
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("update my notes")
    assert "file-ops warning" in answer
    assert "write_file" in answer


def test_superseded_mutation_failure_no_footer():
    flaky = iter([{"ok": False, "error": "locked"}, {"ok": True}])

    def _write(value: str = "x") -> dict:
        return next(flaky)

    register_tool_instance(ToolDef(
        name="write_file", description="w", args_model=_Args, fn=_write,
    ))
    same = lambda: _assistant_call(  # noqa: E731
        {"id": "", "name": "write_file", "arguments": {"value": "notes"}})
    adapter = _ScriptedAdapter([
        same(), same(),
        {"role": "assistant", "content": "Saved."},
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("save it")
    assert "file-ops warning" not in answer


# ── tail pass: thinking exhaustion ─────────────────────────────────


def test_thinking_exhausted_surfaces_plainly_no_retry():
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "finish_reason": "thinking_exhausted"},
        {"role": "assistant", "content": "should never be requested"},
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("hard question")
    assert "output budget" in answer
    assert agent.last_halt_reason == "thinking_exhausted"
    assert adapter.call_count == 1  # no nudge, no continuation retries


def test_local_parse_tags_thinking_exhaustion():
    from jaeger_ai.agent import LocalLlamaAdapter

    class _FakeLlama:
        def create_chat_completion(self, **kwargs):
            return {}

    a = LocalLlamaAdapter(llama=_FakeLlama())
    raw = {"choices": [{
        "message": {"role": "assistant",
                    "content": "<think>hmm this is hard and I keep going"},
        "finish_reason": "length",
    }]}
    msg = a.parse_response(raw)
    assert msg.get("finish_reason") == "thinking_exhausted"
    assert not (msg.get("content") or "").strip()


# ── tail pass: reactive compact-on-overflow ────────────────────────


class _ServerOverflowError(Exception):
    status_code = 400


def test_server_overflow_tightens_estimator_and_retries_same_adapter():
    guard = ContextGuard(ContextBudget(ctx_window=8192))
    ratio_before = guard._ratio
    primary = _ScriptedAdapter([
        _ServerOverflowError(
            "the number of tokens to keep is greater than the context length"
        ),
        {"role": "assistant", "content": "fits now"},
    ])
    backup = _ScriptedAdapter([{"role": "assistant", "content": "fallback"}])
    agent = JaegerAgent(
        adapter=primary, fallback_adapters=[backup], context_guard=guard,
    )
    answer = agent.run_turn("hello")
    assert answer == "fits now"
    assert primary.call_count == 2      # retried SAME adapter
    assert backup.call_count == 0       # never walked the chain
    assert guard._ratio < ratio_before  # estimator actually tightened
