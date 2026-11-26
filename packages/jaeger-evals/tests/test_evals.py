"""Tests for standalone jaeger-evals package."""

from __future__ import annotations

from jaeger_evals import SpanTree, TraceSpan, verify_compaction_integrity


def test_span_tree_and_compaction_verifier() -> None:
    tree = SpanTree([
        TraceSpan(
            name="turn",
            kind="model",
            children=[
                TraceSpan(name="read_file", kind="tool", ok=True),
                TraceSpan(name="edit_file", kind="tool", ok=True),
                TraceSpan(name="run_tests", kind="tool", ok=True),
            ],
        )
    ])
    assert tree.has_tool_call("edit_file") is True
    assert tree.tool_sequence_contains(["read_file", "run_tests"]) is True
    assert tree.error_count() == 0

    ver = verify_compaction_integrity(
        [{"content": "Goal: ship YouTube Ep 1 under 32GB budget " + ("x" * 200)}],
        [{"content": "Summary: Goal ship YouTube Ep 1 under 32GB budget."}],
        required_anchors=["YouTube Ep 1", "32GB budget"],
    )
    assert ver.passed is True and ver.compression_ratio < 0.5
