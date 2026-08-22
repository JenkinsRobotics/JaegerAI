"""Lossy compaction of old tool JSON once the window is ~80% full."""

from __future__ import annotations

from jaeger_ai.core.runtime.context_compactor import (
    DIGEST_TAG,
    compact_messages,
    estimate_tokens,
    should_compact,
)
from jaeger_ai.core.runtime.work_ledger import LEDGER_TAG


def _tool(name: str, body: str, call_id: str = "c1") -> dict:
    return {
        "role": "tool", "name": name, "tool_call_id": call_id,
        "content": body,
    }


def _history(n: int, payload: str = "x" * 200) -> list[dict]:
    messages: list[dict] = []
    for i in range(n):
        messages.append({"role": "user", "content": f"do item {i}"})
        messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{i}", "name": "read_file",
                            "arguments": {"path": f"{i}.txt"}}],
        })
        messages.append(_tool("read_file", payload, call_id=f"c{i}"))
        messages.append({"role": "assistant", "content": f"did {i}"})
    return messages


def test_under_threshold_is_a_noop():
    messages = _history(2, payload="short")
    out = compact_messages(messages, ctx_window=100_000)
    assert out == messages


def test_over_threshold_keeps_last_two_turns_and_digests_the_rest():
    messages = _history(6, payload="JSON " * 400)
    assert should_compact(messages, ctx_window=800)
    out = compact_messages(
        messages, ctx_window=800, keep_turns=2,
        ledger_text=f"{LEDGER_TAG}\nprogress: 4/6",
    )
    digest = [m for m in out if DIGEST_TAG in str(m.get("content") or "")]
    assert digest, out
    assert "4/6" in digest[0]["content"]
    # Last two user turns survive verbatim.
    users = [m["content"] for m in out if m.get("role") == "user"
             and DIGEST_TAG not in str(m.get("content") or "")]
    assert users[-2:] == ["do item 4", "do item 5"]
    # Older raw tool JSON is gone.
    old_tools = [
        m for m in out
        if m.get("role") == "tool" and "do item 0" in str(m)
    ]
    assert old_tools == []


def test_system_and_ledger_messages_are_preserved():
    messages = (
        [{"role": "system", "content": "you are the agent"}]
        + [{"role": "user", "content": f"{LEDGER_TAG}\ntask: notes"}]
        + _history(5, payload="y" * 800)
    )
    out = compact_messages(messages, ctx_window=500, keep_turns=2)
    assert out[0]["role"] == "system"
    assert any(LEDGER_TAG in str(m.get("content") or "") for m in out)


def test_estimator_grows_with_tool_payloads():
    small = estimate_tokens(_history(1, payload="a"))
    big = estimate_tokens(_history(1, payload="a" * 3000))
    assert big > small
