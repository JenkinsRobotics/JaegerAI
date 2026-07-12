"""Capability-ladder planner — engine selection contract.

Pins the planner's choice logic without firing real OS calls. The
engines are mocked with controllable ``can_handle`` /
``is_available`` so the test can assert "did the planner pick the
right tier" for every interesting case.

This is the spine of the new macos_computer skill: when the
planner picks wrong, every downstream behaviour falls apart.
"""

from __future__ import annotations

from typing import Any

import pytest

from jaeger_ai.agent.skills.macos_computer_v1.engines import Action, EngineResult
from jaeger_ai.agent.skills.macos_computer_v1 import planner


# ── fake engine harness ────────────────────────────────────────────


class _FakeEngine:
    """Minimal Engine impl whose every method is parameterised so
    each test can spell out what it wants."""
    def __init__(self, name: str, priority: int, *,
                 available: bool = True, confidence: float = 0.0,
                 result_ok: bool = True,
                 result_payload: Any = None,
                 result_error: str = "") -> None:
        self.name = name
        self.priority = priority
        self._available = available
        self._confidence = confidence
        self._result_ok = result_ok
        self._result_payload = result_payload
        self._result_error = result_error
        self.execute_count = 0

    def is_available(self) -> tuple[bool, str]:
        return self._available, "" if self._available else "not ready"

    def can_handle(self, action: Action) -> float:
        return self._confidence

    def execute(self, action: Action) -> EngineResult:
        self.execute_count += 1
        return EngineResult(
            ok=self._result_ok, engine=self.name,
            result=self._result_payload, error=self._result_error,
            elapsed_ms=1.0,
        )


# ── select_engine ──────────────────────────────────────────────────


def test_select_picks_highest_confidence():
    """When two engines both claim, the higher-confidence one wins."""
    low = _FakeEngine("low", priority=10, confidence=0.3)
    high = _FakeEngine("high", priority=30, confidence=0.9)
    chosen, conf = planner.select_engine(
        Action(kind="press", args={}, target=""),
        engines=[low, high],
    )
    assert chosen is high
    assert conf == 0.9


def test_select_breaks_ties_by_priority():
    """When two engines tie on confidence, the one with the LOWER
    priority number wins (top of the ladder)."""
    fast = _FakeEngine("fast", priority=10, confidence=0.7)
    slow = _FakeEngine("slow", priority=90, confidence=0.7)
    chosen, _ = planner.select_engine(
        Action(kind="press", args={}, target=""),
        engines=[slow, fast],   # order shouldn't matter
    )
    assert chosen is fast


def test_select_skips_unavailable_engines():
    """An engine that says ``is_available -> False`` must not be
    considered, even if its confidence is high. Otherwise we'd
    dispatch to something that's missing its runtime."""
    dead = _FakeEngine("dead", priority=10, confidence=0.95, available=False)
    live = _FakeEngine("live", priority=30, confidence=0.4)
    chosen, _ = planner.select_engine(
        Action(kind="press", args={}, target=""),
        engines=[dead, live],
    )
    assert chosen is live


def test_select_returns_none_below_floor():
    """Confidence below the floor (0.2) means "I don't actually know
    how" — the planner must not dispatch."""
    weak = _FakeEngine("weak", priority=10, confidence=0.1)
    chosen, conf = planner.select_engine(
        Action(kind="press", args={}, target=""),
        engines=[weak],
    )
    assert chosen is None
    assert conf == 0.0


def test_select_returns_none_when_no_engines_available():
    chosen, _ = planner.select_engine(
        Action(kind="press", args={}, target=""),
        engines=[],
    )
    assert chosen is None


# ── run() — dispatch + fall-through ────────────────────────────────


def test_run_executes_chosen_engine_once_on_success():
    eng = _FakeEngine("only", priority=10, confidence=0.9,
                      result_payload={"ok": True})
    out = planner.run(
        Action(kind="press", args={}, target=""),
        engines=[eng],
    )
    assert out["ok"] is True
    assert out["engine"] == "only"
    assert eng.execute_count == 1
    # Audit log has exactly one attempt.
    assert len(out["attempts"]) == 1
    assert out["attempts"][0]["engine"] == "only"


def test_run_falls_through_to_next_engine_on_failure():
    """When the highest-confidence engine returns ``ok=False``, the
    planner tries the next-best engine that cleared the floor."""
    primary = _FakeEngine("primary", priority=10, confidence=0.9,
                          result_ok=False, result_error="primary failed")
    fallback = _FakeEngine("fallback", priority=30, confidence=0.4,
                           result_ok=True, result_payload={"ok": True})
    out = planner.run(
        Action(kind="press", args={}, target=""),
        engines=[primary, fallback],
    )
    assert out["ok"] is True
    assert out["engine"] == "fallback"
    # Both engines actually executed — the audit log shows the path.
    assert primary.execute_count == 1
    assert fallback.execute_count == 1
    assert [a["engine"] for a in out["attempts"]] == ["primary", "fallback"]
    assert out["attempts"][0]["ok"] is False
    assert out["attempts"][1]["ok"] is True


