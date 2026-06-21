"""Phase-8 liveness instrumentation — stale-call detector + heartbeat.

The heartbeat surfaces "still working" status to the TUI / gateway
while the model is generating; the stale detector trips when a
provider's socket is open but no bytes are flowing, so the
adapter-fallback chain can react in ~30s instead of waiting out the
SDK's full timeout.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.agent import (
    AgentCallbacks,
    JaegerAgent,
    ProviderAdapter,
    StaleCallTimeout,
    clear_registry,
    interruptible_call,
)


# ── interruptible_call: stale + heartbeat ──────────────────────────


def test_stale_timeout_fires_when_call_hangs():
    """The wrapped call sleeps forever; the detector raises after the
    timeout passes."""
    ev = threading.Event()

    def _hang() -> str:
        time.sleep(5.0)
        return "should not reach"

    with pytest.raises(StaleCallTimeout, match="no progress for"):
        interruptible_call(
            _hang, ev, poll_interval=0.05, stale_timeout=0.3,
        )


def test_no_stale_timeout_when_call_returns_fast():
    """Fast call: stale_timeout never fires."""
    ev = threading.Event()
    out = interruptible_call(
        lambda: 42, ev, poll_interval=0.01, stale_timeout=1.0,
    )
    assert out == 42


def test_stale_timeout_none_means_unbounded():
    """Stale-timeout=None disables the detector — long calls succeed."""
    ev = threading.Event()

    def _slow() -> str:
        time.sleep(0.3)
        return "done"

    out = interruptible_call(_slow, ev, poll_interval=0.05, stale_timeout=None)
    assert out == "done"


def test_heartbeat_fires_during_call_and_reports_elapsed():
    """Heartbeat ticks during in-flight calls; elapsed_s grows on
    each tick."""
    ev = threading.Event()
    ticks: list[float] = []

    def _slow() -> str:
        time.sleep(0.35)
        return "done"

    out = interruptible_call(
        _slow, ev, poll_interval=0.05,
        on_heartbeat=lambda elapsed: ticks.append(elapsed),
    )
    assert out == "done"
    # Several heartbeats fired; the last is approximately 0.35s.
    assert len(ticks) >= 3
    assert ticks[0] < ticks[-1]
    assert ticks[-1] >= 0.2


def test_heartbeat_exception_does_not_break_call():
    """A buggy heartbeat callback must NEVER break the wrapped call."""
    ev = threading.Event()

    def _slow() -> str:
        time.sleep(0.15)
        return "done"

    def _broken(_elapsed):
        raise RuntimeError("heartbeat bug")

    out = interruptible_call(
        _slow, ev, poll_interval=0.05, on_heartbeat=_broken,
    )
    assert out == "done"


def test_interrupt_still_wins_over_stale_timeout():
    """When the interrupt event fires before stale_timeout, raise
    AgentInterrupted — operator cancel takes priority over the hang
    detector."""
    from jaeger_os.agent import AgentInterrupted

    ev = threading.Event()

    def _hang() -> str:
        time.sleep(5.0)
        return ""

    def _set_interrupt():
        time.sleep(0.1)
        ev.set()

    threading.Thread(target=_set_interrupt, daemon=True).start()
    with pytest.raises(AgentInterrupted):
        interruptible_call(_hang, ev, poll_interval=0.02, stale_timeout=2.0)


# ── JaegerAgent integration ────────────────────────────────────────


class _SlowAdapter(ProviderAdapter):
    """Sleeps for ``hang_for`` seconds in ``call``; tracks
    ``stale_timeout`` and ``on_heartbeat`` kwargs received."""

    name = "slow"

    def __init__(self, hang_for: float = 0.0) -> None:
        self.hang_for = hang_for
        self.last_stale_timeout: float | None | object = object()
        self.last_on_heartbeat: object | None = object()

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, *,
             stale_timeout=None, on_heartbeat=None, **kwargs):  # noqa: ARG002
        self.last_stale_timeout = stale_timeout
        self.last_on_heartbeat = on_heartbeat
        if self.hang_for:
            time.sleep(self.hang_for)
        # Forward calls to the heartbeat so the activity timestamp updates.
        if on_heartbeat is not None:
            on_heartbeat(0.05)
        return {"role": "assistant", "content": "ok"}

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def test_agent_threads_stale_timeout_through_to_adapter():
    """``JaegerAgent.stale_call_timeout_s`` reaches the adapter."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("hi")
    assert adapter.last_stale_timeout == agent.stale_call_timeout_s


