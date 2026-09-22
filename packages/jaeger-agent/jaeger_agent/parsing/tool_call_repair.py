"""Tool call repair and plain-text promotion engine.

Adopted and adapted from OpenClaw's tool-call-repair grammar parser.
Recovers plain-text tool invocations emitted by local or open models (Ollama,
DeepSeek, Qwen, Llama, vLLM, etc.) that emit tool calls in message text rather
than provider-native structured tool fields.

Supports:
1. XML-ish calls:
   <function=name><parameter=key>val</parameter></function>
   <tool_call>{"name": "...", "arguments": {...}}</tool_call>
   <tool name="...">{"key": "val"}</tool>
2. Markdown JSON code blocks:
   ```json {"name": "...", "arguments": {...}} ```
   ```json {"tool": "...", "parameters": {...}} ```
   ```json [{"name": "...", "arguments": {...}}] ```
3. Harmony and Bracket calls:
   [call: tool_name(args)]
   [tool: tool_name(args)]
   <|call|>tool_name{args}
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, NamedTuple


class RepairedToolCall(NamedTuple):
    id: str
    name: str
    arguments: dict[str, Any]
    raw: str


def _repair_json_string(raw: str) -> str:
    """Repair common model JSON syntax bugs (trailing commas, single quotes)."""
    text = raw.strip()
    if not text:
        return "{}"

    # Remove single-line comments // ...
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)

    # Convert single quotes to double quotes when not inside valid strings
    # Simple heuristic: replace 'key': with "key": and ': 'value' with ": "value"
    if "'" in text and '"' not in text:
        text = text.replace("'", '"')
    else:
        # Match single-quoted keys: {'foo': -> {"foo":
        text = re.sub(r"(?<=[{,\s])'([A-Za-z0-9_$-]+)'\s*:", r'"\1":', text)
        # Match single-quoted simple values: : 'bar' -> : "bar"
        text = re.sub(r":\s*'([^']*)'(?=[,\s}\]])", r': "\1"', text)

    # Strip trailing commas before closing braces/brackets
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text


def _safe_parse_json(raw: str) -> Any | None:
    """Attempt standard JSON parse, then repaired JSON parse."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass

    try:
        repaired = _repair_json_string(raw)
        return json.loads(repaired)
    except Exception:
        return None


def _extract_xml_function_tags(text: str) -> list[RepairedToolCall]:
    """Parse <function=name><parameter=k>v</parameter></function> syntax."""
    results: list[RepairedToolCall] = []
    pattern = re.compile(
        r"<function=([A-Za-z0-9_-]+)>(.*?)</function>",
        flags=re.DOTALL | re.IGNORECASE,
    )
    param_pattern = re.compile(
        r"<parameter=([A-Za-z0-9_-]+)>(.*?)</parameter>",
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        name = match.group(1).strip()
        body = match.group(2)
        raw = match.group(0)
        params: dict[str, Any] = {}

        param_matches = list(param_pattern.finditer(body))
        if param_matches:
            for pm in param_matches:
                pname = pm.group(1).strip()
                pval_str = pm.group(2).strip()
                pval = _safe_parse_json(pval_str)
                params[pname] = pval if pval is not None else pval_str
        else:
            # Maybe body is direct JSON
            parsed = _safe_parse_json(body)
            if isinstance(parsed, dict):
                params = parsed

        call_id = f"call_{uuid.uuid4().hex[:24]}"
        results.append(RepairedToolCall(id=call_id, name=name, arguments=params, raw=raw))

    return results


def _extract_tool_call_tags(text: str) -> list[RepairedToolCall]:
    """Parse <tool_call>...</tool_call> or <tool_call> JSON blocks."""
    results: list[RepairedToolCall] = []
    # Both closed and unclosed (if at end) tool_call tags
    pattern = re.compile(
        r"<tool_call>(.*?)(?:</tool_call>|$)",
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        body = match.group(1).strip()
        raw = match.group(0)
        if not body:
            continue

        # If wrapped in markdown code fence inside the tag
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)

        parsed = _safe_parse_json(body)
        if isinstance(parsed, dict):
            name = str(parsed.get("name") or parsed.get("tool") or parsed.get("tool_name") or "").strip()
            args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
            if isinstance(args, str):
                parsed_args = _safe_parse_json(args)
                if isinstance(parsed_args, dict):
                    args = parsed_args
            if name and isinstance(args, dict):
                call_id = str(parsed.get("id") or f"call_{uuid.uuid4().hex[:24]}")
                results.append(RepairedToolCall(id=call_id, name=name, arguments=args, raw=raw))
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("tool") or item.get("tool_name") or "").strip()
                    args = item.get("arguments") or item.get("parameters") or item.get("input") or {}
                    if name and isinstance(args, dict):
                        call_id = str(item.get("id") or f"call_{uuid.uuid4().hex[:24]}")
                        results.append(RepairedToolCall(id=call_id, name=name, arguments=args, raw=raw))

    return results


