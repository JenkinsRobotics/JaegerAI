"""Automatic Post-Task Reflection & Self-Improvement Engine.

Runs asynchronously after multi-step owner runs or autonomous goal ticks so Jaeger
continuously improves without slowing down interactive responses:
- Distills durable lessons & patterns into LearningStore / WorldModelStore
- Automatically drafts & updates scanned workspace SKILL.md files for repeatable
  multi-tool workflows (never overwriting hand-authored skills)
- Strictly respects E-Stop and never executes external side effects
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ReflectionOutcome:
    reflected: bool
    reason: str
    lesson_recorded: bool = False
    skill_captured: str = ""
    tools_used: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reflected": self.reflected,
            "reason": self.reason,
            "lesson_recorded": self.lesson_recorded,
            "skill_captured": self.skill_captured,
            "tools_used": list(self.tools_used),
            "timestamp": self.timestamp,
        }


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    parts = [p for p in cleaned.split("-") if len(p) > 2][:5]
    slug = "-".join(parts)[:42].strip("-")
    return slug or "captured-workflow"


def _extract_tool_names(tool_calls: Sequence[Any]) -> list[str]:
    names: list[str] = []
    for tc in tool_calls:
        if isinstance(tc, Mapping):
            name = str(tc.get("tool") or tc.get("name") or "").strip()
        else:
            name = str(getattr(tc, "tool", None) or getattr(tc, "name", None) or "").strip()
        if name:
            names.append(name)
    return names


class PostTaskReflector:
    """Non-blocking post-task reflection & automatic skill-capture loop."""

    def __init__(
        self,
        *,
        learning_store: Any = None,
        world_model: Any = None,
        skill_saver: Callable[[str, str], Any] | None = None,
        memory_sync: Callable[[], Any] | None = None,
        event_publisher: Callable[[str, Mapping[str, Any]], None] | None = None,
        is_estop: Callable[[], bool] | None = None,
        min_tools_for_skill: int = 3,
    ) -> None:
        self._learning = learning_store
        self._world = world_model
        self._skill_saver = skill_saver
        self._memory_sync = memory_sync
        self._publish = event_publisher
        self._is_estop = is_estop or (lambda: False)
        self._min_tools_for_skill = max(2, int(min_tools_for_skill))
        self._lock = threading.RLock()
        self._recent_outcomes: list[ReflectionOutcome] = []
        self._captured_signatures: set[str] = set()

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [o.to_dict() for o in self._recent_outcomes[-max(1, limit):]][::-1]

    def schedule_reflection(
        self,
        *,
        prompt: str,
        result: Mapping[str, Any],
        session_id: str = "",
        source: str = "owner_turn",
    ) -> None:
        """Run reflection in a lightweight daemon thread so interactive chat never blocks."""
        if self._is_estop():
            return
        t = threading.Thread(
            target=self.reflect_sync,
            kwargs={"prompt": prompt, "result": dict(result), "session_id": session_id, "source": source},
            name="jaeger-post-task-reflect",
            daemon=True,
        )
        t.start()

    def reflect_sync(
        self,
        *,
        prompt: str,
        result: Mapping[str, Any],
        session_id: str = "",
        source: str = "owner_turn",
    ) -> ReflectionOutcome:
        """Analyze a completed run, record durable learnings, and capture reusable workflows."""
        if self._is_estop():
            return ReflectionOutcome(reflected=False, reason="estop_active")

        verdict = str(result.get("verdict") or "")
        content = str(result.get("content") or "").strip()
        tool_names = _extract_tool_names(result.get("tool_calls") or ())
        unique_tools = list(dict.fromkeys(tool_names))

        # Skip trivial single-turn chat with < 2 tool invocations
        if len(tool_names) < 2:
            return ReflectionOutcome(reflected=False, reason="trivial_turn", tools_used=tuple(unique_tools))

        if verdict and verdict not in ("completed", "ok", "success", ""):
            return ReflectionOutcome(reflected=False, reason=f"non_completed:{verdict}", tools_used=tuple(unique_tools))

        clean_prompt = " ".join((prompt or "").split())[:140]
        lesson_recorded = False
        skill_captured = ""

        # 1. Record durable workflow learning in LearningStore
        if self._learning is not None and clean_prompt:
            try:
                summary = (
                    f"Completed '{clean_prompt}' using {len(tool_names)} tool calls "
                    f"({', '.join(unique_tools[:6])}). Outcome: {content[:180]}"
                )
                self._learning.record(
                    kind="workflow_reflection",
                    summary=summary,
                    tags=["reflection", source, *unique_tools[:4]],
                    confidence=0.85,
                )
                lesson_recorded = True
            except Exception:  # noqa: BLE001
                pass

        # 2. Capture a reusable SKILL.md when a rich multi-tool workflow succeeds
        sig = f"{_slugify(clean_prompt)}:{','.join(sorted(unique_tools[:5]))}"
        if (
            self._skill_saver is not None
            and len(unique_tools) >= self._min_tools_for_skill
            and clean_prompt
            and sig not in self._captured_signatures
        ):
            skill_name = f"auto-{_slugify(clean_prompt)}"
            steps_md = "\n".join(f"{idx + 1}. Run `{t}` as needed and inspect its real output." for idx, t in enumerate(unique_tools[:8]))
            skill_md = (
                "---\n"
                f"name: {skill_name}\n"
                f"description: Auto-captured workflow for {clean_prompt[:100]}\n"
                "tags:\n"
                "  - auto-captured\n"
                f"  - {source}\n"
                "---\n\n"
                f"# {skill_name}\n\n"
                f"Captured automatically from a verified multi-step run (`{len(tool_names)}` tool calls).\n\n"
                "## Trigger\n"
                f"Use when the owner asks to: {clean_prompt}\n\n"
                "## Verified Tool Sequence\n"
                f"{steps_md}\n\n"
                "## Verification\n"
                "Confirm the final state with real tool output before reporting completion.\n"
            )
            try:
                self._skill_saver(skill_name, skill_md)
                skill_captured = skill_name
                with self._lock:
                    self._captured_signatures.add(sig)
            except Exception:  # noqa: BLE001
                # Never fail if skill already exists or scanner rejects
                pass

        # 3. Record perception in WorldModelStore & notify global event bus
        if self._world is not None:
            try:
                self._world.record_perception(
                    modality="owner" if source == "owner_turn" else "system",
                    kind="reflection",
                    payload={
                        "summary": f"Reflected on '{clean_prompt[:80]}'"
                        + (f" (captured skill {skill_captured})" if skill_captured else ""),
                        "tools": unique_tools[:8],
                        "skill_captured": skill_captured,
                        "session_id": session_id,
                    },
                    salience=0.75 if skill_captured else 0.55,
                )
            except Exception:  # noqa: BLE001
                pass

        if lesson_recorded and self._memory_sync is not None:
            try:
                self._memory_sync()
            except Exception:  # noqa: BLE001
                pass

        outcome = ReflectionOutcome(
            reflected=True,
            reason="captured_skill" if skill_captured else "recorded_learning",
            lesson_recorded=lesson_recorded,
            skill_captured=skill_captured,
            tools_used=tuple(unique_tools),
        )
        with self._lock:
            self._recent_outcomes.append(outcome)
            if len(self._recent_outcomes) > 50:
                self._recent_outcomes = self._recent_outcomes[-50:]

        if self._publish is not None:
            try:
                self._publish("cognition.reflection", outcome.to_dict())
            except Exception:  # noqa: BLE001
                pass

        return outcome


__all__ = ["PostTaskReflector", "ReflectionOutcome"]
