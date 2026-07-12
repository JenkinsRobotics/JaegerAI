"""Sanitize tool JSON schemas for broad LLM-backend compatibility.

Some local inference backends (notably llama.cpp's
``json-schema-to-grammar`` converter that builds GBNF tool-call
parsers) are strict about what JSON Schema shapes they accept. Schemas
that OpenAI / Anthropic silently accept can make llama.cpp fail the
whole request with::

    HTTP 400: Unable to generate parser for this template.
    Automatic parser generation failed: JSON schema conversion failed.

The failure modes we've actually observed:

* ``{"type": "object"}`` with no ``properties`` — rejected as
  unconstrainable.
* A schema value that's a bare string ``"object"`` instead of a dict
  (malformed MCP server output).
* ``"type": ["string", "null"]`` array-form types — many converters
  only accept single-string ``type``.
* ``anyOf`` / ``oneOf`` unions that exist only to allow ``null``
  (common Pydantic shape). Anthropic rejects these on
  ``input_schema``; collapse to the non-null branch.
* Top-level ``allOf`` / ``anyOf`` / ``oneOf`` / ``enum`` / ``not`` —
  rejected by OpenAI's Codex backend.

This module walks a tool schema tree (after MCP normalisation + any
per-tool dynamic rebuild) and fixes the known-hostile constructs on a
deep copy. Intentionally conservative — only modifies shapes the
backend couldn't use anyway. Ported from Hermes' upstream
``tools/schema_sanitizer.py`` so JROS' behaviour matches what we know
works in production.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


_TOP_LEVEL_FORBIDDEN_KEYS = ("allOf", "anyOf", "oneOf", "enum", "not")
_STRIP_ON_RECOVERY_KEYS = frozenset({"pattern", "format"})


def sanitize_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deep copy of ``tools`` with each tool's ``parameters``
    schema sanitised.

    Input is an OpenAI-format tool list:
    ``[{"type": "function", "function": {"name": ..., "parameters": {...}}}]``.
    The returned list is a deep copy — callers can mutate freely
    without touching the original registry entries.
    """
    if not tools:
        return tools
    return [_sanitize_single_tool(t) for t in tools]


