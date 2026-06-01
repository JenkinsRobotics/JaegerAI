"""gpt-oss harmony dialect.

gpt-oss emits the OpenAI *harmony* response format — three channels:

  * ``<|channel|>analysis<|message|>…<|end|>`` — chain-of-thought
    (reasoning; stripped before the answer, like ``<think>``).
  * ``<|channel|>commentary to=functions.NAME …<|message|>{json}`` — a
    tool call: recipient after ``to=`` (``functions.`` prefix optional),
    arguments are the JSON object after ``<|message|>``.
  * ``<|channel|>final<|message|>…`` — the user-facing answer.

llama-cpp's gpt-oss chat handler does NOT parse these channels into the
structured ``tool_calls`` field in this build — it returns the raw
harmony text — so we parse it here. gpt-oss is driven through the
structured ``tools=`` path (it's absent from the package's prose/render
maps): its handler manages tool presentation and rejects ``<|channel|>``
text echoed back into message content, so we must NOT text-drive it.
"""

from __future__ import annotations

import json
import re
from typing import Any


# A channel body runs until the next harmony control token or end-of-text.
_BODY_END = r"(?=<\|end\|>|<\|call\|>|<\|return\|>|<\|start\|>|<\|channel\|>|$)"

_FINAL = re.compile(
    r"<\|channel\|>final<\|message\|>(.*?)" + _BODY_END, re.DOTALL
)
# Commentary tool call: capture the recipient name; the JSON args are
# raw_decoded from the first ``{`` after the channel's ``<|message|>``.
_COMMENTARY = re.compile(
    r"<\|channel\|>commentary[^\n]*?to=(?:functions\.)?([A-Za-z_][\w.\-]*)"
    r".*?<\|message\|>",
    re.DOTALL,
)


def extract_calls(text: str) -> list[dict[str, Any]]:
    """Salvage gpt-oss tool calls from the harmony ``commentary`` channel.
    Returns ``[{name, args}]`` (name stripped of the ``functions.``
    prefix; args raw_decoded so nested JSON survives)."""
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for m in _COMMENTARY.finditer(text):
        name = m.group(1).strip()
        if not name:
            continue
        brace = text.find("{", m.end())
        if brace < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append({"name": name, "args": obj})
    return out


def clean_channels(text: str) -> str:
    """Return the user-facing answer from harmony output.

    In harmony the answer is ALWAYS the ``final`` channel — ``analysis``
    is private reasoning and ``commentary`` carries tool calls. So a
    response with no ``final`` channel (a pure tool-call / reasoning
    turn) has no user answer: return ``""``."""
    final = _FINAL.search(text)
    return final.group(1).strip() if final else ""


__all__ = ["extract_calls", "clean_channels"]
