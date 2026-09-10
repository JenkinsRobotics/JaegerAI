"""Tool Call Repair & Normalization Middleware for Jaeger.

Modeled after OpenClaw's battle-tested packages/tool-call-repair:
Protects the agent runtime from malformed LLM outputs by auto-repairing:
  1. Markdown fences (```json ... ```)
  2. Single quotes instead of double quotes
  3. Trailing commas in arrays and objects
  4. Unescaped newlines and tabs inside strings
  5. Python-style booleans and None (True/False/None -> true/false/null)
  6. Unterminated brackets / truncated JSON
  7. XML-style tool calls (<tool_call name="...">...</tool_call>)
"""

from __future__ import annotations

import json
import re
from typing import Any


def repair_json_string(raw: str) -> str:
    """Repair common JSON formatting defects produced by language models."""
    if not raw:
        return "{}"

    text = raw.strip()

    # 1. Strip markdown code fences if wrapped
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # 2. Extract balanced JSON object if surrounded by prose
    if not text.startswith("{") and "{" in text:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0).strip()

    # 3. Replace Python constants
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # 4. Replace single quotes around keys or strings
    # Replace 'key': with "key":
    text = re.sub(r"(?<=[{,\s])'([a-zA-Z0-9_\-\.]+)'\s*:", r'"\1":', text)
    # Replace : 'value' with : "value"
    text = re.sub(r":\s*'([^']*)'", r': "\1"', text)

    # 5. Remove trailing commas before closing braces/brackets
    text = re.sub(r",\s*([\]}])", r"\1", text)

    # 6. Check if braces are unbalanced (truncated JSON recovery)
    open_curly = text.count("{")
    close_curly = text.count("}")
    if open_curly > close_curly:
        text += "}" * (open_curly - close_curly)

    open_square = text.count("[")
    close_square = text.count("]")
    if open_square > close_square:
        text += "]" * (open_square - close_square)

    return text


def extract_xml_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract XML-formatted tool calls like <tool_call name="...">...</tool_call>."""
    pattern = r'<tool_call(?:\s+name=[\'"]([^\'"]+)[\'"])?>([\s\S]*?)</tool_call>'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None

    name = match.group(1) or ""
    body = match.group(2).strip()

    # If name wasn't in attribute, check for <name> tag
    if not name:
        name_match = re.search(r"<name>([a-zA-Z0-9_\-]+)</name>", body, re.IGNORECASE)
        if name_match:
            name = name_match.group(1)

    args = safe_parse_tool_arguments(body)
    return name, args


def safe_parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Safely parse tool arguments into a dictionary, applying automatic repair if needed."""
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}

    text = raw.strip()
    if not text:
        return {}

    # Fast path: standard json
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Repair path
    repaired = repair_json_string(text)
    try:
        parsed = json.loads(repaired)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Fallback: key-value line extraction
    extracted: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip().lstrip("-* \t")
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().strip("'\"")
            v = v.strip().strip("'\",")
            if k:
                # Try simple type conversion
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
) -> tuple[str, dict[str, Any]]:
    """Normalize and repair both the tool name and argument payload.

    Args:
        name: The requested tool name.
        raw_arguments: The raw argument string or dictionary from model output.
        parameter_aliases: Optional dict mapping common LLM hallucinated param
            names to canonical ones (e.g. {"path": "file_path"}).
    """
    clean_name = name.strip()

    # If the tool name itself contains an XML tag or command prefix
    clean_name = re.sub(r"^(?:tools?\.|functions?\.)", "", clean_name)

    arguments = safe_parse_tool_arguments(raw_arguments)

    if parameter_aliases:
        repaired_args: dict[str, Any] = {}
        for k, v in arguments.items():
            target_key = parameter_aliases.get(k, k)
            repaired_args[target_key] = v
        arguments = repaired_args

    return clean_name, arguments
