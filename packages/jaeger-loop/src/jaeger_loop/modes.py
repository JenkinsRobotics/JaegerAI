"""Dual execution modes (``build`` vs ``plan``) for jaeger-loop.

Adapted from OpenCode (MIT) Tab-switched ``build`` / ``plan`` agent modes:
- ``AgentMode.BUILD``: normal full authorized toolset.
- ``AgentMode.PLAN``: strictly read-only analysis and planning; denies all
  mutating tools (file edits, shell writes, external sends, hardware motion)
  with a clear guidance message so the model plans safely without side effects.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Mapping

from jaeger_contracts import ToolResult


class AgentMode(str, Enum):
    BUILD = "build"
    PLAN = "plan"

    @classmethod
    def parse(cls, value: str | "AgentMode" | None) -> "AgentMode":
        if isinstance(value, cls):
            return value
        raw = (value or "build").strip().lower()
        if raw == "plan":
            return cls.PLAN
        if raw == "build":
            return cls.BUILD
        raise ValueError(f"unsupported agent mode {value!r}; expected 'build' or 'plan'")


PLAN_MODE_SYSTEM_NOTE = (
    "Execution mode: PLAN (strictly read-only). Inspect files, search, analyze, and produce a clear "
    "step-by-step plan, but do NOT edit files, run mutating commands, or trigger external side effects "
    "until the user switches back to BUILD mode."
)


class PlanModeMiddleware:
    """LoopMiddleware that enforces read-only tool gating whenever ``mode == AgentMode.PLAN``."""

    def __init__(
        self,
        *,
        is_read_only: Callable[[str], bool],
        mode_getter: Callable[[], AgentMode],
        extra_allowed_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._is_read_only = is_read_only
        self._mode_getter = mode_getter
        self._extra_allowed = frozenset(t.strip().lower() for t in extra_allowed_tools if t.strip())

    def on_model_call(self, ctx: Any, call_next: Callable[[Any], Mapping[str, Any]]) -> Mapping[str, Any]:
        return call_next(ctx)

    def on_tool_call(
        self,
        ctx: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
        call_next: Callable[[str, Mapping[str, Any]], ToolResult],
    ) -> ToolResult:
        mode = self._mode_getter()
        if mode == AgentMode.PLAN:
            low = (tool_name or "").strip().lower()
            if low not in self._extra_allowed and not self._is_read_only(tool_name):
                return ToolResult(
                    tool_name=tool_name,
                    ok=False,
                    output="",
                    error=(
                        f"Blocked in PLAN mode (read-only): tool '{tool_name}' can mutate state. "
                        "Switch execution mode to 'build' to execute changes."
                    ),
                )
        return call_next(tool_name, arguments)


__all__ = ["AgentMode", "PLAN_MODE_SYSTEM_NOTE", "PlanModeMiddleware"]