def _extract_bracket_tool_calls(text: str) -> list[RepairedToolCall]:
    """Parse [call: tool_name(args)] or [tool: tool_name(args)] syntax."""
    results: list[RepairedToolCall] = []
    pattern = re.compile(
        r"\[(?:call|tool):\s*([A-Za-z0-9_-]+)\s*\((.*?)\)\]",
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        name = match.group(1).strip()
        body = match.group(2).strip()
        raw = match.group(0)

        # Body might be JSON or key=val pairs
        params = _safe_parse_json(body)
        if not isinstance(params, dict):
            # Try parsing key=value or key="value"
            params = {}
            for kv in re.finditer(r'([A-Za-z0-9_]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,]+))', body):
                k = kv.group(1)
                v = kv.group(2) if kv.group(2) is not None else (kv.group(3) if kv.group(3) is not None else kv.group(4))
                params[k] = v

        call_id = f"call_{uuid.uuid4().hex[:24]}"
        results.append(RepairedToolCall(id=call_id, name=name, arguments=params, raw=raw))

    return results


def _extract_markdown_json_blocks(text: str, allowed_tool_names: set[str] | None = None) -> list[RepairedToolCall]:
    """Parse ```json ... ``` blocks that represent tool call dictionaries."""
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"```(?:json)?\s*\n?({.*?}|\[.*?\])\s*\n?```", flags=re.DOTALL)

    for match in pattern.finditer(text):
        body = match.group(1).strip()
        raw = match.group(0)

        parsed = _safe_parse_json(body)
        if isinstance(parsed, dict):
            name = str(parsed.get("name") or parsed.get("tool") or parsed.get("tool_name") or "").strip()
            args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input")
            
            # If name not explicitly declared, check if the single top-level key matches an allowed tool
            if not name and allowed_tool_names and len(parsed) == 1:
                key = next(iter(parsed))
                if key in allowed_tool_names and isinstance(parsed[key], dict):
                    name = key
                    args = parsed[key]

            if isinstance(args, str):
                parsed_args = _safe_parse_json(args)
                if isinstance(parsed_args, dict):
                    args = parsed_args
            elif args is None and name:
                # Remaining keys might be the arguments directly
                args = {k: v for k, v in parsed.items() if k not in ("name", "tool", "tool_name", "id", "type")}

            if name and isinstance(args, dict):
                # Verify name against allowed tools if provided
                if allowed_tool_names and name not in allowed_tool_names:
                    continue
                call_id = str(parsed.get("id") or f"call_{uuid.uuid4().hex[:24]}")
                results.append(RepairedToolCall(id=call_id, name=name, arguments=args, raw=raw))
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("tool") or item.get("tool_name") or "").strip()
                    args = item.get("arguments") or item.get("parameters") or item.get("input") or {}
                    if name and isinstance(args, dict):
                        if allowed_tool_names and name not in allowed_tool_names:
                            continue
                        call_id = str(item.get("id") or f"call_{uuid.uuid4().hex[:24]}")
                        results.append(RepairedToolCall(id=call_id, name=name, arguments=args, raw=raw))

    return results


def repair_plain_text_tool_calls(
    text: str,
    *,
    allowed_tool_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Inspect model output text, extract tool calls, and return (tool_calls, cleaned_text).

    Returns:
        tuple of (tool_calls, scrubbed_text):
        - tool_calls: OpenAI/Hermes/Jaeger standard format:
          [{"id": ..., "type": "function", "function": {"name": ..., "arguments": json_str}}]
        - scrubbed_text: text with the parsed tool-call blocks removed.
    """
    if not text or not text.strip():
        return [], text

    extracted: list[RepairedToolCall] = []

    # Priority 1: <tool_call> tags
    extracted.extend(_extract_tool_call_tags(text))

    # Priority 2: <function=name> XML tags
    if not extracted:
        extracted.extend(_extract_xml_function_tags(text))

    # Priority 3: [call: name(...)] brackets
    if not extracted:
        extracted.extend(_extract_bracket_tool_calls(text))

    # Priority 4: Markdown JSON blocks
    if not extracted:
        extracted.extend(_extract_markdown_json_blocks(text, allowed_tool_names))

    if not extracted:
        return [], text

    # Filter by allowed_tool_names if provided
    if allowed_tool_names:
        extracted = [tc for tc in extracted if tc.name in allowed_tool_names]
        if not extracted:
            return [], text

    scrubbed = text
    standard_tool_calls: list[dict[str, Any]] = []

    for tc in extracted:
        # Scrub raw slice from visible text
        scrubbed = scrubbed.replace(tc.raw, "").strip()
        standard_tool_calls.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments),
            },
        })

    return standard_tool_calls, scrubbed
