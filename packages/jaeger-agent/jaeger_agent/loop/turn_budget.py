"""Unified per-turn resource budget and telemetry.

The budget owns policy; UI surfaces only render :meth:`snapshot`. Absolute
tool/iteration fuses remain even when optional time, token, or cost ceilings are
unset. Checks happen at safe loop boundaries, never by killing an in-flight
side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable


@dataclass(frozen=True)
class TurnBudgetLimits:
    max_tool_calls: int = 24
    max_iterations: int = 50
    max_elapsed_s: float | None = None
    max_tokens: int | None = None
    max_tool_cost: float | None = None
    warning_fraction: float = 0.8


class TurnBudget:
    def __init__(
        self,
        limits: TurnBudgetLimits,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.limits = limits
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.started_at = self._clock()
        self.tool_calls = 0
        self.iterations = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tool_cost = 0.0

    @property
    def elapsed_s(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def observe_iteration(self, iteration: int) -> None:
        self.iterations = max(self.iterations, int(iteration))

    def consume_tool(self, *, count: int = 1, cost: float = 1.0) -> None:
        self.tool_calls += max(0, int(count))
        self.tool_cost += max(0.0, float(cost))

    def observe_usage(self, *, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens))
        self.completion_tokens += max(0, int(completion_tokens))

    def halt_reason(self) -> str | None:
        if self.tool_calls >= self.limits.max_tool_calls:
            return f"made {self.tool_calls} tool calls in a single turn"
        if self.iterations >= self.limits.max_iterations:
            return f"hit max_iterations={self.limits.max_iterations} without a final answer"
        if self.limits.max_elapsed_s is not None and self.elapsed_s >= self.limits.max_elapsed_s:
            return f"exceeded turn time budget of {self.limits.max_elapsed_s:g}s"
        if self.limits.max_tokens is not None and self.tokens >= self.limits.max_tokens:
            return f"exceeded turn token budget of {self.limits.max_tokens}"
        if self.limits.max_tool_cost is not None and self.tool_cost >= self.limits.max_tool_cost:
            return f"exceeded tool cost budget of {self.limits.max_tool_cost:g}"
        return None

    def warning_dimensions(self) -> list[str]:
        warn = min(0.99, max(0.01, self.limits.warning_fraction))
        values = (
            ("tool_calls", self.tool_calls, self.limits.max_tool_calls),
            ("iterations", self.iterations, self.limits.max_iterations),
            ("elapsed_s", self.elapsed_s, self.limits.max_elapsed_s),
            ("tokens", self.tokens, self.limits.max_tokens),
            ("tool_cost", self.tool_cost, self.limits.max_tool_cost),
        )
        return [name for name, value, limit in values if limit is not None and limit > 0 and value / limit >= warn]

    def warning(self) -> str | None:
        dimensions = self.warning_dimensions()
        if not dimensions:
            return None
        labels = ", ".join(dimensions)
        return (
            f"[turn budget warning: {labels} reached at least "
            f"{round(self.limits.warning_fraction * 100):d}% of the configured limit. "
            "Use existing results, avoid broadening the task, and finish safely.]"
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "usage": {
                "tool_calls": self.tool_calls,
                "iterations": self.iterations,
                "elapsed_s": round(self.elapsed_s, 3),
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "tokens": self.tokens,
                "tool_cost": round(self.tool_cost, 3),
            },
            "limits": {
                "tool_calls": self.limits.max_tool_calls,
                "iterations": self.limits.max_iterations,
                "elapsed_s": self.limits.max_elapsed_s,
                "tokens": self.limits.max_tokens,
                "tool_cost": self.limits.max_tool_cost,
            },
            "warning_dimensions": self.warning_dimensions(),
            "halt_reason": self.halt_reason(),
        }


__all__ = ["TurnBudget", "TurnBudgetLimits"]