def _sanitize_single_tool(tool: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(tool)
    fn = out.get("function") if isinstance(out, dict) else None
    if not isinstance(fn, dict):
        return out

    params = fn.get("parameters")
    if not isinstance(params, dict):
        fn["parameters"] = {"type": "object", "properties": {}}
        return out

    fn["parameters"] = _sanitize_node(params, path=fn.get("name", "<tool>"))
    top = fn["parameters"]
    if not isinstance(top, dict):
        fn["parameters"] = {"type": "object", "properties": {}}
    else:
        if top.get("type") != "object":
            top["type"] = "object"
        if "properties" not in top or not isinstance(top.get("properties"), dict):
            top["properties"] = {}

    # Collapse nullable anyOf/oneOf unions the recursive sanitiser
    # leaves intact. Keeps a ``nullable: true`` hint so
    # ``arg_coercion._schema_allows_null`` still maps ``"null"`` →
    # ``None`` at dispatch time.
    fn["parameters"] = strip_nullable_unions(fn["parameters"], keep_nullable_hint=True)
    fn["parameters"] = _strip_top_level_combinators(
        fn["parameters"], path=fn.get("name", "<tool>"),
    )
    return out


def _strip_top_level_combinators(
    params: dict[str, Any], *, path: str = "<tool>",
) -> dict[str, Any]:
    """Drop combinator keywords from the *top level* of a tool
    parameters schema. OpenAI's Codex backend rejects any of
    ``allOf`` / ``anyOf`` / ``oneOf`` / ``enum`` / ``not`` here.
    Nested occurrences inside ``properties`` are preserved — strict
    rule only applies to the outermost object."""
    if not isinstance(params, dict):
        return params
    out = dict(params)
    for key in _TOP_LEVEL_FORBIDDEN_KEYS:
        if key in out:
            logger.debug(
                "schema_sanitizer[%s]: stripped top-level %r combinator",
                path, key,
            )
            out.pop(key, None)
    return out


def strip_nullable_unions(
    schema: Any, *, keep_nullable_hint: bool = True,
) -> Any:
    """Collapse ``anyOf``/``oneOf`` nullable unions to the non-null
    branch. MCP / Pydantic optional fields commonly arrive as::

        {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}

    Anthropic's validator rejects the null branch; tool optionality is
    already represented by the parent's ``required`` array, so we
    collapse the union to the non-null variant. Metadata
    (``title`` / ``description`` / ``default`` / ``examples``) on the
    outer node is carried over.
    """
    if isinstance(schema, list):
        return [
            strip_nullable_unions(item, keep_nullable_hint=keep_nullable_hint)
            for item in schema
        ]
    if not isinstance(schema, dict):
        return schema

    stripped = {
        k: strip_nullable_unions(v, keep_nullable_hint=keep_nullable_hint)
        for k, v in schema.items()
    }
    for key in ("anyOf", "oneOf"):
        variants = stripped.get(key)
        if not isinstance(variants, list):
            continue
        non_null = [
            item for item in variants
            if not (isinstance(item, dict) and item.get("type") == "null")
        ]
        if len(non_null) == 1 and len(non_null) != len(variants):
            replacement = dict(non_null[0]) if isinstance(non_null[0], dict) else {}
            if keep_nullable_hint:
                replacement.setdefault("nullable", True)
            for meta_key in ("title", "description", "default", "examples"):
                if meta_key in stripped and meta_key not in replacement:
                    replacement[meta_key] = stripped[meta_key]
            return strip_nullable_unions(
                replacement, keep_nullable_hint=keep_nullable_hint,
            )
    return stripped


def _sanitize_node(node: Any, path: str) -> Any:
    """Recursively sanitise a JSON-Schema fragment.

    - Replace bare-string schema values (``"object"`` / ``"string"`` …)
      with proper ``{"type": <value>}`` dicts.
    - Inject ``properties: {}`` into object-typed nodes missing it.
    - Normalise ``type: [X, "null"]`` to single ``type: X``, keeping
      ``nullable: true`` as a hint.
    - Recurse into ``properties``, ``items``, ``additionalProperties``,
      ``anyOf``, ``oneOf``, ``allOf``, and ``$defs`` / ``definitions``.
    - Leave ``required`` / ``enum`` / ``examples`` lists untouched —
      they hold literal values, not nested schemas.
    """
    if isinstance(node, str):
        if node in {"object", "string", "number", "integer", "boolean", "array", "null"}:
            return {"type": node} if node != "object" else {
                "type": "object", "properties": {},
            }
        return {"type": "object", "properties": {}}

    if isinstance(node, list):
        return [_sanitize_node(item, f"{path}[{i}]") for i, item in enumerate(node)]

    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            if len(non_null) == 1 and isinstance(non_null[0], str):
                out["type"] = non_null[0]
                if "null" in value:
                    out.setdefault("nullable", True)
                continue
            first_str = next(
                (t for t in value if isinstance(t, str) and t != "null"), None,
            )
            if first_str:
                out["type"] = first_str
                continue
            out["type"] = "object"
            continue

        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            out[key] = {
                sub_k: _sanitize_node(sub_v, f"{path}.{key}.{sub_k}")
                for sub_k, sub_v in value.items()
            }
        elif key in {"items", "additionalProperties"}:
            if isinstance(value, bool):
                out[key] = value
            else:
                out[key] = _sanitize_node(value, f"{path}.{key}")
        elif key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list):
            out[key] = [
                _sanitize_node(item, f"{path}.{key}[{i}]")
                for i, item in enumerate(value)
            ]
        elif key in {"required", "enum", "examples"}:
            # Sibling keywords whose values are NOT schemas. Recursing
            # would mis-interpret literal strings (e.g. "path" in a
            # ``required`` list) as bare-string schemas and rewrite
            # them to ``{"type": "object"}``.
            out[key] = copy.deepcopy(value) if isinstance(value, (list, dict)) else value
        else:
            out[key] = (
                _sanitize_node(value, f"{path}.{key}")
                if isinstance(value, (dict, list))
                else value
            )

    # Object nodes without properties: inject empty properties dict so
    # llama.cpp's grammar generator has something to constrain.
    if out.get("type") == "object" and not isinstance(out.get("properties"), dict):
        out["properties"] = {}

    # Prune ``required`` entries that don't exist in properties.
    if out.get("type") == "object" and isinstance(out.get("required"), list):
        props = out.get("properties") or {}
        valid = [r for r in out["required"] if isinstance(r, str) and r in props]
        if not valid:
            out.pop("required", None)
        elif len(valid) != len(out["required"]):
            out["required"] = valid

    return out


def strip_pattern_and_format(
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Reactive sanitiser — only invoked when llama.cpp's
    ``json-schema-to-grammar`` rejects a schema with an HTTP 400
    grammar-parse error.

    llama.cpp's regex engine supports only a small subset of ECMAScript
    regex; ``\\d`` / ``\\w`` / ``\\s`` and most ``format`` values get
    rejected. Cloud providers accept these keywords as prompting hints,
    so we keep them in the default schema and only strip on demand.

    Returns ``(tools, stripped_count)``. The input list is mutated in
    place for efficiency — deep-copy upstream if the original matters.
    """
    if not tools:
        return tools, 0

    stripped = 0

    def _walk(node: Any) -> None:
        nonlocal stripped
        if isinstance(node, dict):
            # Only strip as a sibling of ``type`` — avoids touching
            # literal property names like ``search_files.pattern``.
            is_schema_node = (
                "type" in node or "anyOf" in node
                or "oneOf" in node or "allOf" in node
            )
            for key in list(node.keys()):
                if is_schema_node and key in _STRIP_ON_RECOVERY_KEYS:
                    node.pop(key, None)
                    stripped += 1
                    continue
                _walk(node[key])
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(fn, dict):
            params = fn.get("parameters")
            if isinstance(params, dict):
                _walk(params)

    if stripped:
        logger.info(
            "schema_sanitizer: stripped %d pattern/format keyword(s) "
            "(llama.cpp grammar-parse recovery)", stripped,
        )
    return tools, stripped


__all__ = [
    "sanitize_tool_schemas",
    "strip_nullable_unions",
    "strip_pattern_and_format",
]
