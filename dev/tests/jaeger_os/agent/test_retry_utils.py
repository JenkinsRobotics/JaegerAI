"""Phase-8 retry utilities — jittered backoff + retry-with-backoff."""

from __future__ import annotations

import time

import pytest

from jaeger_os.agent import jittered_backoff, retry_with_backoff


# ── jittered_backoff ───────────────────────────────────────────────


def test_first_attempt_starts_at_base_delay():
    """Attempt 1 yields ``base_delay`` plus some jitter — within the
    expected range."""
    delays = [
        jittered_backoff(1, base_delay=2.0, max_delay=10.0, jitter_ratio=0.5)
        for _ in range(20)
    ]
    # Pre-jitter delay is exactly 2.0; jitter is uniform [0, 1.0].
    for d in delays:
        assert 2.0 <= d <= 3.0


def test_doubles_per_attempt():
    """Attempt N uses ``base * 2^(N-1)`` before jitter."""
    pre_jitter_at = lambda n: 2.0 * (2 ** (n - 1))  # noqa: E731
    for attempt in (1, 2, 3, 4):
        samples = [
            jittered_backoff(attempt, base_delay=2.0, max_delay=1e6, jitter_ratio=0.0)
            for _ in range(5)
        ]
        for s in samples:
            assert s == pytest.approx(pre_jitter_at(attempt))


def test_max_delay_caps_growth():
    """No attempt exceeds ``max_delay + jitter_ratio * max_delay``."""
    for attempt in (10, 50, 100):
        delay = jittered_backoff(
            attempt, base_delay=5.0, max_delay=60.0, jitter_ratio=0.5,
        )
        # Pre-jitter ≤ 60; jitter ≤ 30; sum ≤ 90.
        assert delay <= 90.0


def test_jitter_ratio_zero_returns_deterministic_delay():
    """With ``jitter_ratio=0`` the function is deterministic — useful
    for tests pinning the timing curve."""
    a = jittered_backoff(3, base_delay=1.0, jitter_ratio=0.0)
    b = jittered_backoff(3, base_delay=1.0, jitter_ratio=0.0)
    assert a == b


def test_decorrelates_concurrent_callers():
    """Two back-to-back calls produce different jitter samples even
    when the system clock barely moves."""
    samples = [
        jittered_backoff(2, base_delay=10.0, jitter_ratio=0.5)
        for _ in range(50)
    ]
    # Vast majority should be unique values — duplicates indicate a
    # broken seed.
    assert len(set(samples)) > 30


def test_zero_or_negative_base_delay_clamps_to_max():
    """Defensive: a misconfigured ``base_delay <= 0`` shouldn't make
    the function return zero or negative delays."""
    delay = jittered_backoff(3, base_delay=0.0, max_delay=30.0)
    # Floors to max_delay + some jitter.
    assert delay >= 30.0


def test_huge_attempt_does_not_overflow():
    """A bug previously surfaced via ``2 ** 1000`` overflowing — we
    cap exponent at 63 to keep results finite."""
    delay = jittered_backoff(1000, base_delay=1.0, max_delay=10.0)
    assert delay < 20.0  # capped by max_delay + jitter


# ── retry_with_backoff ─────────────────────────────────────────────


def test_returns_immediately_on_success():
    calls = {"n": 0}

    def _fn():
        calls["n"] += 1
        return "ok"

    out = retry_with_backoff(_fn, max_attempts=3, base_delay=0.001)
    assert out == "ok"
    assert calls["n"] == 1


def test_retries_until_success():
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "settled"

    out = retry_with_backoff(
        _flaky, max_attempts=5, base_delay=0.001, max_delay=0.01,
    )
    assert out == "settled"
    assert calls["n"] == 3


def test_reraises_after_exhausting_attempts():
    calls = {"n": 0}

    def _always_fails():
        calls["n"] += 1
        raise RuntimeError(f"bust {calls['n']}")

    with pytest.raises(RuntimeError, match="bust 3"):
        retry_with_backoff(
            _always_fails, max_attempts=3, base_delay=0.001, max_delay=0.01,
        )
    assert calls["n"] == 3


def test_retry_on_only_catches_listed_exceptions():
    """Exceptions not in ``retry_on`` propagate immediately — important
    so terminal errors (bad API key, schema bug) surface fast."""
    def _bad_key():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry_with_backoff(
            _bad_key, max_attempts=3, base_delay=0.001,
            retry_on=(TimeoutError,),  # ValueError NOT in list
        )


def test_on_retry_callback_fires_before_each_sleep():
    seen: list[int] = []

    def _flaky():
        if len(seen) < 2:
            raise RuntimeError("retry me")
        return "ok"

    def _on_retry(attempt, exc, delay):  # noqa: ARG001
        seen.append(attempt)

    retry_with_backoff(
        _flaky, max_attempts=5, base_delay=0.001, max_delay=0.01,
        on_retry=_on_retry,
    )
    # 2 failures → 2 retry callbacks (3rd attempt succeeds).
    assert seen == [1, 2]


def test_on_retry_exception_does_not_break_retry():
    """A buggy logging hook must NEVER break the retry chain."""
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("retry")
        return "ok"

    def _broken_retry_cb(_attempt, _exc, _delay):
        raise RuntimeError("logger broke")

    out = retry_with_backoff(
        _flaky, max_attempts=3, base_delay=0.001,
        on_retry=_broken_retry_cb,
    )
    assert out == "ok"


# ── Anthropic prompt-cache upgrade ─────────────────────────────────


def test_anthropic_cache_markers_cover_last_three_messages():
    """The Phase-8 cache pattern marks system + the trailing 3
    messages so multi-tool sequences hit cache on the next round."""
    from jaeger_os.agent import AnthropicAdapter

    a = AnthropicAdapter(
        api_key="x", prompt_caching=True,
        client=object(),  # never invoked — format_messages is the only path under test
    )
    out = a.format_messages(
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
        ],
        tools=[],
        system="be brief",
    )
    # System wrapped with cache_control.
    assert isinstance(out["system"], list)
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Last 3 messages each carry a cache_control marker.
    last_three = out["messages"][-3:]
    for msg in last_three:
        content = msg["content"]
        # Cache marker lives on the last block of the message body.
        assert isinstance(content, list)
        assert content[-1].get("cache_control") == {"type": "ephemeral"}


def test_anthropic_cache_handles_fewer_than_three_messages():
    """If the conversation is short, mark whatever messages exist
    without raising."""
    from jaeger_os.agent import AnthropicAdapter

    a = AnthropicAdapter(
        api_key="x", prompt_caching=True, client=object(),
    )
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="x",
    )
    # The single user message is marked.
    only_msg = out["messages"][0]
    content = only_msg["content"]
    assert isinstance(content, list)
    assert content[-1].get("cache_control") == {"type": "ephemeral"}
