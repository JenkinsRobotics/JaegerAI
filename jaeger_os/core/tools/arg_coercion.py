"""Tool-argument coercion for local-model output drift.

Open-weight models (Gemma, Qwen, GLM, DeepSeek) frequently emit
tool-call arguments with type drift that strict JSON Schema validation
rejects:

  • Integers as strings: ``{"limit": "5"}`` instead of ``{"limit": 5}``
  • Booleans as strings: ``{"flag": "true"}``
  • Scalars where the schema expects an array: ``{"urls": "https://a"}``
    instead of ``{"urls": ["https://a"]}``
  • JSON strings instead of native arrays / objects:
    ``{"tags": '["a","b"]'}``
  • The literal string ``"null"`` instead of ``None`` for nullable fields

Pydantic v2 handles most string→number coercion natively but **not** the
array-wrap case, and not all schemas pass through Pydantic — the
internal :class:`ToolDef.args_model` does, but adapters that render
schemas for the wire (Anthropic, OpenAI) need the coerced shape before
validation fires.

The implementation is ported verbatim from
:mod:`python_hermes_agent.upstream.model_tools.coerce_tool_args` with
the registry plumbing replaced by an explicit JSON-schema parameter so
the helper is reusable outside the agent registry (e.g. inside tests
or MCP tool bridges).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def coerce_args(args: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce ``args`` toward the types declared in ``schema``.

    ``schema`` is a JSON Schema fragment shaped like
    ``{"type": "object", "properties": {...}}`` (the OpenAI tool
    ``parameters`` shape). Passing ``None`` or a non-dict schema means
    "no coercion possible" — return args unchanged. Non-dict ``args``
    also pass through.

    Coercion is best-effort: on parse failure the original value
    survives, the caller's strict validator decides what to do. Calls
    to this should always be paired with a subsequent Pydantic /
    JSON-Schema validation pass — coercion only handles known drift,
    not arbitrary repair.
    """
    if not isinstance(args, dict) or not args:
        return args
    if not isinstance(schema, dict):
        return args

    properties = (schema.get("properties") or {})
    if not properties:
        return args

    out = dict(args)  # don't mutate caller's dict — adapters reuse it
    for key, value in list(out.items()):
        prop_schema = properties.get(key)
        if not isinstance(prop_schema, dict):
            continue
        expected = prop_schema.get("type")

        # Array-wrap: scalar where the schema declares ``type: array``.
        # Strings go through the regular coercion first so a
        # JSON-encoded array (``'["a","b"]'``) gets parsed cleanly
        # instead of being wrapped as ``['["a","b"]']``.
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
                # JSON-array-looking string that failed to parse — warn
                # and fall back to single-element list rather than
                # silently dropping the call.
                if value.strip().startswith("["):
                    logger.warning(
                        "coerce_args: %s looks like a JSON array string "
                        "but could not be parsed; wrapping as single "
                        "element instead", key,
                    )
                out[key] = [value]
                continue
            out[key] = [value]
            continue

        # Scalar coercion: only meaningful when the model emitted a
        # string for a non-string slot.
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
    """Coerce a single string value toward ``expected_type``.

    Returns the original string when coercion isn't applicable so the
    caller can leave the value untouched and let strict validation
    surface a clean error."""
    if _schema_allows_null(schema) and value.strip().lower() == "null":
        return None

    # Union type — try each branch in order and return the first hit.
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
    """Detect whether a JSON-Schema fragment explicitly permits null —
    either via ``type: null``, ``type: [..., "null"]``, an explicit
    ``nullable: true``, or an ``anyOf``/``oneOf`` variant of
    ``type: null``. The argument coercer uses this to map the literal
    string ``"null"`` to Python ``None``."""
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
    """Parse ``value`` as JSON when the schema expects an array or
    object. The drift case: a complex union / discriminated schema
    causes the model to emit the structure as a JSON-encoded string
    instead of a native value. Returns the original string if parsing
    fails or yields the wrong Python type."""
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value
    if isinstance(parsed, expected_python_type):
        return parsed
    return value


def _coerce_number(value: str, *, integer_only: bool = False) -> Any:
    """Parse ``value`` as a number. Returns the original string on
    parse failure or non-finite results (``inf``/``nan``). When the
    schema demands ``integer``, a fractional value is rejected (kept
    as a string for the caller's validator to surface)."""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return value
    # inf / nan aren't JSON-serialisable and rarely what the model
    # actually meant — preserve the original string instead.
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


__all__ = ["coerce_args"]
