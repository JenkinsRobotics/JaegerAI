"""Unified tool-call repair, plain-text promotion, and argument normalization.

Consolidates both JaegerAI's former ``core/runtime/tool_repair.py`` and
``jaeger_agent/parsing/tool_call_repair.py`` into one authoritative engine.
"""

from __future__ import annotations

import json
import re
import uuid
from html import unescape
from typing import Any, NamedTuple

from .engine import repair_arguments, repair_json_string


class RepairedToolCall(NamedTuple):
    id: str
    name: str
    arguments: dict[str, Any]
    raw: str


def _safe_parse_json(raw: str) -> Any | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        return json.loads(repair_json_string(raw))
    except Exception:
        return None


def safe_parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Safely parse tool arguments into a dictionary via deterministic repair."""
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    try:
        return repair_arguments("tool", text, None)
    except ValueError:
        pass

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


def extract_xml_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract XML-formatted tool calls like ``<tool_call name="...">...</tool_call>``."""
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
    return name, safe_parse_tool_arguments(body)


def repair_tool_call(
    name: str,
    raw_arguments: Any,
    parameter_aliases: dict[str, str] | None = None,
    schema: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Normalize tool name and deterministically repair & coerce arguments."""
    clean_name = re.sub(r"^(?:tools?\.|functions?\.)", "", name.strip())
    arguments = safe_parse_tool_arguments(raw_arguments)
    if parameter_aliases:
        arguments = {parameter_aliases.get(k, k): v for k, v in arguments.items()}
    if schema:
        arguments = repair_arguments(clean_name, arguments, schema)
    return clean_name, arguments


def _extract_xml_function_tags(text: str) -> list[RepairedToolCall]:
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"<function=([A-Za-z0-9_-]+)>(.*?)</function>", flags=re.DOTALL | re.IGNORECASE)
    param_pattern = re.compile(r"<parameter=([A-Za-z0-9_-]+)>(.*?)</parameter>", flags=re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(text):
        name = match.group(1).strip()
        body = match.group(2)
        params: dict[str, Any] = {}
        param_matches = list(param_pattern.finditer(body))
        if param_matches:
            for pm in param_matches:
                pname = pm.group(1).strip()
                pval_str = pm.group(2).strip()
                pval = _safe_parse_json(pval_str)
                params[pname] = pval if pval is not None else pval_str
        else:
            parsed = _safe_parse_json(body)
            if isinstance(parsed, dict):
                params = parsed
        results.append(RepairedToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=name, arguments=params, raw=match.group(0)))
    return results


def _extract_direct_tool_tags(
    text: str,
    allowed_tool_names: set[str] | None,
) -> list[RepairedToolCall]:
    if not allowed_tool_names:
        return []
    results: list[RepairedToolCall] = []
    tag_pattern = re.compile(r"<([A-Za-z_][A-Za-z0-9_-]*)\s+([^<>]*?)(?:\s*/?)>", flags=re.DOTALL)
    attr_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", flags=re.DOTALL)
    for match in tag_pattern.finditer(text):
        name = match.group(1)
        if name not in allowed_tool_names:
            continue
        body = match.group(2)
        attrs = list(attr_pattern.finditer(body))
        if not attrs or attr_pattern.sub("", body).strip():
            continue
        arguments = {
            attr.group(1): unescape(attr.group(2) if attr.group(2) is not None else attr.group(3))
            for attr in attrs
        }
        results.append(RepairedToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=name, arguments=arguments, raw=match.group(0)))
    return results


def _extract_tool_call_tags(text: str) -> list[RepairedToolCall]:
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"<(?:ai:)?tool_call>(.*?)(?:</(?:ai:)?tool_call>|$)", flags=re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(text):
        body = match.group(1).strip()
        raw = match.group(0)
        if not body:
            continue
        fn_match = re.search(r"<(?:ai:)?function_name>(.*?)</(?:ai:)?function_name>", body, flags=re.DOTALL | re.IGNORECASE)
        param_match = re.search(r"<(?:ai:)?parameters>(.*?)</(?:ai:)?parameters>", body, flags=re.DOTALL | re.IGNORECASE)
        if fn_match:
            name = fn_match.group(1).strip()
            param_str = param_match.group(1).strip() if param_match else "{}"
            args = _safe_parse_json(param_str) or {}
            if isinstance(args, str):
                args = _safe_parse_json(args) or {}
            if name and isinstance(args, dict):
                results.append(RepairedToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=name, arguments=args, raw=raw))
                continue
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
        parsed = _safe_parse_json(body)
        if isinstance(parsed, dict):
            name = str(parsed.get("name") or parsed.get("tool") or parsed.get("tool_name") or "").strip()
            args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
            if not name and "command" in parsed:
                name = "terminal"
                args = {"command": parsed["command"]}
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
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"\[(?:call|tool):\s*([A-Za-z0-9_-]+)\s*\((.*?)\)\]", flags=re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(text):
        name = match.group(1).strip()
        body = match.group(2).strip()
        params = _safe_parse_json(body)
        if not isinstance(params, dict):
            params = {}
            for kv in re.finditer(r'([A-Za-z0-9_]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,]+))', body):
                k = kv.group(1)
                v = kv.group(2) if kv.group(2) is not None else (kv.group(3) if kv.group(3) is not None else kv.group(4))
                params[k] = v
        results.append(RepairedToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=name, arguments=params, raw=match.group(0)))
    return results


def _extract_markdown_json_blocks(text: str, allowed_tool_names: set[str] | None = None) -> list[RepairedToolCall]:
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"```(?:json)?\s*\n?({.*?}|\[.*?\])\s*\n?```", flags=re.DOTALL)
    for match in pattern.finditer(text):
        body = match.group(1).strip()
        raw = match.group(0)
        parsed = _safe_parse_json(body)
        if isinstance(parsed, dict):
            name = str(parsed.get("name") or parsed.get("tool") or parsed.get("tool_name") or "").strip()
            args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input")
            if not name and allowed_tool_names and len(parsed) == 1:
                key = next(iter(parsed))
                if key in allowed_tool_names and isinstance(parsed[key], dict):
                    name = key
                    args = parsed[key]
            if not name and "command" in parsed:
                if not allowed_tool_names or "run_shell" in allowed_tool_names:
                    name = "run_shell"
                    args = {"command": parsed["command"]}
                elif "bash" in allowed_tool_names:
                    name = "bash"
                    args = {"command": parsed["command"]}
            if isinstance(args, str):
                parsed_args = _safe_parse_json(args)
                if isinstance(parsed_args, dict):
                    args = parsed_args
            elif args is None and name:
                args = {k: v for k, v in parsed.items() if k not in ("name", "tool", "tool_name", "id", "type")}
            if name and isinstance(args, dict):
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


def _extract_markdown_bash_blocks(text: str, allowed_tool_names: set[str] | None = None) -> list[RepairedToolCall]:
    if allowed_tool_names and not ({"terminal", "run_shell", "bash"} & allowed_tool_names):
        return []
    target_name = "terminal" if (not allowed_tool_names or "terminal" in allowed_tool_names) else "run_shell"
    results: list[RepairedToolCall] = []
    pattern = re.compile(r"```(?:bash|sh)\s*\n(.*?)```", flags=re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(text):
        cmd = match.group(1).strip()
        if cmd:
            results.append(RepairedToolCall(id=f"call_{uuid.uuid4().hex[:24]}", name=target_name, arguments={"command": cmd}, raw=match.group(0)))
    return results


def repair_plain_text_tool_calls(
    text: str,
    *,
    allowed_tool_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Inspect model output text, promote plain-text tool calls, and scrub visible text."""
    if not text or not text.strip():
        return [], text
    extracted: list[RepairedToolCall] = []
    extracted.extend(_extract_tool_call_tags(text))
    if not extracted:
        extracted.extend(_extract_xml_function_tags(text))
    if not extracted:
        extracted.extend(_extract_direct_tool_tags(text, allowed_tool_names))
    if not extracted:
        extracted.extend(_extract_bracket_tool_calls(text))
    if not extracted:
        extracted.extend(_extract_markdown_json_blocks(text, allowed_tool_names))
    if not extracted:
        extracted.extend(_extract_markdown_bash_blocks(text, allowed_tool_names))
    if not extracted:
        return [], text

    if allowed_tool_names:
        remapped: list[RepairedToolCall] = []
        for tc in extracted:
            tc_name = tc.name
            if tc_name not in allowed_tool_names:
                if tc_name in ("terminal", "bash", "sh") and "run_shell" in allowed_tool_names:
                    tc_name = "run_shell"
                elif tc_name in ("run_shell", "bash", "sh") and "terminal" in allowed_tool_names:
                    tc_name = "terminal"
            if tc_name in allowed_tool_names:
                remapped.append(RepairedToolCall(id=tc.id, name=tc_name, arguments=tc.arguments, raw=tc.raw))
        extracted = remapped
        if not extracted:
            return [], text

    scrubbed = text
    standard_tool_calls: list[dict[str, Any]] = []
    for tc in extracted:
        scrubbed = scrubbed.replace(tc.raw, "").strip()
        standard_tool_calls.append({
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
        })
    return standard_tool_calls, scrubbed


__all__ = [
    "RepairedToolCall",
    "extract_xml_tool_call",
    "repair_plain_text_tool_calls",
    "repair_tool_call",
    "safe_parse_tool_arguments",
]
