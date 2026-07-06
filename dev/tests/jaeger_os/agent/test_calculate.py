"""The ``calculate`` tool's safe arithmetic evaluator.

Regression focus (py-math-check, scenario suite 2026-07-06): a 4B asked
"sqrt(1444), is it even?" computed 38, then called
``calculate("38.0 % 2 == 0")`` — which raised "unsupported expression"
because the evaluator handled only arithmetic, not the comparison. The
tool error derailed the turn into a PLAN-retry that never ran, so the
answer never concluded "38, even". Comparisons + boolean ops now
evaluate, letting the tool answer the evenness check directly.
"""

from __future__ import annotations

from jaeger_os.agent.tools.time_and_math import calculate


def test_arithmetic_still_works():
    assert calculate("2 + 2")["result"] == 4
    assert calculate("sqrt(1444)")["result"] == 38
    assert calculate("38 % 2")["result"] == 0


def test_evenness_comparison_evaluates():
    # The exact expression that derailed py-math-check.
    assert calculate("38.0 % 2 == 0")["result"] is True
    assert calculate("37 % 2 == 0")["result"] is False


def test_comparison_operators():
    assert calculate("5 > 3")["result"] is True
    assert calculate("3 >= 3")["result"] is True
    assert calculate("2 < 1")["result"] is False
    assert calculate("3 != 3")["result"] is False
    assert calculate("4 == 4")["result"] is True


def test_chained_comparison():
    assert calculate("1 < 2 < 3")["result"] is True
    assert calculate("1 < 5 < 3")["result"] is False


def test_boolean_ops():
    assert calculate("2 > 0 and 4 % 2 == 0")["result"] is True
    assert calculate("1 > 2 or 4 % 2 == 0")["result"] is True
    assert calculate("1 > 2 and 4 % 2 == 0")["result"] is False


def test_nested_sqrt_evenness():
    # The whole "is sqrt(1444) even?" in one expression.
    assert calculate("sqrt(1444) % 2 == 0")["result"] is True


def test_unsupported_still_errors_cleanly():
    # A name reference is still refused, as a structured error (never raises).
    r = calculate("foo + 1")
    assert "error" in r and "result" not in r
