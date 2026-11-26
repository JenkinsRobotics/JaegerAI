"""Safe zero-eval workflow expression evaluator (Agno CEL-inspired).

Evaluates UI-editable branch/loop conditions (e.g. ``state.score >= 8 and not state.dry_run``)
using a strict Python AST allowlist. Attribute traversal blocks dunders, function calls
are restricted to a tiny pure allowlist (``len``, ``lower``, ``upper``, ``contains``),
and ``eval()``/``exec()`` are never invoked.
"""

from __future__ import annotations

import ast
from typing import Any, Mapping


class UnsafeExpressionError(ValueError):
    """Raised when a workflow condition uses disallowed syntax or operations."""


_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}

_CMP_OPS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_SAFE_FUNCS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "min": min,
    "max": max,
    "lower": lambda s: str(s).lower(),
    "upper": lambda s: str(s).upper(),
    "contains": lambda container, item: item in container,
}


def validate_condition(expr: str) -> ast.Expression:
    if not isinstance(expr, str) or not expr.strip():
        raise UnsafeExpressionError("Expression must be a non-empty string")
    if len(expr) > 1024:
        raise UnsafeExpressionError("Expression exceeds maximum length (1024 chars)")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"Invalid expression syntax: {exc}") from exc
    _validate_node(tree.body)
    return tree


def _validate_node(node: ast.AST) -> None:
    if isinstance(node, (ast.Constant, ast.Name)):
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise UnsafeExpressionError(f"Private identifier disallowed: {node.id!r}")
        return
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _validate_node(v)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _validate_node(node.operand)
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, ast.Compare):
        _validate_node(node.left)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP_OPS:
                raise UnsafeExpressionError(f"Comparison operator disallowed: {type(op).__name__}")
            _validate_node(comp)
        return
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise UnsafeExpressionError(f"Private attribute access disallowed: {node.attr!r}")
        _validate_node(node.value)
        return
    if isinstance(node, ast.Subscript):
        _validate_node(node.value)
        _validate_node(node.slice)
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            _validate_node(elt)
        return
    if isinstance(node, ast.IfExp):
        _validate_node(node.test)
        _validate_node(node.body)
        _validate_node(node.orelse)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS or node.keywords:
            raise UnsafeExpressionError("Only allowlisted pure positional helper calls are permitted")
        for arg in node.args:
            _validate_node(arg)
        return
    raise UnsafeExpressionError(f"Disallowed syntax node: {type(node).__name__}")


def _eval_node(node: ast.AST, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            res: Any = True
            for v in node.values:
                res = _eval_node(v, env)
                if not res:
                    return res
            return res
        res = False
        for v in node.values:
            res = _eval_node(v, env)
            if res:
                return res
        return res
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not val
        if isinstance(node.op, ast.USub):
            return -val
        return +val
    if isinstance(node, ast.BinOp):
        return _BIN_OPS[type(node.op)](_eval_node(node.left, env), _eval_node(node.right, env))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, env)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Attribute):
        base = _eval_node(node.value, env)
        if isinstance(base, Mapping):
            return base.get(node.attr)
        return getattr(base, node.attr, None)
    if isinstance(node, ast.Subscript):
        base = _eval_node(node.value, env)
        key = _eval_node(node.slice, env)
        return base[key] if base is not None else None
    if isinstance(node, ast.List):
        return [_eval_node(e, env) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, env) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_node(e, env) for e in node.elts}
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body if _eval_node(node.test, env) else node.orelse, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _SAFE_FUNCS[node.func.id]
        return fn(*(_eval_node(a, env) for a in node.args))
    raise UnsafeExpressionError(f"Unsupported node: {type(node).__name__}")


def evaluate_condition(expr: str, context: Mapping[str, Any]) -> Any:
    """Validate and safely evaluate ``expr`` against ``context`` without ``eval()``."""
    tree = validate_condition(expr)
    return _eval_node(tree.body, context)


__all__ = ["UnsafeExpressionError", "evaluate_condition", "validate_condition"]
