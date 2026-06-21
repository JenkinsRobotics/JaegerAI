"""Schema sanitiser — keep tool schemas compatible with strict
backends (llama.cpp grammar generator, Anthropic input_schema,
OpenAI Codex top-level rejection of combinators)."""

from __future__ import annotations

import pytest

from jaeger_os.agent.parsing.schema_sanitizer import (
    sanitize_tool_schemas,
    strip_nullable_unions,
    strip_pattern_and_format,
)


# ── sanitize_tool_schemas ──────────────────────────────────────────


def test_handles_empty_input():
    assert sanitize_tool_schemas([]) == []
    assert sanitize_tool_schemas(None) is None  # type: ignore[arg-type]


def test_returns_deep_copy_does_not_mutate_input():
    original = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {"type": "object", "properties": {"a": {"type": "string"}}},
        },
    }]
    sanitized = sanitize_tool_schemas(original)
    sanitized[0]["function"]["parameters"]["properties"]["a"]["type"] = "MUTATED"
    assert original[0]["function"]["parameters"]["properties"]["a"]["type"] == "string"


def test_missing_parameters_gets_minimal_object_schema():
    tools = [{"type": "function", "function": {"name": "x"}}]
    out = sanitize_tool_schemas(tools)
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_object_without_properties_gains_empty_properties():
    """llama.cpp can't constrain ``{"type": "object"}`` without a
    properties dict — the sanitiser injects one."""
    tools = [{
        "type": "function",
        "function": {"name": "x", "parameters": {"type": "object"}},
    }]
    out = sanitize_tool_schemas(tools)
    assert out[0]["function"]["parameters"]["properties"] == {}


def test_type_array_with_null_collapses_to_single_type():
    """``"type": ["string", "null"]`` is rejected by many grammar
    engines — collapse to ``"type": "string"`` plus a ``nullable``
    hint."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": ["string", "null"]}},
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    prop = out[0]["function"]["parameters"]["properties"]["a"]
    assert prop["type"] == "string"
    assert prop["nullable"] is True


def test_anyof_nullable_union_collapses_to_non_null_branch():
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "title": "A",
                    },
                },
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    prop = out[0]["function"]["parameters"]["properties"]["a"]
    assert prop["type"] == "string"
    assert prop["nullable"] is True
    # Metadata carries through.
    assert prop["title"] == "A"


def test_top_level_combinators_stripped():
    """OpenAI Codex rejects top-level ``allOf``/``anyOf``/``oneOf``/
    ``enum``/``not`` on tool parameters."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "allOf": [{"required": ["a"]}],
                "anyOf": [{"required": ["a"]}],
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    params = out[0]["function"]["parameters"]
    assert "allOf" not in params
    assert "anyOf" not in params


def test_nested_combinators_preserved():
    """The strict rule only applies to the *top level* parameters
    object — combinators nested inside a property are preserved."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "object",
                        "properties": {
                            "inner": {
                                "anyOf": [{"type": "string"}, {"type": "integer"}],
                            },
                        },
                    },
                },
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    inner = out[0]["function"]["parameters"]["properties"]["a"]["properties"]["inner"]
    # anyOf survives at the inner level.
    assert "anyOf" in inner


def test_bare_string_schema_replaced_with_dict():
    """Malformed MCP output sometimes embeds ``"object"`` as the
    schema value instead of a dict. Sanitise to a real schema dict."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": "string"},  # malformed
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    assert out[0]["function"]["parameters"]["properties"]["a"] == {"type": "string"}


def test_required_pruned_to_existing_properties():
    """``required: ["x"]`` when ``x`` isn't in ``properties`` is a
    malformed schema — drop the dangling entry."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a", "ghost", "phantom"],
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    assert out[0]["function"]["parameters"]["required"] == ["a"]


def test_required_dropped_entirely_when_all_invalid():
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["ghost"],
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    assert "required" not in out[0]["function"]["parameters"]


def test_required_does_not_misinterpret_strings_as_schemas():
    """Regression: ``required`` carries property-name strings, not
    schemas. The recursive walk used to rewrite ``"a"`` to
    ``{"type": "object"}`` and corrupt the required list."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    assert out[0]["function"]["parameters"]["required"] == ["path"]


def test_enum_values_preserved_as_literals():
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["object", "array", "string"]},
                },
            },
        },
    }]
    out = sanitize_tool_schemas(tools)
    prop = out[0]["function"]["parameters"]["properties"]["kind"]
    # ``"object"`` is one of the literal enum values — must not be
    # rewritten to ``{"type": "object"}``.
    assert prop["enum"] == ["object", "array", "string"]


def test_idempotent():
    """Applying sanitisation twice yields the same result — important
    for layers that defensively re-sanitise."""
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
        },
    }]
    once = sanitize_tool_schemas(tools)
    twice = sanitize_tool_schemas(once)
    assert once == twice


# ── strip_nullable_unions ──────────────────────────────────────────


def test_strip_nullable_unions_handles_oneOf_form():
    schema = {
        "oneOf": [{"type": "integer"}, {"type": "null"}],
        "default": 0,
    }
    out = strip_nullable_unions(schema)
    assert out["type"] == "integer"
    assert out["nullable"] is True
    assert out["default"] == 0


def test_strip_nullable_unions_leaves_multi_branch_unions_alone():
    """When more than one non-null branch exists, the union is
    meaningful — don't collapse it."""
    schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    out = strip_nullable_unions(schema)
    assert "anyOf" in out


def test_strip_nullable_unions_keep_nullable_hint_flag():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    with_hint = strip_nullable_unions(schema, keep_nullable_hint=True)
    without_hint = strip_nullable_unions(schema, keep_nullable_hint=False)
    assert with_hint.get("nullable") is True
    assert "nullable" not in without_hint


# ── strip_pattern_and_format (reactive recovery) ───────────────────


def test_strip_pattern_and_format_removes_keywords_and_counts():
    tools = [{
        "type": "function",
        "function": {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "pattern": r"\d+", "format": "uuid"},
                    "b": {"type": "string"},
                },
            },
        },
    }]
    out, stripped = strip_pattern_and_format(tools)
    assert stripped == 2
    prop_a = out[0]["function"]["parameters"]["properties"]["a"]
    assert "pattern" not in prop_a
    assert "format" not in prop_a
    # ``b`` had neither, so it's untouched.
    assert out[0]["function"]["parameters"]["properties"]["b"] == {"type": "string"}


def test_strip_pattern_and_format_skips_property_named_pattern():
    """A *property* literally named ``pattern`` lives inside
    ``properties`` — not as a sibling of ``type`` — so it must NOT be
    stripped."""
    tools = [{
        "type": "function",
        "function": {
            "name": "search_files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},   # arg literally named "pattern"
                    "path": {"type": "string"},
                },
            },
        },
    }]
    out, stripped = strip_pattern_and_format(tools)
    assert stripped == 0
    assert "pattern" in out[0]["function"]["parameters"]["properties"]


def test_strip_pattern_and_format_handles_empty():
    out, stripped = strip_pattern_and_format([])
    assert out == []
    assert stripped == 0
