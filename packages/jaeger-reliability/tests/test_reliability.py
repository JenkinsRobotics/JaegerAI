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
