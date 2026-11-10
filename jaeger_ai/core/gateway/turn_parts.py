"""Project one turn's durable events into ordered response parts.

The event log already records everything a chat bubble shows; this folds it
into ``[{type: reasoning|text|tool|plan|handoff, ...}]`` once, when the turn
completes, so a reload renders the same bubble without replaying events.
"""
from __future__ import annotations

from typing import Any, Iterable

_TOOL_END = {"tool.completed": "done", "tool.done": "done", "tool.failed": "error", "tool.error": "error"}
_HANDOFF = {"agent.handoff": "to", "agent.handoff.finished": "from"}
PART_EVENTS = ("turn.delta", "turn.steer", "turn.reasoning", "turn.reasoning.done", "tool.started", "agent.knowledge", "turn.context", "turn.model", "tools.selected",
               *_TOOL_END, "turn.plan", "turn.progress", "turn.checkpoint", "sources", "search.count", "follow_ups", *_HANDOFF)


def project_parts(events: Iterable[dict[str, Any]], final_text: str | None = None) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    for evt in events:
        name, data, ts = evt.get("event"), evt.get("data") or {}, evt.get("timestamp")
        last = parts[-1] if parts else None
        if name == "turn.steer":
            parts.append({'type': 'steer', 'text': str(data.get('text') or ''),
                          'steering_id': data.get('steering_id') or str(evt.get('event_id') or ts or len(parts))})
        elif name == "turn.delta":
            text = str(data.get("delta") or "")
            role = str(data.get("content_type") or data.get("channel") or "provisional")
            item_id = str(data.get("item_id") or "") or None
            if last and last["type"] == "text" and last.get("role") == role and last.get("item_id") == item_id:
                last["text"] += text
            elif text:
                parts.append({"type": "text", "text": text, "role": role, **({"item_id": item_id} if item_id else {})})
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
            for prior in parts:
                if prior.get("type") == "text" and prior.get("role") == "provisional":
                    prior["role"] = "commentary"
            part = {"type": "tool", "call_id": data.get("call_id"), "tool": data.get("tool"),
                    "status": "running", **({"input": data["input"]} if data.get("input") else {})}
            tools[str(data.get("call_id"))] = part
            parts.append(part)
        elif name in _TOOL_END:
            part = tools.get(str(data.get("call_id")))
            if part is None:
                part = {"type": "tool", "call_id": data.get("call_id"), "tool": data.get("tool")}
                parts.append(part)
            part["status"] = data.get("outcome") or _TOOL_END[name]
            part["elapsed_s"] = data.get("elapsed_s")
            if data.get("output"):
                part["output"] = data["output"]
            if data.get("summary") or data.get("text"):
                part["summary"] = data.get("summary") or data.get("text")
        elif name == "turn.model":
            parts.append({"type":"model_identity", "actual_model":data.get("actual_model"), "scope":data.get("scope") or "unknown"})
        elif name == "tools.selected":
            replacement = {"type": "tool_selection", "receipt": data.get("receipt") or {}}
            index = next((i for i, part in enumerate(parts) if part.get("type") == "tool_selection"), None)
            if index is None:
                parts.append(replacement)
            else:
                parts[index] = replacement
        elif name == "turn.context":
            parts.append({"type": "model_context", "outline": data.get("outline") or {}})
        elif name == "agent.knowledge":
            parts.append({"type": "knowledge", "documents": data.get("documents") or []})
        elif name in {"turn.progress", "turn.checkpoint", "sources", "search.count", "follow_ups"}:
            kind = {"turn.progress": "progress", "turn.checkpoint": "checkpoint", "search.count": "search_count"}.get(name, name)
            parts.append({**{k: v for k, v in data.items() if k not in {"turn_id", "request_id", "session_id", "type"}}, "type": kind})
        elif name == "turn.plan":
            parts.append({"type": "plan", **{k: v for k, v in data.items() if k not in {"turn_id", "request_id"}}})
        elif name in _HANDOFF:
            handoff = data.get("handoff") or {}
            agent_id = handoff.get("to_agent_id")
            part = {"type": "handoff", "direction": _HANDOFF[name], "handoff_id": handoff.get("id"),
                          "agent_id": agent_id,
                          "agent_name": (handoff.get("metadata") or {}).get("target_display") or agent_id,
                          "status": "delivered" if (handoff.get("metadata") or {}).get("delivery_message_id") else handoff.get("status")}
            prior = next((i for i, p in enumerate(parts) if p["type"] == "handoff" and p["handoff_id"] == part["handoff_id"] and p["direction"] == part["direction"]), None)
            if prior is None:
                parts.append(part)
            elif parts[prior].get("status") != "delivered" or part.get("status") == "delivered":
                parts[prior] = part
    if final_text is not None:
        indexes = [i for i, part in enumerate(parts) if part.get("type") == "text" and part.get("role") == "provisional"]
        final = {"type": "text", "text": final_text, "role": "final", "item_id": "final"}
        if indexes:
            first, rest = indexes[0], set(indexes[1:])
            parts[first] = final
            parts = [part for i, part in enumerate(parts) if i not in rest]
        elif final_text:
            parts.append(final)
    return parts


__all__ = ["PART_EVENTS", "project_parts"]
