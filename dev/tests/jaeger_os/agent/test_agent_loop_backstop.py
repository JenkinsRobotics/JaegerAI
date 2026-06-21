"""Loop-backstop helpers — unit tests, no agent loop, no adapter.

These are the safety-net counters that guarantee a turn terminates. The
thresholds and signatures match the pre-refactor pydantic-ai loop in
``main.py`` so the benchmark suite can compare apples to apples.
"""

from __future__ import annotations

from jaeger_os.agent.loop.loop_backstop import (
    MAX_IDENTICAL_CALLS,
    MAX_SEMANTIC_FAILURES,
    MAX_TOOL_CALLS,
    call_signature,
    loop_halt_reason,
    semantic_failure_signature,
)


# ── call_signature ─────────────────────────────────────────────────


def test_call_signature_is_stable_per_tool_and_args():
    a = call_signature("get_time", {"timezone": "UTC"})
    b = call_signature("get_time", {"timezone": "UTC"})
    assert a == b


def test_call_signature_changes_when_args_differ():
    a = call_signature("get_time", {"timezone": "UTC"})
    b = call_signature("get_time", {"timezone": "PST"})
    assert a != b


# ── semantic_failure_signature ─────────────────────────────────────


def test_semantic_failure_signature_returns_none_on_success():
    assert semantic_failure_signature("x", {}, {"ok": True}) is None
    assert semantic_failure_signature("x", {}, {"ok": True, "stderr": ""}) is None


def test_semantic_failure_signature_returns_none_when_no_error_field():
    assert semantic_failure_signature("x", {}, {"ok": False}) is None


def test_semantic_failure_signature_normalizes_irrelevant_arg_drift():
    """Same tool + same target + same first-line error == same signature,
    even when other args drift. That's the whole point — a model can't
    escape the backstop by jiggling unrelated parameters."""
    sig1 = semantic_failure_signature(
        "write_file",
        {"path": "/tmp/x.py", "content": "v1"},
        {"ok": False, "error": "permission denied"},
    )
    sig2 = semantic_failure_signature(
        "write_file",
        {"path": "/tmp/x.py", "content": "v2-totally-different"},
        {"ok": False, "error": "permission denied\n\nfull trace…"},
    )
    assert sig1 == sig2
    assert "write_file" in sig1


def test_semantic_failure_signature_uses_code_hash_when_no_path():
    """Repeated ``run_python`` failures with the same code body collide
    to one signature; different code yields different signatures."""
    sig_a = semantic_failure_signature(
        "run_python",
        {"code": "1/0"},
        {"ok": False, "stderr": "ZeroDivisionError"},
    )
    sig_b = semantic_failure_signature(
        "run_python",
        {"code": "1/0"},
        {"ok": False, "stderr": "ZeroDivisionError"},
    )
    sig_c = semantic_failure_signature(
        "run_python",
        {"code": "import sys"},
        {"ok": False, "stderr": "ZeroDivisionError"},
    )
    assert sig_a == sig_b
    assert sig_a != sig_c


# ── loop_halt_reason ───────────────────────────────────────────────


def test_loop_halt_reason_returns_none_when_healthy():
    assert loop_halt_reason(5, {"x|{}": 1}, {}) is None


def test_loop_halt_reason_fires_on_identical_calls():
    counts = {"foo|{}": MAX_IDENTICAL_CALLS}
    reason = loop_halt_reason(MAX_IDENTICAL_CALLS, counts, {})
    assert reason is not None
    assert "foo" in reason
    assert "identical" in reason


def test_loop_halt_reason_fires_on_runaway_total():
    counts = {f"t{i}|{{}}": 1 for i in range(MAX_TOOL_CALLS + 1)}
    reason = loop_halt_reason(MAX_TOOL_CALLS + 1, counts, {})
    assert reason is not None
    assert str(MAX_TOOL_CALLS + 1) in reason


def test_loop_halt_reason_fires_on_semantic_failures():
    failures = {"write_file|/tmp/x|permission denied": MAX_SEMANTIC_FAILURES}
    reason = loop_halt_reason(2, {}, failures)
    assert reason is not None
    assert "write_file" in reason
    assert "failure" in reason


def test_loop_halt_reason_prefers_failure_message_over_identical():
    """When both backstops would trip, the failure message is more
    actionable — name it first."""
    counts = {"foo|{}": MAX_IDENTICAL_CALLS}
    failures = {"foo||boom": MAX_SEMANTIC_FAILURES}
    reason = loop_halt_reason(MAX_IDENTICAL_CALLS, counts, failures)
    assert reason is not None
    assert "failure" in reason
