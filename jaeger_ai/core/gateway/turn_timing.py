"""Content-free monotonic timing for one Gateway turn."""
from __future__ import annotations

import time


class TurnTiming:
    def __init__(self, admitted_at: float | None = None):
        self.admitted_at = time.monotonic() if admitted_at is None else admitted_at
        self.prepare_turn_start_ms = None
        self.prepare_turn_end_ms = None
        self.first_model_call_start_ms = None
        self.first_token_ms = None
        self.model_calls = []
        self.tool_calls = []
        self.continuation_steps = []
        self.turn_finish_ms = None
        self.halt_reason = None
        self._model_start = None
        self._tools = {}

    def now(self) -> float:
        return round(max(0.0, (time.monotonic() - self.admitted_at) * 1000), 3)

    def model_start(self) -> None:
        at = self.now()
        self._model_start = at
        if self.first_model_call_start_ms is None:
            self.first_model_call_start_ms = at

    def first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = self.now()

    def model_done(self, usage: dict[str, int]) -> None:
        end = self.now()
        start = self._model_start if self._model_start is not None else end
        entry = {"start_ms": start, "end_ms": end, "duration_ms": round(end - start, 3)}
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                entry[key] = value
        self.model_calls.append(entry)
        self._model_start = None

    def tool_start(self, name: str) -> None:
        self._tools.setdefault(name, []).append(self.now())

    def tool_done(self, name: str) -> None:
        end = self.now()
        queue = self._tools.get(name) or []
        start = queue.pop(0) if queue else end
        self.tool_calls.append({"name": name, "start_ms": start,
                                "end_ms": end, "duration_ms": round(end - start, 3)})

    def continuation(self) -> None:
        self.continuation_steps.append(self.now())

    def snapshot(self) -> dict:
        return {
            "admission_ms": 0.0,
            "prepare_turn_start_ms": self.prepare_turn_start_ms,
            "prepare_turn_end_ms": self.prepare_turn_end_ms,
            "first_model_call_start_ms": self.first_model_call_start_ms,
            "first_token_ms": self.first_token_ms,
            "model_calls": list(self.model_calls),
            "tool_calls": list(self.tool_calls),
            "continuation_steps_ms": list(self.continuation_steps),
            "model_call_count": len(self.model_calls),
            "tool_call_count": len(self.tool_calls),
            "continuation_step_count": len(self.continuation_steps),
            "turn_finish_ms": self.turn_finish_ms,
            "halt_reason": self.halt_reason,
        }
