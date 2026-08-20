"""The 24/7 idle decision — order, not I/O."""

from __future__ import annotations

from jaeger_ai.core.runtime.idle_supervisor import Action, decide, window_elapsed


def test_busy_wins_over_everything():
    assert decide(
        busy=True,
        has_completions=True,
        idle_ready=True,
        has_deep_think=True,
        has_board=True,
        heartbeat_due=True,
    ) is Action.SKIP


def test_completions_outrank_board_and_heartbeat():
    """Hermes async-delegation rail: a finished child must not wait
    behind a standing checklist."""
    assert decide(
        has_completions=True,
        idle_ready=True,
        has_board=True,
        heartbeat_due=True,
    ) is Action.COMPLETION


def test_deep_think_beats_the_board_when_the_window_has_elapsed():
    assert decide(
        idle_ready=True, has_deep_think=True, has_board=True,
    ) is Action.DEEP_THINK


def test_board_beats_heartbeat_when_the_window_has_elapsed():
    assert decide(
        idle_ready=True, has_board=True, heartbeat_due=True,
    ) is Action.BOARD


def test_heartbeat_fires_even_when_the_board_is_empty():
    assert decide(heartbeat_due=True) is Action.HEARTBEAT


def test_nothing_due_is_idle():
    assert decide() is Action.IDLE


def test_board_does_not_run_before_the_idle_window():
    assert decide(
        idle_ready=False, has_board=True, heartbeat_due=False,
    ) is Action.IDLE


def test_window_elapsed_zero_is_off():
    assert window_elapsed(0, quiet_for=10_000) is False
    assert window_elapsed(60, quiet_for=59) is False
    assert window_elapsed(60, quiet_for=60) is True
