"""Tool-argument coercion for local-model output drift (standalone jaeger-tools module)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

COMMON_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "target": ("url", "uri", "link", "path", "site", "website"),
    "query": ("q", "search_query", "text", "prompt", "term", "keyword", "keywords"),
    "url": ("target", "uri", "link"),
    "path": ("file_path", "filepath", "filename", "file"),
    "command": ("cmd", "script"),
    "expression": ("expr", "formula", "math"),
    "location": ("city", "place", "loc"),
}


def coerce_args(args: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce ``args`` toward the types declared in ``schema``."""
    if not isinstance(args, dict) or not args:
        return args
    if not isinstance(schema, dict):
        return args

    properties = schema.get("properties") or {}
    if not properties:
        return args

    out = dict(args)

    for target_prop, aliases in COMMON_PARAM_ALIASES.items():
        if target_prop in properties and target_prop not in out:
            for alias in aliases:
                if alias in out and alias not in properties:
                    out[target_prop] = out.pop(alias)
                    break

    if len(out) == 1 and any(k in out for k in ("value", "text", "_raw_arguments")):
        for unkeyed in ("value", "text", "_raw_arguments"):
            if unkeyed in out and unkeyed not in properties:
                unkeyed_val = out[unkeyed]
                req = [r for r in (schema.get("required") or []) if r in properties]
                if len(req) == 1 and req[0] not in out:
                    out[req[0]] = unkeyed_val
                    out.pop(unkeyed, None)
                    break
                elif len(properties) == 1:
                    prop_name = next(iter(properties.keys()))
                    if prop_name not in out:
                        out[prop_name] = unkeyed_val
                        out.pop(unkeyed, None)
                        break

    for key, value in list(out.items()):
        prop_schema = properties.get(key)
        if not isinstance(prop_schema, dict):
            continue
        expected = prop_schema.get("type")

        if (
            expected == "array"
            and value is not None
            and not isinstance(value, (list, tuple))
        ):
            if isinstance(value, str):
                coerced = _coerce_value(value, expected, prop_schema)
                if coerced is not value:
                    out[key] = coerced
                    continue
                if value.strip().startswith("["):
                    logger.warning(
                        "coerce_args: %s looks like a JSON array string "
                        "but could not be parsed; wrapping as single element instead",
                        key,
                    )
                out[key] = [value]
                continue
            out[key] = [value]
            continue

        if not isinstance(value, str):
            continue
        if not expected and not _schema_allows_null(prop_schema):
            continue
        coerced = _coerce_value(value, expected, prop_schema)
        if coerced is not value:
            out[key] = coerced

    return out


def _coerce_value(
    value: str,
    expected_type: str | list[str] | None,
    schema: dict[str, Any] | None,
) -> Any:
    if _schema_allows_null(schema) and value.strip().lower() == "null":
        return None
    if isinstance(expected_type, list):
        for t in expected_type:
            result = _coerce_value(value, t, schema)
            if result is not value:
                return result
        return value
    if expected_type in {"integer", "number"}:
        return _coerce_number(value, integer_only=(expected_type == "integer"))
    if expected_type == "boolean":
        return _coerce_boolean(value)
    if expected_type == "array":
        return _coerce_json(value, list)
    if expected_type == "object":
        return _coerce_json(value, dict)
    if expected_type == "null" and value.strip().lower() == "null":
        return None
    return value


def _schema_allows_null(schema: dict[str, Any] | None) -> bool:
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    if schema.get("nullable") is True:
        return True
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict) and variant.get("type") == "null":
                return True
    return False


def _coerce_json(value: str, expected_python_type: type) -> Any:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value
    if isinstance(parsed, expected_python_type):
        return parsed
    return value


def _coerce_number(value: str, *, integer_only: bool = False) -> Any:
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return value
    if f != f or f in (float("inf"), float("-inf")):
        return value
    if f == int(f):
        return int(f)
    if integer_only:
        return value
    return f


def _coerce_boolean(value: str) -> Any:
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return value


__all__ = ["COMMON_PARAM_ALIASES", "coerce_args"]
