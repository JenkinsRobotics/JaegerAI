"""Input and output guardrails with tripwires.

Standard followed: OpenAI Agents SDK guardrails (``InputGuardrail`` runs on the
user's input before the agent works, ``OutputGuardrail`` on the agent's final
output; each returns ``GuardrailFunctionOutput(tripwire_triggered=...)`` and a
tripped wire ends the run instead of returning the guarded content). Tool-level
checks stay on the existing ``pre_tool`` hook (Claude Agent SDK ``PreToolUse``).

Register a guardrail with :func:`register_input` / :func:`register_output`. A
guardrail is ``fn(text) -> GuardrailResult | bool | None``; ``True`` or a result
with ``tripwire_triggered`` trips. A guardrail that raises trips (fail closed).
Every trip is reported on the live stream as ``guardrail.tripped``.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuardrailResult:
    tripwire_triggered: bool
    reason: str = ""
    guardrail: str = ""


GuardrailFn = Callable[[str], "GuardrailResult | bool | None"]
_lock = threading.RLock()
_guards: dict[str, list[tuple[str, GuardrailFn]]] = {"input": [], "output": []}


def _register(stage: str, fn: GuardrailFn, name: str | None) -> Callable[[], None]:
    entry = (name or getattr(fn, "__name__", "guardrail"), fn)
    with _lock:
        _guards[stage] = [g for g in _guards[stage] if g[0] != entry[0]] + [entry]

    def unregister() -> None:
        with _lock:
            if entry in _guards[stage]:
                _guards[stage].remove(entry)
    return unregister


def register_input(fn: GuardrailFn, *, name: str | None = None) -> Callable[[], None]:
    return _register("input", fn, name)


def register_output(fn: GuardrailFn, *, name: str | None = None) -> Callable[[], None]:
    return _register("output", fn, name)


def clear() -> None:
    with _lock:
        for stage in _guards:
            _guards[stage].clear()


def run(stage: str, text: str) -> GuardrailResult | None:
    """First tripped guardrail for ``stage`` ("input" | "output"), else None."""
    with _lock:
        guards = list(_guards.get(stage, ()))
    for name, fn in guards:
        try:
            answer = fn(text or "")
        except Exception as exc:  # noqa: BLE001 — cannot answer => trip (fail closed)
            logger.warning("%s guardrail %s failed; tripping", stage, name, exc_info=True)
            answer = GuardrailResult(True, f"guardrail failed: {type(exc).__name__}", name)
        if answer is True:
            answer = GuardrailResult(True, "", name)
        if isinstance(answer, GuardrailResult) and answer.tripwire_triggered:
            result = GuardrailResult(True, answer.reason, answer.guardrail or name)
            from jaeger_agent import live
            live.emit("guardrail.tripped", {"stage": stage, "guardrail": result.guardrail,
                                            "reason": result.reason[:300]})
            return result
    return None


def refusal(stage: str, result: GuardrailResult) -> str:
    what = "your message" if stage == "input" else "my reply"
    why = f": {result.reason}" if result.reason else ""
    return f"[Stopped by the {result.guardrail} {stage} guardrail{why}. I did not send {what} on.]" \
        if stage == "output" else f"[Stopped by the {result.guardrail} input guardrail{why}. I did not act on {what}.]"


__all__ = ["GuardrailResult", "register_input", "register_output", "run", "refusal", "clear"]
