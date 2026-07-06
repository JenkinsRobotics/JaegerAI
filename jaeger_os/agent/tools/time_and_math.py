"""Time, math, and machine-state skills.

  • get_time(timezone)
  • calculate(expression)
  • system_status()

All three are skip-final candidates — the dict result IS the answer.
"""

from __future__ import annotations

import ast
import datetime as dt
import operator as op
import os
import platform
import shutil
from typing import Any

from jaeger_os.core.context import _require_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.agent.schemas.tool_registry import register_tool_from_function


def get_time(timezone: str | None = None) -> dict[str, Any]:
    """The current date, day of week, year and time — local, or in a
    specific IANA timezone if provided. The source of truth for any
    question about the present moment; never answer those from memory.

    Returns explicit ``date`` / ``weekday`` / ``year`` fields alongside
    ``datetime`` so the answer can't be misread."""
    if timezone:
        try:
            from zoneinfo import ZoneInfo
            now = dt.datetime.now(ZoneInfo(timezone))
        except Exception as exc:
            return {"error": f"unknown timezone: {timezone!r} ({exc})"}
    else:
        now = dt.datetime.now().astimezone()
    return {
        "datetime": now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "date": now.strftime("%A, %B %d, %Y"),
        "weekday": now.strftime("%A"),
        "year": now.year,
        "time": now.strftime("%I:%M %p"),
        "iso": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
    }


_CALC_OPS: dict[type, Any] = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv, ast.USub: op.neg, ast.UAdd: op.pos,
}

# Comparison + boolean operators. A model asked "is N even?" naturally
# writes ``N % 2 == 0`` — without these the calculator raised
# "unsupported expression", and a 4B derailed into a PLAN-retry that never
# ran (py-math-check, scenario suite 2026-07-06). Supporting comparisons
# lets the tool answer the boolean directly. Still pure/safe: no names,
# no calls beyond the math whitelist.
_CALC_CMP: dict[type, Any] = {
    ast.Eq: op.eq, ast.NotEq: op.ne,
    ast.Lt: op.lt, ast.LtE: op.le,
    ast.Gt: op.gt, ast.GtE: op.ge,
}

# Whitelist of safe single-arg math calls. sqrt is the bench-driving case —
# without it, Gemma free-texts "square root of N" because it correctly infers
# the calculator can't handle `sqrt(...)`. abs / log / log10 / exp / sin / cos
# / tan are cheap to include and round out the surface a model is likely to
# try without unlocking anything dangerous.
import math
_CALC_FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt, "abs": abs, "log": math.log, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "floor": math.floor, "ceil": math.ceil, "round": round,
}


def _calc_eval(node: Any) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    if isinstance(node, ast.Compare):
        # Chained comparisons (a < b < c) are folded left-to-right the way
        # Python does: every link must hold. Common single-link case
        # (``x == 0``) is just one iteration.
        left = _calc_eval(node.left)
        for cmp_op, comparator in zip(node.ops, node.comparators):
            fn = _CALC_CMP.get(type(cmp_op))
            if fn is None:
                raise ValueError(f"unsupported comparison: {type(cmp_op).__name__}")
            right = _calc_eval(comparator)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        # ``and`` / ``or`` over already-safe operands (e.g. "N>0 and N%2==0").
        vals = [_calc_eval(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
        raise ValueError(f"unsupported boolean op: {type(node.op).__name__}")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _CALC_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"unsupported function: {node.func.id}")
        if len(node.args) != 1 or node.keywords:
            raise ValueError(f"{node.func.id}() takes exactly one positional arg")
        return fn(_calc_eval(node.args[0]))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


def calculate(expression: str) -> dict[str, Any]:
    """Evaluate a safe arithmetic expression.

    Supports + - * / ** % // and single-arg math calls: sqrt, abs, log,
    log10, exp, sin, cos, tan, floor, ceil, round. Square root: pass
    `sqrt(12345)` (preferred) or `12345 ** 0.5`.

    Returns ``{expression, result}`` on success or ``{expression, error}``
    on any evaluation failure (division by zero, malformed input,
    unsupported operator, math-domain error, etc.). The tool NEVER
    raises to the agent loop — the agent should see a structured
    error dict it can surface to the user.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _calc_eval(tree.body)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return {"expression": expression, "result": result}
    except ZeroDivisionError:
        return {"expression": expression,
                "error": "division by zero (undefined)"}
    except (SyntaxError, ValueError, TypeError, OverflowError) as exc:
        return {"expression": expression,
                "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        # Catch-all so a never-seen math edge case (e.g. complex result
        # from sqrt(-1)) doesn't bubble up and kill the agent turn.
        return {"expression": expression,
                "error": f"{type(exc).__name__}: {exc}"}


def system_status() -> dict[str, Any]:
    layout = _require_layout()
    total, used, free = shutil.disk_usage(layout.root)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": load_avg,
        "instance": str(layout.root),
        "disk": {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "free_gb": round(free / 1024**3, 2),
        },
    }


@register_tool_from_function(name="get_time", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="time", operation="get_time",
               summary="read the current time")
def _t_get_time(timezone: str | None = None) -> dict:
    """The current date, day of the week, year, and time — the ONLY
    source of truth for "what day/date/year/time is it", "what's
    today", and similar. Your training data is frozen in the past, so
    a date or year answered from memory will be WRONG — always call
    this for anything about the present moment. Optional IANA
    timezone (e.g. 'Asia/Shanghai')."""
    return get_time(timezone=timezone)


@register_tool_from_function(name="calculate", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="math", operation="calculate",
               summary="evaluate an arithmetic expression")
def _t_calculate(expression: str) -> dict:
    """Evaluate a safe arithmetic expression. Supports + - * / ** % //
    and single-arg sqrt/abs/log/log10/exp/sin/cos/tan/floor/ceil/round.
    For "square root of N" call calculate("sqrt(N)")."""
    return calculate(expression=expression)
