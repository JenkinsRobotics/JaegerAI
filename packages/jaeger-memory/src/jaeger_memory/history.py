"""Replayable message history invariants & orphan-preserving compaction boundaries.

Synthesizes:
- AG2 (`history.py`): 4-invariant replayable span / snap rules so message slicing
  never begins on an orphaned tool result or severs an assistant tool_call from
  its corresponding tool results.
- Agno (`compact.py`): ``choose_boundary()`` selecting a clean split index
  between older compactable history and recent verbatim turns without breaking
  tool-call groups.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def close_dangling_tool_calls(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every assistant tool_call has a matching tool result (AG2 invariant)."""
    out = [dict(m) for m in messages]
    answered = {
        m.get("tool_call_id")
        for m in out
        if m.get("role") == "tool" and m.get("tool_call_id")
    }
    patched: list[dict[str, Any]] = []
    for m in out:
        patched.append(m)
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for tc in m["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, Mapping) else None
                if tc_id and tc_id not in answered:
                    patched.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "[interrupted: tool call did not complete before checkpoint]",
                    })
                    answered.add(tc_id)
    return patched


def _assistant_call_ids(message: Mapping[str, Any]) -> set[str]:
    if message.get("role") != "assistant":
        return set()
    calls = message.get("tool_calls") or []
    return {
        str(tc.get("id"))
        for tc in calls
        if isinstance(tc, Mapping) and tc.get("id")
    }


def snap(messages: Sequence[Mapping[str, Any]], cut_index: int) -> int:
    """Snap a proposed split index to a valid group boundary (AG2 snap rule).

    Guarantees that ``messages[snapped:]`` never starts on a ``role='tool'``
    message whose owning assistant tool_call lies before the cut, and never
    splits an assistant message with tool_calls from its tool results.
    """
    n = len(messages)
    if n == 0:
        return 0
    idx = max(0, min(cut_index, n))
    if idx == 0 or idx == n:
        return idx

    # If the cut lands on a tool message, walk backward to include its owning
    # assistant message (if immediately preceding in the same tool-call block);
    # otherwise walk forward past orphaned leading tool messages.
    if messages[idx].get("role") == "tool":
        probe = idx
        while probe > 0 and messages[probe].get("role") == "tool":
            probe -= 1
        if messages[probe].get("role") == "assistant" and _assistant_call_ids(messages[probe]):
            return probe
        # Orphaned tool block with no owning assistant: advance past it.
        while idx < n and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    return idx


def replayable_span(
    messages: Sequence[Mapping[str, Any]],
    start_index: int = 0,
    *,
    close_dangling: bool = True,
) -> list[dict[str, Any]]:
    """Return a provider-valid, replayable slice starting near ``start_index``.

    Enforces all 4 AG2 invariants:
      1. Never starts on an orphaned ``role='tool'`` message.
      2. Keeps every assistant ``tool_calls`` message paired with its tool results.
      3. Strips any dangling ``role='tool'`` whose ``tool_call_id`` has no
         preceding assistant call in the slice.
      4. Optionally closes any unanswered assistant ``tool_calls`` at the tail.
    """
    if not messages:
        return []
    snapped = snap(messages, start_index)
    raw = [dict(m) for m in messages[snapped:]]

    seen_calls: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for msg in raw:
        role = msg.get("role")
        if role == "assistant":
            seen_calls.update(_assistant_call_ids(msg))
            cleaned.append(msg)
        elif role == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id and str(tc_id) not in seen_calls:
                continue
            cleaned.append(msg)
        else:
            cleaned.append(msg)

    return close_dangling_tool_calls(cleaned) if close_dangling else cleaned


def choose_boundary(
    messages: Sequence[Mapping[str, Any]],
    *,
    keep_recent: int = 4,
    max_recent_chars: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition non-system history into ``(older, recent)`` on a clean tool boundary (Agno).

    Guarantees ``recent`` never begins with an orphaned tool result and preserves
    at least ``keep_recent`` messages when available (expanding backward if needed
    to avoid cutting an assistant+tool group in half).
    """
    items = [dict(m) for m in messages]
    n = len(items)
    if n == 0 or keep_recent <= 0:
        return items, []
    if n <= keep_recent:
        return [], replayable_span(items, 0, close_dangling=False)

    proposed = max(0, n - keep_recent)
    if max_recent_chars is not None and max_recent_chars > 0:
        chars = 0
        idx = n
        while idx > 0 and (n - idx) < keep_recent:
            idx -= 1
            chars += len(str(items[idx].get("content") or ""))
            if chars >= max_recent_chars and idx < n - 1:
                break
        proposed = max(proposed, idx)

    cut = snap(items, proposed)
    older = items[:cut]
    recent = replayable_span(items, cut, close_dangling=False)
    return older, recent


__all__ = [
    "choose_boundary",
    "close_dangling_tool_calls",
    "replayable_span",
    "snap",
]
