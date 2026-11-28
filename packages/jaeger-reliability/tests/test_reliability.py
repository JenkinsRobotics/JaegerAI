"""Standalone tests for jaeger-reliability."""

from __future__ import annotations

import pytest

from jaeger_contracts import ReliabilityPort
from jaeger_reliability import (
    CredentialPool,
    FailoverReason,
    ReliabilityEngine,
    retry_stream_zero_event_safe,
)


def test_reliability_engine_protocol_and_error_classification() -> None:
    eng = ReliabilityEngine()
    assert isinstance(eng, ReliabilityPort)
    assert eng.classify_error(RuntimeError("HTTP 429 Too Many Requests")) == FailoverReason.RATE_LIMIT.value
    assert eng.classify_error(RuntimeError("413 context_length_exceeded")) == FailoverReason.CONTEXT_OVERFLOW.value
    assert eng.classify_error(RuntimeError("401 Invalid API Key")) == FailoverReason.AUTH.value
    assert eng.classify_error(TimeoutError("upstream timed out")) == FailoverReason.TRANSIENT.value

    class _StatusErr(Exception):
        def __init__(self, status_code: int, msg: str = "") -> None:
            super().__init__(msg)
            self.status_code = status_code

    assert eng.classify_error(_StatusErr(404, "model missing")) == FailoverReason.NOT_FOUND.value
    assert eng.classify_error(_StatusErr(402, "payment required")) == FailoverReason.QUOTA.value
    assert eng.classify_error(_StatusErr(429, "insufficient_quota")) == FailoverReason.QUOTA.value
    assert eng.classify_error(_StatusErr(503, "overloaded")) == FailoverReason.TRANSIENT.value


def test_credential_pool_rotates_and_respects_cooldown() -> None:
    now = [100.0]
    pool = CredentialPool(["k1", "k2"], clock=lambda: now[0])
    assert pool.acquire() == "k1"
    pool.mark_failed("k1", cooldown_s=60.0)
    assert pool.acquire() == "k2"
    assert pool.acquire() == "k2"  # k1 still cooling down
    now[0] += 65.0
    assert pool.acquire() == "k1"  # recovered


def test_zero_event_safe_streaming_retry() -> None:
    attempts = [0]

    def fail_before_emit():
        attempts[0] += 1
        if attempts[0] < 3:
            raise TimeoutError("connection timed out")
        yield "ok-chunk"

    assert list(retry_stream_zero_event_safe(fail_before_emit, max_attempts=3)) == ["ok-chunk"]
    assert attempts[0] == 3

    # Once a chunk IS emitted, MUST NOT retry (prevents corrupted merged stream)
    partial_attempts = [0]

    def fail_mid_stream():
        partial_attempts[0] += 1
        yield "partial"
        raise TimeoutError("connection timed out mid-stream")

    with pytest.raises(TimeoutError):
        list(retry_stream_zero_event_safe(fail_mid_stream, max_attempts=3))
    assert partial_attempts[0] == 1


def test_deterministic_argument_repair_and_loop_detection() -> None:
    eng = ReliabilityEngine(repeat_threshold=3)
    schema = {
        "properties": {
            "count": {"type": "integer"},
            "dry_run": {"type": "boolean"},
            "paths": {"type": "array"},
        }
    }
    raw = "```json\n{'count': '42', 'dry_run': 'true', 'paths': '[\"a.py\", \"b.py\"]'}\n```"
    repaired = eng.repair_arguments("edit_file", raw, schema)
    assert repaired == {"count": 42, "dry_run": True, "paths": ["a.py", "b.py"]}

    # Identical consecutive loop
    assert eng.check_loop([{"tool": "shell", "arguments": {"cmd": "ls"}}] * 3) is True
    # ABAB oscillating loop
    assert eng.check_loop([
        {"tool": "read_file", "arguments": {"path": "a.py"}},
        {"tool": "edit_file", "arguments": {"path": "a.py"}},
        {"tool": "read_file", "arguments": {"path": "a.py"}},
        {"tool": "edit_file", "arguments": {"path": "a.py"}},
    ]) is True
    # Normal progression
    assert eng.check_loop([
        {"tool": "read_file", "arguments": {"path": "a.py"}},
        {"tool": "edit_file", "arguments": {"path": "a.py"}},
        {"tool": "shell", "arguments": {"cmd": "pytest"}},
    ]) is False


def test_detailed_classification_retry_after_and_x_should_retry() -> None:
    from jaeger_reliability import classify_error_detailed, retry_call, sanitize_property_key, unrename_tool_args

    class _HeaderErr(Exception):
        def __init__(self, status_code: int, headers: dict[str, str]) -> None:
            super().__init__(f"HTTP {status_code}")
            self.status_code = status_code
            self.headers = headers

    d_forbid = classify_error_detailed(_HeaderErr(429, {"x-should-retry": "false"}))
    assert d_forbid.provider_forbids_retry is True and d_forbid.retryable is False

    d_ra = classify_error_detailed(_HeaderErr(429, {"Retry-After": "1.5"}))
    assert d_ra.retryable is True and d_ra.retry_after_s == 1.5

    sleeps: list[float] = []
    calls = [0]

    def flaky() -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise _HeaderErr(429, {"Retry-After": "0.25"})
        return "recovered"

    assert retry_call(flaky, attempts=3, sleep_fn=sleeps.append) == "recovered"
    assert sleeps == [0.25]

    k = sanitize_property_key("foo.bar/baz")
    assert k == "foo_bar_baz"
    assert unrename_tool_args({k: 7}, {k: "foo.bar/baz"}) == {"foo.bar/baz": 7}
