"""update_plan (stateless, validated) and wait (bounded, cancellable)."""

from __future__ import annotations

import pytest

from jaeger_agent.tools.plan import MAX_WAIT_S, normalize_plan, wait_for
from jaeger_agent.util import tool_interrupt


def test_valid_plan_is_echoed_with_counts():
    out = normalize_plan(
        [{"step": "read code", "status": "completed"},
         {"step": "write fix", "status": "in_progress"},
         {"step": "run tests", "status": "pending"}],
        explanation="  started the fix ",
    )
    assert out["ok"] is True
    assert out["summary"] == {"total": 3, "pending": 1, "in_progress": 1, "completed": 1}
    assert out["explanation"] == "started the fix"
    assert out["plan"][1] == {"step": "write fix", "status": "in_progress"}


def test_status_spelling_is_forgiven_and_default_is_pending():
    out = normalize_plan([{"step": "a", "status": "In-Progress"}, {"content": "b"}])
    assert [s["status"] for s in out["plan"]] == ["in_progress", "pending"]


@pytest.mark.parametrize("plan", [None, [], "text", [5], [{"status": "pending"}],
                                  [{"step": "x", "status": "done"}]])
def test_bad_plans_are_rejected_with_a_reason(plan):
    out = normalize_plan(plan)
    assert out["ok"] is False and out["error"]


def test_two_in_progress_steps_are_rejected():
    out = normalize_plan([{"step": "a", "status": "in_progress"}, {"step": "b", "status": "in_progress"}])
    assert out["ok"] is False and "one step" in out["error"]


def test_plan_is_stateless_between_calls():
    normalize_plan([{"step": "first conversation", "status": "pending"}])
    other = normalize_plan([{"step": "second conversation", "status": "pending"}])
    assert [s["step"] for s in other["plan"]] == ["second conversation"]


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_wait_sleeps_the_requested_time():
    c = Clock()
    out = wait_for(2, sleep=c.sleep, clock=c.monotonic)
    assert out["ok"] and out["interrupted"] is False and out["waited_s"] == pytest.approx(2, abs=0.3)


def test_wait_is_capped():
    c = Clock()
    out = wait_for(10_000, sleep=c.sleep, clock=c.monotonic)
    assert out["capped"] is True and out["waited_s"] <= MAX_WAIT_S + 0.3


def test_wait_stops_when_the_turn_is_cancelled():
    c = Clock()
    ticks = []

    def sleep(seconds):
        ticks.append(seconds)
        c.sleep(seconds)
        if len(ticks) == 2:
            tool_interrupt._interrupt.set()

    try:
        out = wait_for(30, sleep=sleep, clock=c.monotonic)
    finally:
        tool_interrupt.clear_interrupt()
    assert out["interrupted"] is True and out["waited_s"] < 5


@pytest.mark.parametrize("value", ["abc", None, -1])
def test_wait_rejects_bad_input(value):
    assert wait_for(value)["ok"] is False


def test_both_tools_are_registered_and_classified():
    from jaeger_agent import tools  # noqa: F401  (registers on import)
    from jaeger_agent.skill_registry.toolset_scoping import TOOLSETS, TOOLSET_SUMMARY

    assert TOOLSETS["planning"] == frozenset({"update_plan", "wait"})
    assert "planning" in TOOLSET_SUMMARY
