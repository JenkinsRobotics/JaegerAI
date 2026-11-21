"""Deterministic, read-only audit of the immediately preceding chat turn."""
from __future__ import annotations

import re
from typing import Any


def is_previous_turn_audit(text: str) -> bool:
    """Match only an explicit self/previous-turn metrics request.

    A generic request containing ``audit`` must still reach the agent.  This
    route is intentionally narrow so it cannot become a hidden intent router.
    """
    body = " ".join(str(text or "").casefold().split())
    if not body or len(body) > 700:
        return False
    previous = bool(re.search(
        r"\b(previous|last|immediately previous)\s+(failed\s+)?(request|turn|reply|response)\b"
        r"|\b(you|u)\s+(used|took)\b|\bit took (you|u)\b",
        body,
    ))
    metrics = bool(re.search(r"\b(tool|tools|steps?|passes|calls?|time|duration|elapsed|model|provider)\b", body))
    ask = bool(re.search(r"\b(audit|report|show|tell|how many|how long)\b", body))
    return previous and metrics and ask


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value) if int(value) == value else None


def previous_turn_audit(store: Any, session_id: str, current_request_id: str) -> str:
    row = store.previous_terminal_request(
        session_id, before_request_id=current_request_id,
    )
    if row is None:
        return "Previous request audit: no earlier terminal Gateway receipt is available in this conversation."

    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
    execution = row.get("execution") if isinstance(row.get("execution"), dict) else {}
    tool_rows = timing.get("tool_calls") if isinstance(timing.get("tool_calls"), list) else []
    tools = [str(item.get("name")) for item in tool_rows if isinstance(item, dict) and item.get("name")]
    if not tools:
        tools = list(store.request_tool_names(session_id, row["request_id"]))

    tool_count = _nonnegative_int(timing.get("tool_call_count"))
    if tool_count is None and tools:
        tool_count = len(tools)
    model_count = _nonnegative_int(timing.get("model_call_count"))
    steps = _nonnegative_int(timing.get("continuation_step_count"))
    if steps is None:
        steps = _nonnegative_int(result.get("continuation_steps"))
    elapsed = timing.get("turn_finish_ms")
    elapsed_text = f"{float(elapsed) / 1000:.3f} seconds" if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0 else "unavailable"
    model = result.get("actual_model") or result.get("model") or execution.get("model") or "unavailable"
    provider = execution.get("provider") or result.get("backend") or "unavailable"
    error = result.get("error") or result.get("halt_reason") or timing.get("halt_reason") or "none recorded"
    partial = result.get("partial_output") or result.get("output")
    partial_text = str(partial).strip() if isinstance(partial, str) else ""

    lines = [
        "Previous request audit (durable Gateway receipt):",
        f"- Request ID: {row['request_id']}",
        f"- Terminal state: {row['status']}",
        f"- Model/provider: {model} / {provider}",
        f"- Model calls: {model_count if model_count is not None else 'unavailable'}",
        f"- Tool calls: {tool_count if tool_count is not None else 'unavailable'}",
        f"- Tool names: {', '.join(tools) if tools else 'none recorded'}",
        f"- Continuation/execution steps: {steps if steps is not None else 'unavailable'}",
        f"- Total elapsed time: {elapsed_text}",
        f"- Halt/error: {error}",
        f"- Partial result: {partial_text if partial_text else 'unavailable'}",
    ]
    return "\n".join(lines)


__all__ = ["is_previous_turn_audit", "previous_turn_audit"]
