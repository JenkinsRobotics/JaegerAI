"""ChatML / Hermes dialect.

Models: Hermes-3/4, Qwen3.x (incl. Qwen3-Coder), DeepHermes, DeepSeek-R1
(Qwen-distilled). They were trained on the ChatML tool convention:

  * presentation: a ``<tools>[…schemas…]</tools>`` block + an instruction
    to emit calls inside ``<tool_call>…</tool_call>``.
  * emission (two observed shapes, both salvaged here):
      - Hermes JSON envelope: ``<tool_call>{"name": X, "arguments": …}</tool_call>``
      - Qwen XML: ``<tool_call><function=X><parameter=Y>v</parameter></function></tool_call>``
        (and a loose variant where the ``<tool_call>`` wrapper is dropped).

Bare top-level JSON (``{"name": …}`` with no envelope) is the Llama-3
raw-JSON form — DeepSeek-R1 borrows it — and is handled by
:mod:`llama3`, which the package dispatcher tries first for that shape.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import _shared


# Qwen3-Coder native XML form — distinct from any Gemma pattern.
_QWEN_TOOLCALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_QWEN_FUNCTION = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_QWEN_PARAM = re.compile(r"<parameter=([^>]+)>\n?(.*?)\n?</parameter>", re.DOTALL)

# Standard Hermes JSON envelope. Capture EVERYTHING inside — not a brace
# block — so f-string braces inside a ``content:"…"`` value don't stop
# the lazy quantifier early.
ENVELOPE_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def extract_qwen(text: str) -> list[dict[str, Any]]:
    """Salvage Qwen3-Coder's ``<function=…><parameter=…>`` tool calls.

    Two shapes in the wild, both salvaged here:

      - **Strict (chat-template official):**
        ``<tool_call><function=X><parameter=Y>v</parameter></function></tool_call>``
      - **Loose (the model sometimes drops the wrapper):**
        ``<function=X><parameter=Y>v</parameter></function>``
        — and sometimes appends a stray ``</tool_call>`` closer with no
        matching opener.

    Returns ``[{name, args}]``. Parameter values are kept as raw strings;
    downstream Pydantic validation coerces them.
    """
    out: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1. Strict form first — any <function=> *inside* a <tool_call>
    #    wrapper. Recording the span lets us skip the same function
    #    block in the loose-form pass below.
    for tc in _QWEN_TOOLCALL.finditer(text):
        for fn in _QWEN_FUNCTION.finditer(tc.group(1)):
            name = fn.group(1).strip()
            if not name:
                continue
            args: dict[str, Any] = {}
            for pm in _QWEN_PARAM.finditer(fn.group(2)):
                args[pm.group(1).strip()] = pm.group(2)
            out.append({"name": name, "args": args})
        seen_spans.add((tc.start(), tc.end()))

    # 2. Loose form — any <function=> NOT covered by a strict wrapper.
    for fn in _QWEN_FUNCTION.finditer(text):
        start, end = fn.start(), fn.end()
        if any(s <= start and end <= e for s, e in seen_spans):
            continue
        name = fn.group(1).strip()
        if not name:
            continue
        args = {}
        for pm in _QWEN_PARAM.finditer(fn.group(2)):
            args[pm.group(1).strip()] = pm.group(2)
        out.append({"name": name, "args": args})
    return out


def extract_envelope(text: str) -> list[dict[str, Any]]:
    """Salvage Hermes ``<tool_call>{json}</tool_call>`` JSON envelopes.

    Tolerant payload parsing (trailing commas, Gemma quote tokens,
    double-encoded arg strings, flat-arg style) lives in
    :func:`_shared.payload_to_call`."""
    out: list[dict[str, Any]] = []
    for match in ENVELOPE_PATTERN.finditer(text):
        call = _shared.payload_to_call(match.group(1))
        if call:
            out.append(call)
    return out


def render_tools(tools: list[Any]) -> str:
    """Present ``tools`` in the ChatML / Hermes convention."""
    if not tools:
        return ""
    schema_json = _shared.tool_schemas_json(tools)
    return (
        "You have access to the following tools. To call one, emit "
        "EXACTLY:\n"
        "<tool_call>\n{\"name\": <tool-name>, \"arguments\": <json>}\n"
        "</tool_call>\n"
        "After the result returns, continue until the task is done, "
        "then answer in plain text.\n"
        f"<tools>\n{schema_json}\n</tools>"
    )


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Echo a PRIOR tool call back to the model as the ChatML text it
    would itself have emitted — so multi-turn history stays in-dialect
    and never touches the model's (fragile) structured tool template."""
    payload = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
    return f"<tool_call>\n{payload}\n</tool_call>"


def render_tool_result(content: str) -> str:
    """Echo a tool result in the Hermes ``<tool_response>`` convention."""
    return f"<tool_response>\n{content}\n</tool_response>"


__all__ = [
    "extract_qwen", "extract_envelope", "render_tools",
    "render_tool_call", "render_tool_result", "ENVELOPE_PATTERN",
]
