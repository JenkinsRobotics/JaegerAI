"""Tool Call Repair & Normalization Middleware for Jaeger.

Delegates JSON/fence/Python-literal/truncation repair and JSON-Schema type
coercion directly to standalone ``jaeger-reliability`` (Module 07).
"""

from __future__ import annotations

import json
import re
from typing import Any

from jaeger_reliability import repair_arguments as _v2_repair_args
from jaeger_reliability import repair_json_string as repair_json_string


def extract_xml_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract XML-formatted tool calls like <tool_call name="...">...</tool_call>."""
    pattern = r'<tool_call(?:\s+name=[\'"]([^\'"]+)[\'"])?>([\s\S]*?)</tool_call>'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None

    name = match.group(1) or ""
    body = match.group(2).strip()

    if not name:
        name_match = re.search(r"<name>([a-zA-Z0-9_\-]+)</name>", body, re.IGNORECASE)
        if name_match:
            name = name_match.group(1)

    if not name:
        return None
    args = safe_parse_tool_arguments(body)
    return name, args


def safe_parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Safely parse tool arguments into a dictionary via standalone ``jaeger-reliability``."""
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}

    text = raw.strip()
    if not text:
        return {}

    # Fast path: valid JSON preserves exact strings/whitespace/primitives
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Standalone jaeger-reliability deterministic parser (fences, Python literals, trailing commas, truncation)
    try:
        return _v2_repair_args("tool", text, None)
    except ValueError:
        pass

    # Last-resort key-value bullet extraction for non-JSON plain text
    extracted: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip().lstrip("-* \t")
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().strip("'\"")
            v = v.strip().strip("'\",")
            if k:
                if v.lower() == "true":
                    extracted[k] = True
                elif v.lower() == "false":
                    extracted[k] = False
                elif v.isdigit():
                    extracted[k] = int(v)
                else:
                    extracted[k] = v

    return extracted


def repair_tool_call(
    name: str,
    raw_arguments: Any,
    parameter_aliases: dict[str, str] | None = None,
    schema: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Normalize and repair tool name and arguments via standalone ``jaeger-reliability``."""
    clean_name = re.sub(r"^(?:tools?\.|functions?\.)", "", name.strip())
    arguments = safe_parse_tool_arguments(raw_arguments)

    if parameter_aliases:
        arguments = {parameter_aliases.get(k, k): v for k, v in arguments.items()}

    if schema:
        arguments = _v2_repair_args(clean_name, arguments, schema)

    return clean_name, arguments
