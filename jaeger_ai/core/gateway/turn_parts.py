"""Project one turn's durable events into ordered response parts.

The event log already records everything a chat bubble shows; this folds it
into ``[{type: reasoning|text|tool|plan|handoff, ...}]`` once, when the turn
completes, so a reload renders the same bubble without replaying events.
"""
from __future__ import annotations

from typing import Any, Iterable

_TOOL_END = {"tool.completed": "done", "tool.done": "done", "tool.failed": "error", "tool.error": "error"}
_HANDOFF = {"agent.handoff": "to", "agent.handoff.finished": "from"}
PART_EVENTS = ("turn.delta", "turn.reasoning", "turn.reasoning.done", "tool.started",
               *_TOOL_END, "turn.plan", *_HANDOFF)


def project_parts(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    for evt in events:
        name, data, ts = evt.get("event"), evt.get("data") or {}, evt.get("timestamp")
        last = parts[-1] if parts else None
        if name == "turn.delta":
            text = str(data.get("delta") or "")
            if last and last["type"] == "text":
                last["text"] += text
            elif text:
                parts.append({"type": "text", "text": text})
        elif name == "turn.reasoning":
            text = str(data.get("text") or "")
            if last and last["type"] == "reasoning" and "duration_ms" not in last:
                last["text"] += text
            else:
                parts.append({"type": "reasoning", "text": text, "started_at": ts})
        elif name == "turn.reasoning.done":
            open_ = next((p for p in reversed(parts) if p["type"] == "reasoning" and "duration_ms" not in p), None)
            if open_ is not None:
                open_["started_at"] = data.get("started_at", open_.get("started_at"))
                open_["duration_ms"] = data.get("duration_ms")
        elif name == "tool.started":
            part = {"type": "tool", "call_id": data.get("call_id"), "tool": data.get("tool"),
                    "status": "running", **({"input": data["input"]} if data.get("input") else {})}
            tools[str(data.get("call_id"))] = part
            parts.append(part)
        elif name in _TOOL_END:
            part = tools.get(str(data.get("call_id")))
            if part is None:
                part = {"type": "tool", "call_id": data.get("call_id"), "tool": data.get("tool")}
                parts.append(part)
            part["status"] = _TOOL_END[name]
            part["elapsed_s"] = data.get("elapsed_s")
            if data.get("output"):
                part["output"] = data["output"]
        elif name == "turn.plan":
            parts.append({"type": "plan", **{k: v for k, v in data.items() if k not in {"turn_id", "request_id"}}})
        elif name in _HANDOFF:
            handoff = data.get("handoff") or {}
            agent_id = handoff.get("to_agent_id")
            parts.append({"type": "handoff", "direction": _HANDOFF[name], "handoff_id": handoff.get("id"),
                          "agent_id": agent_id,
                          "agent_name": (handoff.get("metadata") or {}).get("target_display") or agent_id,
                          "status": handoff.get("status")})
    return parts


__all__ = ["PART_EVENTS", "project_parts"]
