"""Zero-side-effect Dry-Run / Safe-Mode workflow & tool simulator.

Adapted from Significant-Gravitas/AutoGPT (MIT License) ``executor/simulator.py``
pattern. Lets operators test multi-step business or droid workflows (e.g. YouTube
publish pipelines) with zero real API writes, file mutations, or external spend.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class SimulatedStep:
    step_id: str
    name: str
    action: str
    simulated_input: dict[str, Any]
    simulated_output: dict[str, Any]
    would_have_side_effects: bool
    reason: str
    duration_ms: int = 0


@dataclass
class DryRunReport:
    workflow_name: str
    steps: list[SimulatedStep] = field(default_factory=list)
    total_side_effect_steps: int = 0
    estimated_ok: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "estimated_ok": self.estimated_ok,
            "total_steps": len(self.steps),
            "total_side_effect_steps": self.total_side_effect_steps,
            "created_at": self.created_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "action": s.action,
                    "simulated_input": s.simulated_input,
                    "simulated_output": s.simulated_output,
                    "would_have_side_effects": s.would_have_side_effects,
                    "reason": s.reason,
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
        }


_SIDE_EFFECT_KEYWORDS = (
    "publish",
    "upload",
    "send",
    "email",
    "mail",
    "delete",
    "remove",
    "write",
    "edit",
    "shell",
    "exec",
    "pay",
    "charge",
    "post",
    "tweet",
    "deploy",
    "hardware",
    "motor",
)


def _has_side_effect(action: str, step: Mapping[str, Any]) -> bool:
    if step.get("read_only") is True:
        return False
    if step.get("side_effect") is True or step.get("requires_approval") is True:
        return True
    low = f"{action} {step.get('name', '')}".lower()
    return any(tok in low for tok in _SIDE_EFFECT_KEYWORDS)


class DryRunSimulator:
    """Simulates multi-step workflow definitions safely without executing real side effects."""

    def __init__(
        self,
        *,
        llm_predictor: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self._predictor = llm_predictor

    def simulate_workflow(
        self,
        name: str,
        steps: Sequence[Mapping[str, Any]],
        *,
        initial_context: Mapping[str, Any] | None = None,
    ) -> DryRunReport:
        ctx = dict(initial_context or {})
        report = DryRunReport(workflow_name=name)
        for idx, raw in enumerate(steps):
            t0 = time.monotonic()
            sid = str(raw.get("id") or f"step_{idx + 1}")
            sname = str(raw.get("name") or sid)
            action = str(raw.get("action") or raw.get("tool") or "noop")
            step_input = dict(raw.get("args") or raw.get("input") or {})
            side_fx = _has_side_effect(action, raw)
            if side_fx:
                report.total_side_effect_steps += 1

            if self._predictor is not None:
                try:
                    predicted = dict(self._predictor(action, {"step": dict(raw), "context": ctx}))
                except Exception as exc:  # noqa: BLE001
                    predicted = {"simulated": True, "ok": False, "error": str(exc)}
                    report.estimated_ok = False
            else:
                predicted = {
                    "simulated": True,
                    "ok": True,
                    "action": action,
                    "dry_run_summary": f"[DRY RUN] Would execute {action} with {json.dumps(step_input, default=str)[:200]}",
                }
            ctx[sid] = predicted
            report.steps.append(
                SimulatedStep(
                    step_id=sid,
                    name=sname,
                    action=action,
                    simulated_input=step_input,
                    simulated_output=predicted,
                    would_have_side_effects=side_fx,
                    reason=(
                        "Side-effect action intercepted and simulated in Safe Mode"
                        if side_fx
                        else "Read-only / pure step simulated cleanly"
                    ),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            )
        return report


__all__ = ["DryRunReport", "DryRunSimulator", "SimulatedStep"]
