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

from ._common import _require_layout


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
