"""Hermes-style self-improvement learning nudge tracker for jaeger-loop.

Tracks completed turns and tool intensity per session and generates a concise,
non-intrusive system hint for the next turn when:
- A recent turn used >= `tool_threshold` tool calls (suggesting a reusable SKILL.md), or
- `turn_interval` completed turns have elapsed since the last memory curation check.

Never modifies user-facing reply prose; can be disabled via `JAEGER_NUDGE_ENABLED=0`.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

__all__ = ["LearningNudgeTracker"]


@dataclass
class _SessionNudgeState:
    turns_completed: int = 0
    turns_since_memory_nudge: int = 0
    pending_skill_nudge: bool = False
    pending_memory_nudge: bool = False
    last_tool_count: int = 0


class LearningNudgeTracker:
    """Thread-safe per-session tracker for Hermes-style skill & memory curation nudges."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        tool_threshold: int | None = None,
        turn_interval: int = 8,
    ) -> None:
        if enabled is None:
            raw = (os.environ.get("JAEGER_NUDGE_ENABLED") or "1").strip().lower()
            enabled = raw not in ("0", "false", "no", "off")
        if tool_threshold is None:
            try:
                tool_threshold = int(os.environ.get("JAEGER_NUDGE_TOOL_THRESHOLD") or "4")
            except ValueError:
                tool_threshold = 4
        self._enabled = bool(enabled)
        self._tool_threshold = max(2, int(tool_threshold))
        self._turn_interval = max(2, int(turn_interval))
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionNudgeState] = {}

    def record_turn(self, session_id: str, *, tool_calls: int, verdict: str = "complete") -> None:
        if not self._enabled or verdict != "complete":
            return
        with self._lock:
            st = self._sessions.setdefault(session_id, _SessionNudgeState())
            st.turns_completed += 1
            st.turns_since_memory_nudge += 1
            st.last_tool_count = int(tool_calls)
            if tool_calls >= self._tool_threshold:
                st.pending_skill_nudge = True
            if st.turns_since_memory_nudge >= self._turn_interval:
                st.pending_memory_nudge = True

    def consume_hint(self, session_id: str) -> str:
        """Return and clear any pending non-intrusive reflection hint for the next turn."""
        if not self._enabled:
            return ""
        with self._lock:
            st = self._sessions.get(session_id)
            if st is None:
                return ""
            parts: list[str] = []
            if st.pending_skill_nudge:
                st.pending_skill_nudge = False
                parts.append(
                    "If the multi-step workflow from your recent turn is reusable, consider capturing or refining it "
                    "with save_workspace_skill/update_workspace_skill (only if genuinely reusable; never mention this reminder)."
                )
            if st.pending_memory_nudge:
                st.pending_memory_nudge = False
                st.turns_since_memory_nudge = 0
                parts.append(
                    "If durable owner preferences or project facts emerged recently, save them quietly with memory_remember."
                )
            return ("\nLearning loop: " + " ".join(parts)) if parts else ""

    def stats(self, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if session_id:
                st = self._sessions.get(session_id)
                return {
                    "enabled": self._enabled,
                    "session_id": session_id,
                    "turns_completed": st.turns_completed if st else 0,
                    "pending_skill_nudge": st.pending_skill_nudge if st else False,
                    "pending_memory_nudge": st.pending_memory_nudge if st else False,
                }
            return {
                "enabled": self._enabled,
                "tool_threshold": self._tool_threshold,
                "turn_interval": self._turn_interval,
                "tracked_sessions": len(self._sessions),
            }
