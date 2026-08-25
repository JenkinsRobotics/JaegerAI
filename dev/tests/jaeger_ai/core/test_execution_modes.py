"""Execution modes — how long a request keeps running.

Covers the mode switch and its coupling to the confirm gate, the step
budget, the cooperative stop, and the one-shot verification pass. The
turn-level continuation that consumes all of this is exercised in
``dev/tests/jaeger_ai/interfaces/test_tui_automation.py``.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import autonomy, execution


@pytest.fixture(autouse=True)
def _clean_state():
    execution.reset()
    autonomy.set_autonomy(autonomy.DEFAULT)
    yield
    execution.reset()
    autonomy.set_autonomy(autonomy.DEFAULT)


def test_default_is_interactive_and_not_continuous() -> None:
    assert execution.current_mode() == execution.DEFAULT == "interactive"
    assert execution.is_continuous() is False
    assert set(execution.list_modes()) == {
        "interactive", "auto", "supervised", "deepthink"}


@pytest.mark.parametrize(
    "typed,expected",
    [("auto", "auto"), ("full-auto", "auto"), ("ON", "auto"), ("agent", "auto"),
     ("step", "supervised"), ("plan", "supervised"),
     ("chat", "interactive"), ("ask", "interactive"), ("coder", "deepthink"),
     ("nonsense", None), ("", None),
     # ``normal`` belongs to the brain presets, not here — /mode routes it
     # to a model swap, so this module must not claim it.
     ("normal", None)],
)
def test_normalize_accepts_the_spellings_users_type(typed, expected) -> None:
    assert execution.normalize(typed) == expected


def test_auto_loosens_the_confirm_gate_and_interactive_restores_it() -> None:
    autonomy.set_autonomy("scoped")
    res = execution.set_execution_mode("auto")
    assert res["ok"] and res["autonomy"] == "auto"
    # An unattended run that stops at a y/n prompt is the failure this
    # coupling exists to prevent.
    assert autonomy.current_autonomy() == "auto"

    execution.set_execution_mode("interactive")
    assert autonomy.current_autonomy() == "scoped"


def test_supervised_pins_the_gate_to_ask() -> None:
    autonomy.set_autonomy("auto")
    execution.set_execution_mode("supervised")
    assert autonomy.current_autonomy() == "ask"
    execution.set_execution_mode("interactive")
    assert autonomy.current_autonomy() == "auto"


def test_unknown_mode_is_refused_without_changing_state() -> None:
    execution.set_execution_mode("auto")
    bad = execution.set_execution_mode("turbo")
    assert not bad["ok"] and "turbo" in bad["error"]
    assert execution.current_mode() == "auto"


def test_run_counts_steps_against_a_budget() -> None:
    execution.set_execution_mode("auto")
    execution.begin_run("distil every note", budget=3)
    assert execution.run_active() and execution.steps_left() == 3
    assert [execution.record_step() for _ in range(3)] == [1, 2, 3]
    assert execution.steps_left() == 0

    progress = execution.run_progress()
    assert progress["objective"] == "distil every note"
    assert progress["step"] == 3 and progress["budget"] == 3


def test_budget_reads_the_env_override(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_AUTO_MAX_STEPS", "7")
    assert execution.max_steps() == 7
    monkeypatch.setenv("JAEGER_AUTO_MAX_STEPS", "not-a-number")
    assert execution.max_steps() == execution.DEFAULT_MAX_STEPS


def test_automation_config_exposes_the_two_budgets() -> None:
    from jaeger_ai.core.instance.schemas import AutomationConfig
    cfg = AutomationConfig()
    assert cfg.inner_max_iterations == 24
    assert cfg.job_max_steps == 100


def test_inner_max_chat_vs_batch(monkeypatch) -> None:
    monkeypatch.delenv("JAEGER_INNER_MAX", raising=False)
    assert execution.inner_max() == execution.INNER_MAX_CHAT
    assert execution.inner_max(batch=True) == execution.INNER_MAX_AUTO
    execution.set_execution_mode("auto")
    assert execution.inner_max() == execution.INNER_MAX_AUTO
    monkeypatch.setenv("JAEGER_INNER_MAX", "12")
    assert execution.inner_max() == 12
    assert execution.inner_max(batch=True) == 12


def test_stop_is_cooperative_and_clears_on_a_new_run() -> None:
    execution.set_execution_mode("auto")
    execution.begin_run("something long")
    execution.request_stop("/stop")
    assert execution.stop_requested()
    # A new run is a fresh mandate — the old stop must not kill it.
    execution.begin_run("something else")
    assert not execution.stop_requested()


def test_verification_is_offered_once_per_run() -> None:
    execution.set_execution_mode("auto")
    execution.begin_run("write the summary file")
    assert execution.needs_verification() is True
    execution.mark_verified()
    assert execution.needs_verification() is False

    # A run with no stated objective has nothing to verify against.
    execution.begin_run("")
    assert execution.needs_verification() is False


def test_leaving_auto_ends_the_run() -> None:
    execution.set_execution_mode("auto")
    execution.begin_run("objective")
    execution.record_step()
    execution.set_execution_mode("interactive")
    assert execution.run_active() is False
    # The counters survive for /status after the run ends.
    assert execution.run_progress()["step"] == 1
