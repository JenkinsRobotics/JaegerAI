"""Plain Llama-3.x / 4 dialect — raw-JSON tool calls.

Llama emits a tool call as a bare JSON object, optionally prefixed by
the ``<|python_tag|>`` bot-token::

    <|python_tag|>{"name": "get_time", "parameters": {"timezone": "UTC"}}

or simply, with no wrapping at all::

    {"name": "get_weather", "arguments": {"location": "Tokyo"}}

This bare-JSON form is also what reasoning models distilled from Qwen
(DeepSeek-R1) and some Qwen builds fall back to — so the package
dispatcher tries this extractor for any envelope-free ``{"name": …}``
text, regardless of the model's nominal family. ``arguments`` and
``parameters`` are both accepted (Llama uses ``parameters``; the rest of
the matrix uses ``arguments``).
"""

from __future__ import annotations

import json
from typing import Any

from . import _shared


BOT = "<|python_tag|>"


def extract_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Llama 3.x / 4 raw-JSON tool calls. Returns ``[{name, args}]``.

    Uses stdlib ``json.JSONDecoder.raw_decode`` so multiple JSON objects
    in a row work and surrounding prose is tolerated."""
    # Trim past the bot token if present so the first brace is the JSON
    # we care about.
    scan = text.split(BOT, 1)[1] if BOT in text else text
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(scan):
        # Hop to the next '{' — raw_decode wants a JSON-shaped prefix.
        brace = scan.find("{", idx)
        if brace < 0:
            break
        try:
            obj, end = decoder.raw_decode(scan, brace)
        except json.JSONDecodeError:
            idx = brace + 1
            continue
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("tool_name") or ""
            args = obj.get("arguments")
            if args is None:
                args = obj.get("parameters")
            if isinstance(name, str) and name and isinstance(args, dict):
                out.append({"name": name.strip(), "args": args})
        idx = end
    return out


def render_tools(tools: list[Any]) -> str:
    """Present ``tools`` in the Llama-3 convention — JSON after the
    python tag."""
    if not tools:
        return ""
    schema_json = _shared.tool_schemas_json(tools)
    return (
        "You can call tools. To do so, emit a JSON object of the form "
        "{\"name\": <tool-name>, \"parameters\": <json>} prefixed by "
        "<|python_tag|>. After the result returns, continue until "
        "done, then answer plainly.\n"
        f"Available tools (JSON schemas): {schema_json}"
    )


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Echo a prior tool call in the Llama-3 ``<|python_tag|>`` form
    (Llama names the args object ``parameters``)."""
    payload = json.dumps({"name": name, "parameters": args}, ensure_ascii=False)
    return f"{BOT}{payload}"


def render_tool_result(content: str) -> str:
    """Llama-3 ipython results are the raw output; the surrounding user
    turn is enough context, so echo plainly."""
    return content


__all__ = [
    "extract_calls", "render_tools", "render_tool_call",
    "render_tool_result", "BOT",
]
