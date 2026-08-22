"""Lossy context compaction for long autonomous runs.

The loop's context guard already drops oldest turns into a digest when
the window is genuinely full. This module is the *earlier*, more
aggressive pass aimed at batch work: verbose JSON tool results from
finished steps rot the window long before the guard would fire, and
they are exactly the tokens a work ledger has already summarised.

At ~80% of the serving context window:

  1. System-role messages and the current work-ledger block stay.
  2. Older completed turns' raw tool JSON is flushed into a two-
     paragraph progress digest.
  3. The last two turns stay verbatim for immediate coherence.

The compacted list is written back onto ``jaeger_agent.messages``.
Failure is silent — compaction must never take a turn down with it.
"""

from __future__ import annotations

import json
import os
from typing import Any

from jaeger_ai.core.runtime.work_ledger import LEDGER_TAG, context_block

DEFAULT_THRESHOLD = 0.80
DEFAULT_KEEP_TURNS = 2
_CHARS_PER_TOKEN = 3.0
DIGEST_TAG = "[Progress digest]"


def _flag_threshold() -> float:
    raw = os.environ.get("JAEGER_COMPACT_AT", "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_THRESHOLD
    return min(0.99, max(0.1, value))


def estimate_tokens(messages: list[dict[str, Any]], *, system_prompt: str = "") -> int:
    """Conservative char heuristic. Matches the guard's 3 chars/token
    bias: overshoot rather than overflow."""
    total = len(system_prompt or "")
    for message in messages or []:
        total += len(str(message.get("content") or ""))
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            total += len(str(call.get("name") or ""))
            args = call.get("arguments")
            if isinstance(args, str):
                total += len(args)
            elif args is not None:
                try:
                    total += len(json.dumps(args, default=str))
                except TypeError:
                    total += len(str(args))
    return int(total / _CHARS_PER_TOKEN)


def _ctx_window_for(agent: Any) -> int:
    guard = getattr(agent, "context_guard", None) if agent is not None else None
    budget = getattr(guard, "budget", None) if guard is not None else None
    window = int(getattr(budget, "ctx_window", 0) or 0)
    if window > 0:
        return window
    try:
        from jaeger_ai.main import last_ctx_snapshot
        snap = last_ctx_snapshot()
        window = int(snap.get("max") or 0)
        if window > 0:
            return window
    except Exception:  # noqa: BLE001
        pass
    return 0


def _used_tokens_for(agent: Any, messages: list[dict[str, Any]]) -> int:
    guard = getattr(agent, "context_guard", None) if agent is not None else None
    if guard is not None and hasattr(guard, "estimate_messages_tokens"):
        try:
            return int(guard.estimate_messages_tokens(
                messages,
                system_prompt=getattr(agent, "system_prompt", "") or "",
                tools=getattr(agent, "tools", None) or [],
            ))
        except Exception:  # noqa: BLE001 — fall through to the heuristic
            pass
    return estimate_tokens(
        messages, system_prompt=getattr(agent, "system_prompt", "") or "",
    )


def should_compact(
    messages: list[dict[str, Any]],
    *,
    ctx_window: int,
    used_tokens: int | None = None,
    threshold: float | None = None,
    system_prompt: str = "",
) -> bool:
    if ctx_window <= 0 or not messages:
        return False
    used = used_tokens if used_tokens is not None else estimate_tokens(
        messages, system_prompt=system_prompt,
    )
    return used >= int(ctx_window * (threshold if threshold is not None else _flag_threshold()))


def _is_ledger(message: dict[str, Any]) -> bool:
    return LEDGER_TAG in str(message.get("content") or "")


def _is_digest(message: dict[str, Any]) -> bool:
    return DIGEST_TAG in str(message.get("content") or "")


def _turn_groups(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split history into user-initiated turns. A turn is a user
    message plus the assistant/tool messages that follow it, until the
    next user message. Leading non-user messages (rare system rows)
    form their own group."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "user" and current:
            groups.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        groups.append(current)
    return groups


def _tool_stats(groups: list[list[dict[str, Any]]]) -> tuple[int, list[str], int]:
    names: list[str] = []
    errors = 0
    for group in groups:
        for message in group:
            if str(message.get("role") or "") != "tool":
                for call in message.get("tool_calls") or []:
                    if isinstance(call, dict) and call.get("name"):
                        names.append(str(call["name"]))
                continue
            name = str(message.get("name") or "tool")
            names.append(name)
            content = str(message.get("content") or "")
            lowered = content[:400].lower()
            if '"ok": false' in lowered or '"error"' in lowered or "traceback" in lowered:
                errors += 1
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return len(names), unique, errors


def _progress_digest(old_groups: list[list[dict[str, Any]]], ledger_text: str) -> str:
    n_calls, tools, errors = _tool_stats(old_groups)
    tool_list = ", ".join(tools[:12]) if tools else "none"
    para1 = (
        f"Earlier steps ran {n_calls} tool call(s) across "
        f"{len(old_groups)} turn(s). Tools used: {tool_list}."
    )
    if errors:
        para1 += f" {errors} of those calls returned an error."
    para2 = (ledger_text or "").strip() or (
        "No work ledger was present at compaction time; continue from "
        "the last two verbatim turns and do not re-do finished work."
    )
    if para2.startswith(LEDGER_TAG):
        para2 = "Current work ledger:\n" + para2
    return f"{DIGEST_TAG}\n{para1}\n\n{para2}"


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    ctx_window: int,
    used_tokens: int | None = None,
    threshold: float | None = None,
    keep_turns: int = DEFAULT_KEEP_TURNS,
    ledger_text: str = "",
    system_prompt: str = "",
) -> list[dict[str, Any]]:
    """Return a compacted copy of ``messages``. Unchanged when usage
    is under the threshold. Never mutates the input list."""
    if not should_compact(
        messages,
        ctx_window=ctx_window,
        used_tokens=used_tokens,
        threshold=threshold,
        system_prompt=system_prompt,
    ):
        return list(messages)

    pinned: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "system" or _is_ledger(message) or _is_digest(message):
            pinned.append(message)
        else:
            rest.append(message)

    groups = _turn_groups(rest)
    keep = max(0, int(keep_turns))
    if len(groups) <= keep:
        # Even with few turns, flush oversized tool JSON in the older
        # half so a single giant result cannot sit at 80% forever.
        compacted = pinned + [item for group in groups for item in group]
        return _truncate_old_tool_json(compacted, keep_last=keep)

    old_groups, recent = groups[:-keep], groups[-keep:]
    digest = _progress_digest(old_groups, ledger_text or context_block())
    rebuilt: list[dict[str, Any]] = list(pinned)
    rebuilt.append({"role": "user", "content": digest})
    rebuilt.append({
        "role": "assistant",
        "content": "Acknowledged the progress digest. Continuing from there.",
    })
    for group in recent:
        rebuilt.extend(group)
    return rebuilt


def _truncate_old_tool_json(
    messages: list[dict[str, Any]],
    *,
    keep_last: int,
    max_chars: int = 400,
) -> list[dict[str, Any]]:
    groups = _turn_groups(messages)
    if len(groups) <= keep_last:
        return messages
    cutoff = len(groups) - keep_last
    out: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if index >= cutoff:
            out.extend(group)
            continue
        for message in group:
            if str(message.get("role") or "") != "tool":
                out.append(message)
                continue
            content = str(message.get("content") or "")
            if len(content) <= max_chars:
                out.append(message)
                continue
            stub = dict(message)
            name = str(message.get("name") or "tool")
            stub["content"] = (
                f"[compacted {name} result, {len(content)} chars] "
                + content[:max_chars]
            )
            out.append(stub)
    return out


def compact_agent(agent: Any, *, threshold: float | None = None) -> bool:
    """Compact ``agent.messages`` in place when the window is ~80% full.

    Returns True when a compaction actually rewrote the list. Never
    raises — a hiccup leaves the original messages alone.
    """
    if agent is None:
        return False
    messages = getattr(agent, "messages", None)
    if not isinstance(messages, list) or not messages:
        return False
    try:
        window = _ctx_window_for(agent)
        if window <= 0:
            return False
        used = _used_tokens_for(agent, messages)
        compacted = compact_messages(
            messages,
            ctx_window=window,
            used_tokens=used,
            threshold=threshold,
            ledger_text=context_block(),
            system_prompt=getattr(agent, "system_prompt", "") or "",
        )
        if compacted is messages or compacted == messages:
            return False
        messages[:] = compacted
        return True
    except Exception:  # noqa: BLE001 — compaction must never break a turn
        return False


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_KEEP_TURNS",
    "DIGEST_TAG",
    "estimate_tokens",
    "should_compact",
    "compact_messages",
    "compact_agent",
]
