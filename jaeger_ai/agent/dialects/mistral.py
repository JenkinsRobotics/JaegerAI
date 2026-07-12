"""Mistral / Ministral / Nemo dialect.

Presentation uses ``[AVAILABLE_TOOLS]…[/AVAILABLE_TOOLS]``; the model
emits calls behind a ``[TOOL_CALLS]`` bot-token. Two emission formats,
both seen in the wild:

  - **Pre-v11** (JSON array):
    ``content[TOOL_CALLS] [{"name": "...", "arguments": {...}}, ...]``
  - **v11+** (interleaved):
    ``[TOOL_CALLS]name1{"k":"v"}[TOOL_CALLS]name2{"k":"v"}``
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import _shared


_BOT = "[TOOL_CALLS]"

# Bare interleaved form: ``name{json}`` with NO ``[TOOL_CALLS]`` token —
# Ministral emits exactly this (the inner half of the v11 format). Anchored
# to the start so it only fires when the whole message IS a tool call.
_BARE_LEADING = re.compile(r"^\s*([a-zA-Z_][\w]*)\s*\{")


def extract_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Mistral ``[TOOL_CALLS]`` emissions. Returns ``[{name, args}]``.

    Refuses to fuzzy-match an unknown name — same conservative stance as
    the other dialects."""
    idx = text.find(_BOT)
    if idx < 0:
        return []
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()

    while idx >= 0:
        # Move past the bot token and any whitespace.
        cursor = idx + len(_BOT)
        while cursor < len(text) and text[cursor] in (" ", "\t", "\n", "\r"):
            cursor += 1
        if cursor >= len(text):
            break
        ch = text[cursor]
        if ch == "[":
            # Pre-v11 — single JSON array of {"name", "arguments"} objects.
            try:
                arr, end = decoder.raw_decode(text, cursor)
            except json.JSONDecodeError:
                break
            if isinstance(arr, list):
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or ""
                    args = item.get("arguments") or item.get("parameters") or {}
                    if isinstance(name, str) and name and isinstance(args, dict):
                        out.append({"name": name.strip(), "args": args})
            idx = text.find(_BOT, end)
            continue
        # v11+ — bare ``name{"k":"v"}``; possibly chained with more
        # [TOOL_CALLS]name{...} segments. Read name up to the first
        # ``{`` (greedy), then raw_decode the JSON args.
        brace = text.find("{", cursor)
        if brace < 0:
            break
        name = text[cursor:brace].strip()
        try:
            obj, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            break
        if name and isinstance(obj, dict):
            out.append({"name": name, "args": obj})
        idx = text.find(_BOT, end)
    return out


def extract_bare_calls(text: str) -> list[dict[str, Any]]:
    """Salvage a bare ``name{json}`` tool call (Mistral v11 interleaved
    form with the ``[TOOL_CALLS]`` token dropped — Ministral's native
    emission). Anchored: only fires when the WHOLE message is a single
    ``name{json}`` with no trailing prose, so it can't false-match a
    ``word{…}`` buried in ordinary text."""
    m = _BARE_LEADING.match(text)
    if not m:
        return []
    name = m.group(1)
    brace = text.index("{", m.start())
    try:
        obj, end = json.JSONDecoder().raw_decode(text, brace)
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict) or text[end:].strip():
        return []
    return [{"name": name, "args": obj}]


def render_tools(tools: list[Any]) -> str:
    """Present ``tools`` in the Mistral convention (never forces the
    Hermes ``<tool_call>`` tag)."""
    if not tools:
        return ""
    schema_json = _shared.tool_schemas_json(tools)
    return (
        "Tools are available. To call one, emit EXACTLY:\n"
        "[TOOL_CALLS][{\"name\": <tool-name>, \"arguments\": <json>}]\n"
        "After the result returns, continue until done, then answer "
        "plainly.\n"
        f"[AVAILABLE_TOOLS]{schema_json}[/AVAILABLE_TOOLS]"
    )


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Echo a prior tool call in Mistral's ``[TOOL_CALLS]`` convention."""
    payload = json.dumps([{"name": name, "arguments": args}], ensure_ascii=False)
    return f"[TOOL_CALLS]{payload}"


def render_tool_result(content: str) -> str:
    """Echo a tool result in Mistral's ``[TOOL_RESULTS]`` convention."""
    return f"[TOOL_RESULTS]{content}[/TOOL_RESULTS]"


__all__ = [
    "extract_calls", "extract_bare_calls", "render_tools",
    "render_tool_call", "render_tool_result",
]
