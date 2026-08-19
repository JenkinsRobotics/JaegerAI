"""Continuous execution — /auto, /mode, /plan and the turn-level loop.

The slash commands are thin: what matters is that they move the shared
:mod:`jaeger_ai.core.runtime.execution` state (not a TUI-local flag), and
that the worker's post-turn check re-fires a turn exactly when the last
answer promised work it had not done.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from jaeger_ai.core.runtime import autonomy, execution
from jaeger_ai.interfaces.tui import slash_commands as slash
from jaeger_ai.interfaces.tui.app import JaegerTUI


@pytest.fixture(autouse=True)
def _clean_execution_state():
    """The execution mode is process-global (one resident agent per
    instance), so a test that leaves it in ``auto`` would arm the next
    one."""
    execution.reset()
    autonomy.set_autonomy(autonomy.DEFAULT)
    yield
    execution.reset()
    autonomy.set_autonomy(autonomy.DEFAULT)


@pytest.fixture()
def ctx(tmp_path):
    tui = JaegerTUI(skip_model=True)
    yield slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=100),
        instance_dir=tmp_path,
        tui=tui,
    )


# ── slash commands ──────────────────────────────────────────────────


def test_automation_commands_are_registered() -> None:
    for name in ("auto", "mode", "plan", "goal", "stop", "status"):
        assert name in slash._BY_NAME, name


def test_auto_on_off_moves_the_shared_execution_state(ctx) -> None:
    slash.dispatch("/auto on", ctx)
    assert execution.current_mode() == "auto"
    assert ctx.tui._auto_mode is True

    slash.dispatch("/auto off", ctx)
    assert execution.current_mode() == "interactive"
    assert ctx.tui._auto_mode is False
    # Reporting status must not change it.
    slash.dispatch("/auto", ctx)
    assert execution.current_mode() == "interactive"


def test_auto_on_accepts_a_step_budget(ctx) -> None:
    slash.dispatch("/auto on 6", ctx)
    assert execution.run_progress()["budget"] == 6


def test_mode_switches_execution_modes(ctx) -> None:
    slash.dispatch("/mode auto", ctx)
    assert execution.current_mode() == "auto"
    slash.dispatch("/mode supervised", ctx)
    assert execution.current_mode() == "supervised"
    # Supervised keeps the confirm gate on every mutation.
    assert autonomy.current_autonomy() == "ask"
    slash.dispatch("/mode interactive", ctx)
    assert execution.current_mode() == "interactive"


def test_mode_leaves_the_brain_presets_alone(ctx, monkeypatch) -> None:
    """``/mode high`` is the model-swap axis and must still reach it —
    the execution modes were added alongside it, not on top of it."""
    calls: list[str] = []
    from jaeger_ai.core.runtime import modes as brain_modes
    monkeypatch.setattr(
        brain_modes, "set_mode",
        lambda name: calls.append(name) or {"ok": True, "mode": name})
    slash.dispatch("/mode high", ctx)
    assert calls == ["high"]
    assert execution.current_mode() == "interactive"


def test_plan_opens_a_run_and_hands_back_a_prompt(ctx) -> None:
    res = slash.dispatch("/plan Distil every note into actions", ctx)
    assert execution.current_mode() == "auto"
    assert execution.run_active()
    assert execution.run_progress()["objective"] == \
        "Distil every note into actions"
    prompt = res.extras["plan_prompt"]
    assert "Distil every note into actions" in prompt
    # The plan and its execution are one turn — the prompt must say so,
    # or the model ends on the plan and the run stalls at step 1.
    assert "execute" in prompt.lower()


def test_plan_without_an_objective_does_nothing(ctx) -> None:
    res = slash.dispatch("/plan", ctx)
    assert res.extras == {}
    assert execution.current_mode() == "interactive"


def test_stop_halts_the_run_and_returns_to_interactive(ctx) -> None:
    slash.dispatch("/plan Process the backlog", ctx)
    execution.record_step()
    slash.dispatch("/stop", ctx)
    assert execution.stop_requested()
    assert execution.current_mode() == "interactive"


# ── the turn-level continuation loop ────────────────────────────────


def _tui() -> JaegerTUI:
    return JaegerTUI(skip_model=True)


def test_narrated_promise_re_fires_the_turn() -> None:
    tui = _tui()
    execution.set_execution_mode("auto")
    execution.begin_run("read every folder")
    tui._last_answer = ("I am starting the analysis. Let me begin by "
                        "reading the first folder.")
    nxt = tui._post_turn_auto_check()
    assert nxt is not None and "Continue the task NOW" in nxt
    assert execution.run_progress()["step"] == 1
    assert execution.run_progress()["phase"] == "executing"


def test_interactive_mode_never_re_fires() -> None:
    tui = _tui()
    execution.set_execution_mode("interactive")
    tui._last_answer = "Let me begin by reading the first folder."
    assert tui._post_turn_auto_check() is None


def test_completion_buys_one_verification_pass_then_settles() -> None:
    tui = _tui()
    execution.set_execution_mode("auto")
    execution.begin_run("distil every note")
    tui._last_answer = "All folders processed. Here is the final summary: ..."

    verify = tui._post_turn_auto_check()
    assert verify is not None and "VERIFICATION STEP" in verify
    assert execution.run_progress()["phase"] == "verifying"

    # The verified answer settles the run — no second verify pass.
    tui._last_answer = "I've finished; verified the file exists."
    assert tui._post_turn_auto_check() is None
    assert execution.run_active() is False


def test_question_ends_the_run_rather_than_talking_over_the_user() -> None:
    tui = _tui()
    execution.set_execution_mode("auto")
    execution.begin_run("distil every note")
    tui._last_answer = "Which folder should I start with?"
    assert tui._post_turn_auto_check() is None
    assert execution.run_active() is False


def test_budget_exhaustion_stops_the_run() -> None:
    tui = _tui()
    execution.set_execution_mode("auto")
    execution.begin_run("read every folder", budget=1)
    tui._last_answer = "Let me begin by reading the next folder."
    assert tui._post_turn_auto_check() is not None      # step 1 of 1
    assert tui._post_turn_auto_check() is None          # budget spent
    assert execution.run_active() is False


def test_stop_request_is_honoured_at_the_turn_boundary() -> None:
    tui = _tui()
    execution.set_execution_mode("auto")
    execution.begin_run("read every folder")
    tui._last_answer = "Let me begin by reading the next folder."
    execution.request_stop("Ctrl-C")
    assert tui._post_turn_auto_check() is None
    assert execution.run_active() is False
    # The flag is consumed, so the next run starts clean.
    assert execution.stop_requested() is False


def test_status_bar_shows_the_step_counter() -> None:
    tui = _tui()
    assert tui._autonomous_fragment() is None
    execution.set_execution_mode("auto")
    execution.begin_run("objective")
    execution.record_step()
    style, text = tui._autonomous_fragment()
    assert "1/" in text and "AUTO" in text
    execution.request_stop("x")
    assert "stopping" in tui._autonomous_fragment()[1]
