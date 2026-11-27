"""Zombie-fenced SSE event streaming with monotonic Last-Event-ID cursor replay (Agno pattern)."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Mapping

from jaeger_authority import redact_text
from jaeger_events import FencedEventStream, StaleWriterError


def format_sse(
    *,
    event: str,
    data: Mapping[str, Any] | str,
    seq: int | None = None,
) -> str:
    """Render one standards-compliant Server-Sent Event frame."""
    lines: list[str] = []
    if seq is not None:
        lines.append(f"id: {int(seq)}")
    if event:
        lines.append(f"event: {event}")
    payload = data if isinstance(data, str) else json.dumps(dict(data), ensure_ascii=False, default=str)
    for chunk in payload.splitlines() or [""]:
        lines.append(f"data: {chunk}")
    return "\n".join(lines) + "\n\n"


class SessionEventHub:
    """Manages per-session zombie-fenced event streams with cursor-based replay."""

    def __init__(self, save_tool_receipt: Callable[[str, Mapping[str, Any]], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._save_tool_receipt = save_tool_receipt
        self._stream = FencedEventStream()
        self._requests: dict[str, str] = {}
        self._doorbells: dict[str, threading.Condition] = {}

    def _cond(self, session_id: str) -> threading.Condition:
        with self._lock:
            cond = self._doorbells.get(session_id)
            if cond is None:
                cond = threading.Condition(self._lock)
                self._doorbells[session_id] = cond
            return cond

    def open_generation(self, session_id: str, *, floor_seq: int = 0, request_id: str = "") -> int:
        """Mint a new monotonic writer generation, fencing out any prior zombie worker."""
        cond = self._cond(session_id)
        with cond:
            gen = self._stream.open_attempt(session_id, floor_seq=floor_seq)
            self._requests[session_id] = request_id
            cond.notify_all()
            return gen

    def publish(
        self,
        session_id: str,
        event: str,
        payload: Mapping[str, Any],
        *,
        generation: int,
    ) -> dict[str, Any]:
        """Append a fenced event and ring the session doorbell. Raises StaleWriterError on zombie writes."""
        cond = self._cond(session_id)
        with cond:
            request_id = self._requests.get(session_id)
            if request_id and "request_id" not in payload:
                payload = {**payload, "request_id": request_id}
            env = self._stream.append(
                session_id,
                generation,
                event,
                payload,
                session_id=session_id,
            )
            rec = {
                "seq": env.seq,
                "event": env.event_type,
                "payload": dict(env.payload),
                "session_id": env.session_id,
            }
            if request_id and self._save_tool_receipt is not None and event in ("tool.completed", "tool.failed"):
                receipt = {"status": event.removeprefix("tool.")}
                for key in ("call_id", "tool", "step", "output", "error"):
                    value = payload.get(key)
                    if value is not None:
                        receipt[key] = redact_text(value)[:2_000] if isinstance(value, str) else value
                self._save_tool_receipt(request_id, receipt)
            cond.notify_all()
            return rec

    def replay_after(self, session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        envs = self._stream.read_since(session_id, after_seq=after_seq)
        return [
            {
                "seq": env.seq,
                "event": env.event_type,
                "payload": dict(env.payload),
                "session_id": env.session_id,
            }
            for env in envs
        ]

    def transcript_parts(self, session_id: str, request_id: str, final_content: str) -> list[dict[str, Any]]:
        """Project the visible turn into durable message parts."""
        parts: list[dict[str, Any]] = []
        tools: dict[str, dict[str, Any]] = {}
        fragments: list[str] = []
        fragment_type = ""

        def flush_text() -> None:
            if not fragments:
                return
            value = "".join(fragments)
            if fragment_type == "thinking":
                value = redact_text(value)[:2_000]
            if value:
                parts.append({"type": fragment_type, "text": value})
            fragments.clear()

        for event in self.replay_after(session_id):
            payload = event["payload"]
            if payload.get("request_id") != request_id:
                continue
            kind = event["event"]
            if kind in ("text.delta", "thinking.delta"):
                next_type = "text" if kind == "text.delta" else "thinking"
                if next_type != fragment_type:
                    flush_text()
                    fragment_type = next_type
                delta = payload.get("delta")
                if isinstance(delta, str):
                    fragments.append(delta)
            elif kind in ("tool.started", "tool.completed", "tool.failed"):
                flush_text()
                call_id = str(payload.get("call_id") or event["seq"])
                card = tools.get(call_id)
                if card is None:
                    card = {"type": "tool", "callId": call_id,
                            "toolName": str(payload.get("tool") or "tool"), "status": "running"}
                    tools[call_id] = card
                    parts.append(card)
                if kind != "tool.started":
                    card["status"] = "completed" if kind == "tool.completed" else "failed"
                    if isinstance(payload.get("duration_ms"), (int, float)):
                        card["durationMs"] = payload["duration_ms"]
                    for key in ("output", "error"):
                        value = payload.get(key)
                        if isinstance(value, str) and value:
                            card[key] = redact_text(value)[:2_000]
        flush_text()
        if final_content and not "".join(
            part["text"] for part in parts if part["type"] == "text"
        ).rstrip().endswith(final_content.rstrip()):
            parts.append({"type": "text", "text": final_content})
        return parts

    def history_cursor(self, session_id: str) -> int:
        """Skip settled runs; replay the active run from its first event."""
        with self._lock:
            for event in reversed(self._stream.read_since(session_id)):
                if event.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    return event.seq
                if event.event_type == "run.started":
                    return event.seq - 1
            return 0

    def wait_for_events(
        self,
        session_id: str,
        after_seq: int,
        *,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Block on the session doorbell until events > ``after_seq`` arrive or timeout expires."""
        cond = self._cond(session_id)
        with cond:
            items = self.replay_after(session_id, after_seq=after_seq)
            if items:
                return items
            cond.wait(timeout=max(0.01, float(timeout)))
            return self.replay_after(session_id, after_seq=after_seq)


def restore_saved_presentation(result: Mapping[str, Any], final_content: str) -> list[dict[str, Any]]:
    """Recover older visible tool activity from a request's exact saved result."""
    records = result.get("messages")
    if not isinstance(records, list):
        return []
    turn: list[Mapping[str, Any]] = []
    for message in records:
        if isinstance(message, dict):
            if message.get("role") == "user":
                turn.clear()
            else:
                turn.append(message)

    receipts = {
        message["tool_call_id"]: message for message in turn
        if message.get("role") == "tool" and isinstance(message.get("tool_call_id"), str)
    }
    parts: list[dict[str, Any]] = []
    restored = set()
    for message in turn:
        if message.get("role") != "assistant":
            continue
        text = message.get("content")
        if isinstance(text, str) and text and text != final_content:
            parts.append({"type": "text", "text": text})
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("id"), str):
                continue
            call_id = call["id"]
            receipt = receipts.get(call_id)
            if not receipt or call_id in restored or receipt.get("name") != call.get("name"):
                continue
            raw = receipt.get("content")
            if not isinstance(raw, str):
                continue
            failed = raw.startswith("ERROR: ")
            parts.append({
                "type": "tool",
                "callId": call_id,
                "toolName": str(call["name"]),
                "status": "failed" if failed else "completed",
                "error" if failed else "output": redact_text(raw.removeprefix("ERROR: ") if failed else raw)[:2_000],
            })
            restored.add(call_id)
    if not restored:
        return []
    if final_content:
        parts.append({"type": "text", "text": final_content})
    return parts


__all__ = ["SessionEventHub", "StaleWriterError", "format_sse"]
