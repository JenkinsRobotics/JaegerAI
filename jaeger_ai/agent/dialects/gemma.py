"""Gemma 3 / 4 dialect.

Presentation: **none**. Gemma's structured ``tools=`` path works through
llama-cpp's function-calling handler, so injecting system-prompt prose
would be redundant and risks perturbing a model that already routes
well. :func:`render_tools` returns ``""`` by construction.

Parsing: Gemma emits tool calls in three native shapes, all salvaged
here (the model only ever speaks one, but builds vary):

  * brace args:  ``<|tool_call>call:name{"k": "v"}<tool_call|>``
  * paren kwargs: ``<|tool_call>call:name(key='value', n=3)<tool_call|>``
  * legacy JSON envelope: ``<|tool_call|>{"name": …}<|/tool_call|>``

Tool names allow ``:`` and ``/`` so MCP-qualified names like
``mcp:web/fetch`` salvage.
"""

from __future__ import annotations

import re
from typing import Any

from . import _shared


# Gemma's three native envelopes. Order matters — it is preserved by the
# package dispatcher so multi-call output ordering stays byte-for-byte
# identical to the pre-refactor parser.
NATIVE_PATTERNS = [
    # <|tool_call>call:name{...}<tool_call|>  (brace args)
    re.compile(
        r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\{(.*?)\}\s*<tool_call\|>",
        re.DOTALL,
    ),
    # <|tool_call>call:name(key='value')<tool_call|>  (paren kwargs)
    re.compile(
        r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\((.*?)\)\s*<tool_call\|>",
        re.DOTALL,
    ),
    # <|tool_call|>…<|/tool_call|>   (legacy JSON envelope)
    re.compile(r"<\|tool_call\|>\s*(.*?)\s*<\|/tool_call\|>", re.DOTALL),
]


# Salvage patterns: Gemma 4 sometimes omits the closing ``<tool_call|>``
# token — the same malformed-emission class as the leaked channel markers
# below (2026-06-20) — stranding an otherwise-valid opening call as plain
# text so the model's real tool call is dropped and the turn halts. These
# match the opening form WITHOUT the closing token, greedy to the last
# brace/paren so nested args survive. Consulted ONLY when the strict
# patterns matched nothing, so well-formed (multi-)call output is untouched.
TOLERANT_PATTERNS = [
    re.compile(r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\{(.*)\}", re.DOTALL),
    re.compile(r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\((.*)\)", re.DOTALL),
]


def extract_native(text: str) -> list[dict[str, Any]]:
    """Salvage Gemma's three native tool-call forms. Returns
    ``[{name, args}]`` in pattern order, then match order within a
    pattern."""
    out: list[dict[str, Any]] = []
    for pat_idx, pattern in enumerate(NATIVE_PATTERNS):
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2:
                # Brace (pat 0) or paren (pat 1) args.
                name = groups[0]
                if pat_idx == 1:
                    args: Any = _shared.parse_paren_args(groups[1])
                else:
                    args = _shared.parse_gemma_args(groups[1])
                if not name:
                    continue
                if not isinstance(args, dict):
                    args = {"value": args}
                out.append({"name": str(name), "args": args})
            else:
                # Legacy JSON envelope (pat 2) — tolerant payload parse.
                call = _shared.payload_to_call(groups[0])
                if call:
                    out.append(call)
    if out or "<|tool_call>" not in text:
        return out
    # Nothing matched but an opening token is present: salvage the
    # close-token-less form (see TOLERANT_PATTERNS).
    for pat_idx, pattern in enumerate(TOLERANT_PATTERNS):
        for match in pattern.finditer(text):
            name = match.group(1)
            if not name:
                continue
            if pat_idx == 1:
                args = _shared.parse_paren_args(match.group(2))
            else:
                args = _shared.parse_gemma_args(match.group(2))
            if not isinstance(args, dict):
                args = {"value": args}
            out.append({"name": str(name), "args": args})
        if out:
            break
    return out


def render_tools(tools: list[Any]) -> str:
    """Gemma needs no prose injection — its structured ``tools=`` path
    works. Always returns ``""``."""
    return ""


# Gemma 4's reasoning/channel markers, rendered as raw text by llama.cpp
# (the special tokens leak out detokenised). The MALFORMED forms it emits
# — ``<|channel>`` (no closing pipe) and ``<channel|>`` (no opening pipe)
# — never match the proper ``<|channel|>`` harmony form, so the whole
# block ``<|channel>thought\n<channel|>…answer…`` surfaced verbatim in
# the TUI as a phantom "thought". 2026-06-20.
_CHANNEL_MARKER = re.compile(r"<\|?channel\|?>")
_CHANNEL_LABEL = re.compile(
    r"^\s*(?:thought|thinking|analysis|commentary|final)\b[\s:]*",
    re.IGNORECASE,
)


def strip_reasoning_channels(text: str) -> str:
    """Strip Gemma's leaked channel markers, returning the content of the
    LAST channel (the answer follows the reasoning preamble) with its
    channel-name label removed. A no-op when no channel markers present."""
    if not text or "channel" not in text.lower():
        return text
    segments = _CHANNEL_MARKER.split(text)
    if len(segments) <= 1:
        return text
    tail = _CHANNEL_LABEL.sub("", segments[-1])
    return tail.strip()


__all__ = [
    "extract_native", "render_tools", "NATIVE_PATTERNS",
    "strip_reasoning_channels",
]