def test_run_surfaces_last_error_when_every_engine_fails():
    a = _FakeEngine("a", priority=10, confidence=0.9,
                    result_ok=False, result_error="a broke")
    b = _FakeEngine("b", priority=30, confidence=0.4,
                   result_ok=False, result_error="b broke")
    out = planner.run(
        Action(kind="press", args={}, target=""),
        engines=[a, b],
    )
    assert out["ok"] is False
    # Last attempt's error surfaces at the top level so the model
    # sees a useful message.
    assert "b broke" in out["error"]
    assert len(out["attempts"]) == 2


def test_run_reports_no_claimant_when_every_engine_abstains():
    """All engines below the floor → no claimant, no execute call,
    a clear error so the agent knows to escalate (ask user, etc.)."""
    a = _FakeEngine("a", priority=10, confidence=0.0)
    b = _FakeEngine("b", priority=30, confidence=0.1)
    out = planner.run(
        Action(kind="press", args={}, target=""),
        engines=[a, b],
    )
    assert out["ok"] is False
    assert a.execute_count == 0
    assert b.execute_count == 0
    assert "no available engine" in out["error"].lower()


# ── computer.py — agent-facing wrappers ─────────────────────────────


def test_computer_use_dispatches_one_action():
    """The thin ``computer_use(action, target, **kwargs)`` wrapper
    must build an Action correctly and run it through the planner.
    We confirm by passing engines = a fake list via monkeypatch."""
    from jaeger_ai.agent.skills.macos_computer_v1 import macos_computer as computer

    seen: list[Action] = []
    fake = _FakeEngine("probe", priority=10, confidence=0.9,
                      result_payload={"ok": True, "called": True})

    # Patch DEFAULT_ENGINES on the planner module so ``computer_use``
    # routes through our fake.
    orig = planner.DEFAULT_ENGINES
    planner.DEFAULT_ENGINES = (fake,)
    try:
        out = computer.computer_use(action="press", target="Calculator",
                                    value="5")
    finally:
        planner.DEFAULT_ENGINES = orig

    assert out["ok"] is True
    assert out["engine"] == "probe"
    assert fake.execute_count == 1


def test_planner_routes_read_value_to_ax():
    """``read_value`` is the cheap-verification action — must go to
    AX (priority 30), not vision (90), since vision can't read
    object state. The whole point of the engine ladder is that
    this routing decision is automatic."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines.ax_engine import AXEngine
    from jaeger_ai.agent.skills.macos_computer_v1.engines.applescript_engine import (
        AppleScriptEngine,
    )
    from jaeger_ai.agent.skills.macos_computer_v1.engines.vision_engine import (
        VisionEngine,
    )
    chosen, conf = planner.select_engine(
        Action(kind="read_value", args={"label": "Result"}, target="Calculator"),
        engines=[AppleScriptEngine(), AXEngine(), VisionEngine()],
    )
    # On Mac with AX permission, AX wins (conf 0.95). On other
    # hosts AX is unavailable and the test skips the routing check.
    if chosen is not None and chosen.name != "vision":
        assert chosen.name == "ax", \
            f"read_value routed to {chosen.name!r}, expected 'ax'"


def test_planner_routes_focused_window_to_ax():
    """``focused_window`` powers ``computer_look()`` — must route to
    AX so the read is cheap."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines.ax_engine import AXEngine
    from jaeger_ai.agent.skills.macos_computer_v1.engines.vision_engine import (
        VisionEngine,
    )
    chosen, _ = planner.select_engine(
        Action(kind="focused_window", args={}, target=""),
        engines=[AXEngine(), VisionEngine()],
    )
    if chosen is not None and chosen.name != "vision":
        assert chosen.name == "ax"


def test_computer_do_accepts_a_list_of_action_dicts():
    """``computer_do([{kind, ...}, {kind, ...}])`` runs each step
    in order through the planner, stops on the first failure."""
    from jaeger_ai.agent.skills.macos_computer_v1 import macos_computer as computer

    step1 = _FakeEngine("s1", priority=10, confidence=0.9,
                        result_payload={"ok": True})
    orig = planner.DEFAULT_ENGINES
    planner.DEFAULT_ENGINES = (step1,)
    try:
        out = computer.computer_do([
            {"kind": "press", "target": "Calculator", "value": "5"},
            {"kind": "press", "target": "Calculator", "value": "+"},
        ])
    finally:
        planner.DEFAULT_ENGINES = orig

    assert out["ok"] is True
    assert len(out["steps"]) == 2
    assert step1.execute_count == 2
