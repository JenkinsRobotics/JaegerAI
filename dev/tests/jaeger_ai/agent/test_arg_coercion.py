"""Tool-argument coercion — local-model drift compatibility."""

from __future__ import annotations

import pytest

from jaeger_os.core.tools.arg_coercion import coerce_args


_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "n": {"type": "integer"},
        "f": {"type": "number"},
        "flag": {"type": "boolean"},
        "name": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "config": {"type": "object"},
        "maybe": {"type": ["string", "null"]},
    },
}


# ── happy / passthrough ────────────────────────────────────────────


def test_returns_input_unchanged_for_empty_args():
    assert coerce_args({}, _OBJECT_SCHEMA) == {}


def test_returns_input_unchanged_when_schema_missing():
    assert coerce_args({"n": "42"}, None) == {"n": "42"}


def test_returns_input_unchanged_when_properties_missing():
    assert coerce_args({"n": "42"}, {"type": "object"}) == {"n": "42"}


def test_already_correct_values_pass_through():
    args = {"n": 3, "flag": True, "name": "hi"}
    assert coerce_args(args, _OBJECT_SCHEMA) == args


def test_does_not_mutate_caller_dict():
    args = {"n": "42"}
    coerced = coerce_args(args, _OBJECT_SCHEMA)
    assert args == {"n": "42"}  # unchanged
    assert coerced == {"n": 42}


# ── scalar coercion ────────────────────────────────────────────────


def test_integer_string_to_int():
    assert coerce_args({"n": "42"}, _OBJECT_SCHEMA) == {"n": 42}


def test_float_string_to_float():
    assert coerce_args({"f": "3.14"}, _OBJECT_SCHEMA) == {"f": 3.14}


def test_integer_only_rejects_decimals():
    """A schema asking for integer + value ``"3.14"`` must NOT silently
    truncate. Surface the original string so validation can fail
    loudly."""
    assert coerce_args({"n": "3.14"}, _OBJECT_SCHEMA) == {"n": "3.14"}


def test_boolean_strings():
    assert coerce_args({"flag": "true"}, _OBJECT_SCHEMA) == {"flag": True}
    assert coerce_args({"flag": "false"}, _OBJECT_SCHEMA) == {"flag": False}
    assert coerce_args({"flag": "TRUE"}, _OBJECT_SCHEMA) == {"flag": True}


def test_boolean_garbage_keeps_string():
    assert coerce_args({"flag": "maybe"}, _OBJECT_SCHEMA) == {"flag": "maybe"}


def test_unparseable_number_keeps_string():
    assert coerce_args({"n": "not-a-number"}, _OBJECT_SCHEMA) == {"n": "not-a-number"}


def test_inf_and_nan_keep_string():
    """Infinity / NaN aren't JSON-serialisable and rarely intended —
    keep the original."""
    assert coerce_args({"f": "inf"}, _OBJECT_SCHEMA) == {"f": "inf"}
    assert coerce_args({"f": "nan"}, _OBJECT_SCHEMA) == {"f": "nan"}


# ── array wrapping (the key Hermes-lift win) ───────────────────────


def test_bare_string_wrapped_for_array_field():
    assert coerce_args({"tags": "a"}, _OBJECT_SCHEMA) == {"tags": ["a"]}


def test_bare_int_wrapped_for_array_field():
    assert coerce_args({"tags": 5}, _OBJECT_SCHEMA) == {"tags": [5]}


def test_json_encoded_array_string_parsed():
    args = {"tags": '["a", "b", "c"]'}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"tags": ["a", "b", "c"]}


def test_malformed_json_array_string_falls_back_to_wrap():
    args = {"tags": '["a", missing-quote'}
    # Can't parse → wrap as single element (logged as a warning).
    assert coerce_args(args, _OBJECT_SCHEMA) == {"tags": ['["a", missing-quote']}


def test_already_array_passes_through_array_field():
    args = {"tags": ["a", "b"]}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"tags": ["a", "b"]}


def test_none_preserved_for_array_field():
    """``None`` could mean "omit" — don't silently wrap into ``[None]``."""
    args = {"tags": None}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"tags": None}


# ── object coercion ────────────────────────────────────────────────


def test_json_encoded_object_string_parsed():
    args = {"config": '{"key": "val"}'}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"config": {"key": "val"}}


def test_malformed_object_json_keeps_string():
    args = {"config": "{bad: json"}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"config": "{bad: json"}


# ── nullable handling ──────────────────────────────────────────────


def test_literal_null_string_becomes_none_for_nullable_field():
    args = {"maybe": "null"}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"maybe": None}


def test_anyof_null_branch_recognised_as_nullable():
    schema = {
        "type": "object",
        "properties": {
            "x": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    assert coerce_args({"x": "null"}, schema) == {"x": None}


def test_literal_null_not_coerced_for_non_nullable_field():
    """Schema doesn't allow null → preserve the string so validation
    can surface it."""
    assert coerce_args({"name": "null"}, _OBJECT_SCHEMA) == {"name": "null"}


# ── unknown properties + edge cases ────────────────────────────────


def test_unknown_property_passes_through():
    """The schema only covers ``n``, ``flag``, etc. — extra keys must
    not be dropped or coerced."""
    args = {"extra": "anything"}
    assert coerce_args(args, _OBJECT_SCHEMA) == {"extra": "anything"}


def test_non_dict_args_passes_through():
    assert coerce_args("not a dict", _OBJECT_SCHEMA) == "not a dict"
    assert coerce_args(None, _OBJECT_SCHEMA) is None


def test_non_dict_schema_passes_through():
    assert coerce_args({"n": "42"}, "not-a-schema") == {"n": "42"}


# ── end-to-end via ToolDef.dispatch ────────────────────────────────


def test_dispatch_now_coerces_arrays_before_pydantic_validation():
    """Smoke through a real ``ToolDef`` — confirms the wiring landed
    in ``dispatch``. Without coercion, Pydantic would reject the bare
    string ``"a"`` against a ``list[str]`` field."""
    from pydantic import BaseModel
    from jaeger_ai.agent import ToolDef

    class Args(BaseModel):
        tags: list[str]

    captured: dict[str, list[str]] = {}

    def _impl(tags: list[str]) -> dict:
        captured["seen"] = tags
        return {"ok": True}

    tool = ToolDef(name="x", description="x", args_model=Args, fn=_impl)
    result = tool.dispatch({"tags": "single"})
    assert result == {"ok": True}
    assert captured["seen"] == ["single"]
