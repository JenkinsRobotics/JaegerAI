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
        self.helpers = []

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
        cost = usage.get("cost_usd") if isinstance(usage, dict) else None
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            entry["cost_usd"] = float(cost)
        self.model_calls.append(entry)
        self._model_start = None

    def helper_done(self, handoff_id: str, tokens: dict | None, status: str = "") -> None:
        """An inner helper (delegate) finished under this run: its usage is
        part of the run's usage (OpenAI Agents SDK counts agent-as-tool runs)."""
        if any(h.get("handoff_id") == handoff_id for h in self.helpers):
            return
        tokens = tokens if isinstance(tokens, dict) else {}
        entry = {"handoff_id": handoff_id, "status": status,
                 "input_tokens": int(tokens.get("prompt") or 0),
                 "output_tokens": int(tokens.get("completion") or 0)}
        cost = tokens.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            entry["cost_usd"] = float(cost)
        self.helpers.append(entry)

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

    def usage(self) -> dict:
        """Run total across model steps (OpenAI Agents SDK ``Usage`` shape:
        requests, input/output/total tokens) plus cost when providers report it."""
        inp = sum(int(c.get("prompt_tokens") or 0) for c in self.model_calls)
        out = sum(int(c.get("completion_tokens") or 0) for c in self.model_calls)
        costs = [float(c["cost_usd"]) for c in self.model_calls if "cost_usd" in c]
        out_doc = {"requests": len(self.model_calls), "input_tokens": inp, "output_tokens": out,
                   "total_tokens": inp + out, "reported": bool(inp or out),
                   "cost_usd": round(sum(costs), 6) if costs else None}
        if self.helpers:
            h_in = sum(h["input_tokens"] for h in self.helpers)
            h_out = sum(h["output_tokens"] for h in self.helpers)
            h_costs = [h["cost_usd"] for h in self.helpers if "cost_usd" in h]
            out_doc["helpers"] = {"count": len(self.helpers), "input_tokens": h_in, "output_tokens": h_out,
                                  "total_tokens": h_in + h_out,
                                  "cost_usd": round(sum(h_costs), 6) if h_costs else None}
            out_doc["total_with_helpers"] = {
                "input_tokens": inp + h_in, "output_tokens": out + h_out, "total_tokens": inp + out + h_in + h_out,
                "cost_usd": round(sum(costs) + sum(h_costs), 6) if (costs or h_costs) else None}
        return out_doc

    def snapshot(self) -> dict:
        return {
            "usage": self.usage(),
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
