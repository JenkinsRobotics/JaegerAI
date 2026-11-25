"""Bi-directional tool JSON-schema sanitization for broad LLM-backend compatibility.

Synthesizes Hermes ``tools/schema_sanitizer.py`` + Jaeger's GBNF/Anthropic/Codex
compatibility rules:
- Deep-copies tool definitions so registries stay immutable.
- Collapses nullable ``anyOf``/``oneOf`` and ``type: [X, "null"]`` unions.
- Strips top-level combinators (``allOf``/``anyOf``/``oneOf``/``enum``/``not``).
- Injects ``properties: {}`` on unconstrained objects and prunes dangling ``required``.
- Supports deterministic property-key sanitization + ``unrename_tool_args`` back-mapping.
- Reactive ``strip_pattern_and_format`` recovery for strict llama.cpp GBNF servers.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Mapping

logger = logging.getLogger("jaeger_reliability.schema_sanitizer")

_TOP_LEVEL_FORBIDDEN_KEYS = ("allOf", "anyOf", "oneOf", "enum", "not")
_STRIP_ON_RECOVERY_KEYS = frozenset({"pattern", "format"})
_VALID_PROP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


def sanitize_property_key(key: str) -> str:
    """Deterministically map non-identifier schema property keys for strict providers."""
    if _VALID_PROP_KEY_RE.match(key):
        return key
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    if not cleaned or not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"k_{cleaned}"
    return cleaned[:64]


def unrename_tool_args(
    args: Mapping[str, Any],
    key_map: Mapping[str, str],
) -> dict[str, Any]:
    """Restore original schema property names from sanitized keys at dispatch time."""
    if not key_map:
        return dict(args)
    return {key_map.get(k, k): v for k, v in args.items()}


def sanitize_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deep copy of OpenAI-format ``tools`` with sanitized parameter schemas."""
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

    fn["parameters"] = strip_nullable_unions(fn["parameters"], keep_nullable_hint=True)
    fn["parameters"] = _strip_top_level_combinators(
        fn["parameters"], path=fn.get("name", "<tool>"),
    )
    return out


def _strip_top_level_combinators(
    params: dict[str, Any], *, path: str = "<tool>",
) -> dict[str, Any]:
    if not isinstance(params, dict):
        return params
    out = dict(params)
    for key in _TOP_LEVEL_FORBIDDEN_KEYS:
        if key in out:
            logger.debug("schema_sanitizer[%s]: stripped top-level %r combinator", path, key)
            out.pop(key, None)
    return out


def strip_nullable_unions(
    schema: Any, *, keep_nullable_hint: bool = True,
) -> Any:
    """Collapse ``anyOf``/``oneOf`` nullable unions to the non-null branch."""
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
    if isinstance(node, str):
        if node in {"object", "string", "number", "integer", "boolean", "array", "null"}:
            return {"type": node} if node != "object" else {"type": "object", "properties": {}}
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
            first_str = next((t for t in value if isinstance(t, str) and t != "null"), None)
            out["type"] = first_str or "object"
            continue

        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            out[key] = {
                sub_k: _sanitize_node(sub_v, f"{path}.{key}.{sub_k}")
                for sub_k, sub_v in value.items()
            }
        elif key in {"items", "additionalProperties"}:
            out[key] = value if isinstance(value, bool) else _sanitize_node(value, f"{path}.{key}")
        elif key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list):
            out[key] = [_sanitize_node(item, f"{path}.{key}[{i}]") for i, item in enumerate(value)]
        elif key in {"required", "enum", "examples"}:
            out[key] = copy.deepcopy(value) if isinstance(value, (list, dict)) else value
        else:
            out[key] = (
                _sanitize_node(value, f"{path}.{key}")
                if isinstance(value, (dict, list))
                else value
            )

    if out.get("type") == "object" and not isinstance(out.get("properties"), dict):
        out["properties"] = {}

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
    """Reactive sanitizer stripping ``pattern`` / ``format`` after GBNF grammar 400s."""
    if not tools:
        return tools, 0

    stripped = 0

    def _walk(node: Any) -> None:
        nonlocal stripped
        if isinstance(node, dict):
            is_schema_node = any(k in node for k in ("type", "anyOf", "oneOf", "allOf"))
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
        if isinstance(fn, dict) and isinstance(fn.get("parameters"), dict):
            _walk(fn["parameters"])

    if stripped:
        logger.info("schema_sanitizer: stripped %d pattern/format keyword(s)", stripped)
    return tools, stripped


__all__ = [
    "sanitize_property_key",
    "sanitize_tool_schemas",
    "strip_nullable_unions",
    "strip_pattern_and_format",
    "unrename_tool_args",
]