def test_agent_threads_heartbeat_callback_through_to_adapter():
    """A user-supplied heartbeat callback flows from
    ``AgentCallbacks.heartbeat`` to the adapter's ``on_heartbeat`` arg."""
    ticks: list[float] = []
    cb = AgentCallbacks(heartbeat=lambda e: ticks.append(e))
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("hi")
    # The adapter forwarded the heartbeat once during call.
    assert ticks == [0.05]


def test_agent_last_activity_ts_updates_on_heartbeat():
    """The agent's ``last_activity_ts`` is touched by every heartbeat
    so the TUI / gateway can read 'last seen' time."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    before = time.time()
    agent.run_turn("hi")
    after = time.time()
    assert before <= agent.last_activity_ts <= after
    assert "model" in agent.last_activity_desc


def test_touch_activity_updates_timestamp_and_description():
    """The public ``touch_activity`` lets tools and callbacks signal
    progress between model calls."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.touch_activity("downloading model from hub")
    assert agent.last_activity_desc == "downloading model from hub"
    assert agent.last_activity_ts > 0


def test_stale_timeout_disabled_when_set_to_none():
    """Setting ``stale_call_timeout_s = None`` on the agent passes
    ``None`` to the adapter, disabling the detector."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.stale_call_timeout_s = None
    agent.run_turn("hi")
    assert adapter.last_stale_timeout is None


def test_stale_timeout_triggers_fallback_chain():
    """When the primary hangs past stale_timeout, the agent moves on
    to the next fallback adapter without raising to the caller."""
    primary = _SlowAdapter(hang_for=0.6)  # will trip the detector
    backup = _SlowAdapter(hang_for=0.0)
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup])
    agent.stale_call_timeout_s = 0.2
    result = agent.run_turn("hi")
    # Backup served the response.
    assert result == "ok"


def test_accumulate_usage_extracts_openai_shape():
    """OpenAI / llama-cpp put token usage under ``raw["usage"]`` with
    ``prompt_tokens`` / ``completion_tokens``. The agent must
    accumulate these so the bench can report real throughput."""
    agent = JaegerAgent(adapter=_SlowAdapter())
    agent._accumulate_usage({
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    })
    assert agent.last_prompt_tokens == 100
    assert agent.last_completion_tokens == 20


def test_accumulate_usage_extracts_anthropic_shape():
    """Anthropic puts the same data under ``input_tokens`` /
    ``output_tokens``. The helper must handle both names."""
    agent = JaegerAgent(adapter=_SlowAdapter())
    agent._accumulate_usage({
        "content": [{"type": "text", "text": "hi"}],
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    assert agent.last_prompt_tokens == 50
    assert agent.last_completion_tokens == 10


def test_accumulate_usage_sums_across_iterations():
    """A multi-step turn racks up multiple model calls — the counts
    must accumulate, not overwrite."""
    agent = JaegerAgent(adapter=_SlowAdapter())
    agent._accumulate_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    agent._accumulate_usage({"usage": {"prompt_tokens": 110, "completion_tokens": 5}})
    assert agent.last_prompt_tokens == 210
    assert agent.last_completion_tokens == 25


def test_accumulate_usage_silently_skips_missing_field():
    """An adapter that doesn't report usage must not break anything
    — the helper just no-ops and the bench falls back to the
    whitespace estimate."""
    agent = JaegerAgent(adapter=_SlowAdapter())
    agent._accumulate_usage({"choices": []})       # no usage key
    agent._accumulate_usage("not even a dict")     # type: ignore
    agent._accumulate_usage({"usage": "wrong type"})
    assert agent.last_prompt_tokens == 0
    assert agent.last_completion_tokens == 0


def test_accumulate_usage_resets_at_start_of_run_turn():
    """Each call to ``run_turn`` starts fresh; previous turns'
    token counts must not carry over."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.last_prompt_tokens = 999
    agent.last_completion_tokens = 999
    agent.run_turn("hi")
    # _SlowAdapter doesn't report usage → both stay 0 after reset.
    assert agent.last_prompt_tokens == 0
    assert agent.last_completion_tokens == 0


