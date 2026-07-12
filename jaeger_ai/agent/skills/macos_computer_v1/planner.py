"""Capability-ladder planner — picks the right engine for each step.

Two responsibilities:

  * :func:`select_engine` — for ONE :class:`Action`, find the engine
    that should run it. Polls every available engine's
    ``can_handle`` and picks the one with the highest confidence at
    or above the threshold. Ties break by ladder priority
    (lower = wins) so AppleScript beats AX beats vision on a tie.
  * :func:`run` — drive ONE action through the selected engine,
    falling through to the next engine if the chosen one returns
    ``ok=False``. Records which engine handled each attempt so the
    caller can audit-log the path.

There is intentionally NO "decompose a natural-language goal into
steps" logic here today. ``computer_do(goal)`` will accept either
a single semantic action dict OR a list of them; the *model* does
the goal → steps decomposition. That keeps the planner small and
predictable, and lets us bench engine selection independently
from prompt engineering.
"""

from __future__ import annotations

import time
from typing import Iterable

from jaeger_ai.agent.skills.macos_computer_v1.engines import Action, Engine, EngineResult
from jaeger_ai.agent.skills.macos_computer_v1.engines.applescript_engine import AppleScriptEngine
from jaeger_ai.agent.skills.macos_computer_v1.engines.ax_engine import AXEngine
from jaeger_ai.agent.skills.macos_computer_v1.engines.browser_engine import BrowserEngine
from jaeger_ai.agent.skills.macos_computer_v1.engines.vision_engine import VisionEngine


# Default ladder order, top to bottom (highest priority first).
# Independent of the engines' own ``priority`` field — that field
# is documentation; this list is what the planner actually iterates.
DEFAULT_ENGINES: tuple[Engine, ...] = (
    AppleScriptEngine(),
    BrowserEngine(),
    AXEngine(),
    VisionEngine(),
)


# Engines must clear this confidence to be considered. Anything
# below is treated as "I don't actually know how to do this" so we
# don't dispatch to a tier just because it weakly claimed.
_CONFIDENCE_FLOOR = 0.2


def select_engine(
    action: Action,
    engines: Iterable[Engine] | None = None,
) -> tuple[Engine | None, float]:
    """Pick the engine that should run ``action``. Returns
    ``(engine, confidence)`` — engine is ``None`` when no available
    engine cleared :data:`_CONFIDENCE_FLOOR`.

    ``engines=None`` resolves to :data:`DEFAULT_ENGINES` AT CALL
    TIME — important so tests that monkeypatch the module-level
    constant see the patched list."""
    if engines is None:
        engines = DEFAULT_ENGINES
    best_engine: Engine | None = None
    best_conf = 0.0
    for eng in engines:
        ready, _detail = eng.is_available()
        if not ready:
            continue
        conf = eng.can_handle(action)
        if conf < _CONFIDENCE_FLOOR:
            continue
        # Highest confidence wins. On tie, lower priority (better
        # tier) wins — applescript over ax over vision.
        if conf > best_conf or (
            conf == best_conf
            and best_engine is not None
            and getattr(eng, "priority", 99) < getattr(best_engine, "priority", 99)
        ):
            best_engine = eng
            best_conf = conf
    return best_engine, best_conf


def run(
    action: Action,
    engines: Iterable[Engine] | None = None,
) -> dict:
    """Drive ``action`` through the ladder. Tries the best engine
    first; on ``ok=False`` falls through to the next-best (≥
    floor) engine; returns the FIRST successful result OR the
    last attempt's error.

    ``engines=None`` resolves to :data:`DEFAULT_ENGINES` AT CALL
    TIME — see :func:`select_engine` for why.

    Audit log goes in ``"attempts"`` — list of
    ``{engine, confidence, ok, elapsed_ms, error?}`` so the agent
    (or the bench) can see which path actually ran."""
    if engines is None:
        engines = DEFAULT_ENGINES
    started = time.perf_counter()
    # Build the candidate list (every available engine that clears
    # the floor), sorted by confidence desc, priority asc.
    candidates: list[tuple[float, Engine]] = []
    for eng in engines:
        ready, _detail = eng.is_available()
        if not ready:
            continue
        conf = eng.can_handle(action)
        if conf >= _CONFIDENCE_FLOOR:
            candidates.append((conf, eng))
    candidates.sort(
        key=lambda pair: (-pair[0], getattr(pair[1], "priority", 99))
    )

    attempts: list[dict] = []
    last_result: EngineResult | None = None
    for conf, eng in candidates:
        result = eng.execute(action)
        last_result = result
        attempts.append({
            "engine": eng.name,
            "confidence": round(conf, 2),
            "ok": result.ok,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error if not result.ok else "",
        })
        if result.ok:
            return {
                "ok": True,
                "engine": eng.name,
                "result": result.result,
                "attempts": attempts,
                "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
    # No engine succeeded — surface the last attempt's error (or
    # a generic "nothing claimed it" message when the candidate
    # list was empty).
    if last_result is None:
        return {
            "ok": False,
            "error": (f"no available engine claimed action "
                      f"kind={action.kind!r} target={action.target!r}"),
            "attempts": attempts,
            "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    return {
        "ok": False,
        "engine": last_result.engine,
        "error": last_result.error or "every engine returned ok=False",
        "attempts": attempts,
        "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }


__all__ = ["DEFAULT_ENGINES", "Action", "run", "select_engine"]
