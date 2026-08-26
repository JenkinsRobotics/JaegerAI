from jaeger_agent.loop.turn_budget import TurnBudget, TurnBudgetLimits


def test_turn_budget_tracks_all_dimensions_and_snapshots():
    now = [10.0]
    budget = TurnBudget(TurnBudgetLimits(
        max_tool_calls=10, max_iterations=8, max_elapsed_s=20,
        max_tokens=1000, max_tool_cost=12,
    ), clock=lambda: now[0])
    budget.observe_iteration(3)
    budget.consume_tool(count=2, cost=4.5)
    budget.observe_usage(prompt_tokens=600, completion_tokens=200)
    now[0] = 26.0
    snapshot = budget.snapshot()
    assert snapshot["usage"] == {
        "tool_calls": 2, "iterations": 3, "elapsed_s": 16.0,
        "prompt_tokens": 600, "completion_tokens": 200, "tokens": 800,
        "tool_cost": 4.5,
    }
    assert set(snapshot["warning_dimensions"]) == {"elapsed_s", "tokens"}


def test_turn_budget_preserves_absolute_tool_fuse():
    budget = TurnBudget(TurnBudgetLimits(max_tool_calls=24, max_iterations=50))
    budget.consume_tool(count=24)
    assert budget.halt_reason() == "made 24 tool calls in a single turn"


def test_optional_limits_are_inactive_when_unset():
    now = [0.0]
    budget = TurnBudget(TurnBudgetLimits(max_tool_calls=24, max_iterations=50), clock=lambda: now[0])
    now[0] = 99999.0
    budget.observe_usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert budget.halt_reason() is None


def test_warning_adapts_to_every_configured_dimension():
    budget = TurnBudget(TurnBudgetLimits(
        max_tool_calls=10, max_iterations=10, max_tokens=100,
        max_tool_cost=10, warning_fraction=0.8,
    ))
    budget.observe_iteration(8)
    budget.consume_tool(count=8, cost=8)
    budget.observe_usage(prompt_tokens=70, completion_tokens=10)
    assert set(budget.warning_dimensions()) == {
        "tool_calls", "iterations", "tokens", "tool_cost",
    }
    assert "finish safely" in (budget.warning() or "")