class _StallingAdapter:
    """Adapter that synchronously raises ``StaleCallTimeout`` on
    every call — simulates an adapter whose ``interruptible_call``
    inner wrapper tripped its watchdog. ``_SlowAdapter`` above
    doesn't actually raise (it just sleeps), so it can't exercise
    the loop's ``except StaleCallTimeout`` branch."""

    name = "stalling"

    def __init__(self, *, returns: dict | None = None) -> None:
        self.returns = returns  # None ⇒ raise; dict ⇒ return normally

    def describe(self) -> str:
        return "stalling-adapter"

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, *,
             stale_timeout=None, on_heartbeat=None, **kwargs):  # noqa: ARG002
        if self.returns is None:
            raise StaleCallTimeout(
                f"no response after {(stale_timeout or 0):.1f}s (test)"
            )
        return self.returns

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


def test_stale_timeout_sets_stalled_halt_reason_when_chain_exhausted():
    """When EVERY adapter in the chain raises StaleCallTimeout, the
    loop must surface a clean ``stalled`` halt reason rather than
    letting the exception escape as a generic crash. This is the
    user-facing recovery signal — the TUI / latency log distinguishes
    'model stalled' from 'something exploded' on this."""
    primary = _StallingAdapter()
    backup = _StallingAdapter()
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup])
    agent.stale_call_timeout_s = 0.1
    with pytest.raises(StaleCallTimeout):
        agent.run_turn("hi")
    assert agent.last_halt_reason == "stalled"


def test_stalled_message_mentions_recovery_path():
    """The thinking callback emitted on stall must reference the
    ``jaeger kill`` recovery instructions so a non-expert user knows
    what to do when the model hangs."""
    seen_thoughts: list[str] = []
    cb = AgentCallbacks(thinking=lambda s: seen_thoughts.append(s))
    # Primary stalls, backup returns ok — the loop continues past
    # the primary, but the thinking callback still emits the stall
    # notice. That's the visible signal in the TUI.
    primary = _StallingAdapter()
    backup = _StallingAdapter(returns={"role": "assistant", "content": "ok"})
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup],
                       callbacks=cb)
    agent.stale_call_timeout_s = 0.1
    result = agent.run_turn("hi")
    assert result == "ok"
    stall_messages = [s for s in seen_thoughts if "stalled" in s.lower()]
    assert stall_messages, "expected a 'stalled' notice in the thinking stream"
    assert "jaeger kill" in stall_messages[0]


# ── progress-aware stale detection ─────────────────────────────────


def test_progress_touches_keep_long_healthy_call_alive():
    """A call whose worker reports progress (chunks/tokens flowing)
    must survive a stale_timeout shorter than its total duration —
    'stale' means silence, not slowness."""
    from jaeger_os.agent.loop.interrupt import CallProgress

    ev = threading.Event()
    prog = CallProgress()

    def _slow_but_alive() -> str:
        for _ in range(8):
            time.sleep(0.1)   # total 0.8s, well past the 0.3s cap
            prog.touch()
        return "finished"

    out = interruptible_call(
        _slow_but_alive, ev,
        poll_interval=0.02, stale_timeout=0.3, progress=prog,
    )
    assert out == "finished"


def test_progress_silence_still_trips_stale():
    """With a progress beacon attached, a worker that STOPS reporting
    progress trips the detector after the quiet period."""
    from jaeger_os.agent.loop.interrupt import CallProgress

    ev = threading.Event()
    prog = CallProgress()

    def _goes_quiet() -> str:
        prog.touch()
        time.sleep(5.0)       # silence — no more touches
        return "should not reach"

    with pytest.raises(StaleCallTimeout, match="no progress for"):
        interruptible_call(
            _goes_quiet, ev,
            poll_interval=0.02, stale_timeout=0.3, progress=prog,
        )
