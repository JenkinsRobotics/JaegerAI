"""Per-dialect tool presentation + extraction.

One module per tool dialect — each owns BOTH sides of the contract for
the models that speak it:

  * :mod:`chatml`  — Hermes, Qwen, DeepHermes, DeepSeek-R1
  * :mod:`mistral` — Mistral, Ministral, Nemo
  * :mod:`llama3`  — plain Llama-3 + the bare-JSON form others borrow
  * :mod:`harmony` — gpt-oss
  * :mod:`gemma`   — Gemma 3 / 4 (structured ``tools=``; no prose)

The guiding principle (operator, 2026-05-27): **we match the model, the
model never drifts to match us.** :func:`detect_family` maps a model
onto its dialect; :func:`render_tools_for` presents tools in that
dialect's native form; :func:`extract_tool_calls` reads back whatever
the model natively emitted.

``extract_tool_calls`` is dialect-agnostic on purpose: a model can drift
between shapes (e.g. a ChatML model that falls back to bare JSON), so
the dispatcher walks every dialect in a fixed priority order rather than
trusting the classification. The order — and the synthetic id prefixes —
are preserved byte-for-byte from the pre-refactor monolithic parser so
the benchmark suite compares apples to apples.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.agent.schemas.message_types import ToolCall

from . import chatml, gemma, harmony, llama3, mistral
from ._shared import new_id, normalize_tool_name, repair_arguments
from .detect import FAMILIES, detect_family, detect_reasoning, strip_think_blocks
from .gemma import strip_reasoning_channels


# Union of the envelope-strip patterns (Gemma's three natives + the
# ChatML/Hermes ``<tool_call>`` envelope). The TUI / finalize fallback
# uses this to scrub tool-call markup from text shown to the user.
_DRIFT_PATTERNS = [*gemma.NATIVE_PATTERNS, chatml.ENVELOPE_PATTERN]

# Wrappers we treat as "this text already speaks a non-Llama dialect" —
# so a bare-JSON Hermes envelope isn't misread as a Llama raw-JSON call.
_NON_LLAMA_WRAPPERS = ("<tool_call>", "<|tool_call|>", "<|tool_call>", "<function=")


def _wrap(calls: list[dict[str, Any]], prefix: str) -> list[ToolCall]:
    return [
        {"id": new_id(prefix), "name": c["name"], "arguments": c["args"]}
        for c in calls
    ]


def parse_harmony(text: str) -> tuple[list[ToolCall], str]:
    """Parse gpt-oss harmony output into ``(tool_calls, answer)``.

    Tool calls come off the ``commentary`` channel; the answer is the
    ``final`` channel (analysis is stripped). Returns synthetic-id tool
    calls + the cleaned user-facing answer. Used by the adapter when the
    raw response contains ``<|channel|>`` markers."""
    calls = _wrap(harmony.extract_calls(text), "harmony")
    return calls, harmony.clean_channels(text)


def extract_tool_calls(text: str) -> list[ToolCall]:
    """Extract tool calls from a model's NATIVE textual form.

    Walks the dialects in priority order and returns the first dialect
    that yields calls (Gemma + Hermes JSON envelopes are combined, since
    a model may emit either through the same envelope machinery).
    Returns an empty list when no recognised dialect appears — the agent
    loop then treats the response as a final answer.

    Returned dicts are in *internal* :class:`ToolCall` shape with
    ``arguments`` as a real ``dict`` (not a JSON-encoded string).
    """
    # 1. Mistral ``[TOOL_CALLS]`` — JSON array (pre-v11) or interleaved
    #    name+brace-args (v11+). No ``<`` needed; check before the
    #    no-``<`` early-return below.
    if "[TOOL_CALLS]" in text:
        calls = mistral.extract_calls(text)
        if calls:
            return _wrap(calls, "mistral")

    # 2. Llama 3.x/4 raw-JSON — bare ``{"name": …, "arguments": …}`` with
    #    NO envelope (DeepSeek-R1 / some Qwen builds borrow this), or the
    #    same JSON behind ``<|python_tag|>``. Require the python tag OR
    #    the absence of every other dialect's opening tag — otherwise a
    #    Hermes JSON envelope inside ``<tool_call>`` would be misread.
    _llama_marker = llama3.BOT in text
    _other_wrapper = any(w in text for w in _NON_LLAMA_WRAPPERS)
    if (_llama_marker or not _other_wrapper) and (
        "{" in text and ('"name"' in text or '"tool_name"' in text)
    ):
        calls = llama3.extract_calls(text)
        if calls:
            return _wrap(calls, "llama")

    # 2b. Mistral v11 interleaved WITHOUT the ``[TOOL_CALLS]`` token —
    #     the whole message is a bare ``name{json}`` (Ministral's native
    #     emission). No ``<`` and no ``"name"`` key, so it slips past
    #     both checks above; catch it before the no-``<`` early return.
    bare_mistral = mistral.extract_bare_calls(text)
    if bare_mistral:
        return _wrap(bare_mistral, "mistral")

    if "<" not in text:
        return []

    # 3. Qwen ``<function=…>`` XML — distinct from every other pattern; a
    #    model only ever speaks one dialect, so if Qwen calls are present
    #    they ARE the answer.
    qwen = chatml.extract_qwen(text)
    if qwen:
        return _wrap(qwen, "qwen")

    # 4. JSON envelopes — Gemma's three natives, then the ChatML/Hermes
    #    ``<tool_call>{json}</tool_call>`` envelope. Combined + ordered
    #    exactly as the pre-refactor pattern loop.
    out: list[ToolCall] = []
    out.extend(_wrap(gemma.extract_native(text), "drift"))
    out.extend(_wrap(chatml.extract_envelope(text), "drift"))
    return out


# NB harmony (gpt-oss) is deliberately ABSENT from every renderer map.
# gpt-oss's native interface is llama-cpp's structured harmony chat
# handler — it manages the analysis/commentary/final channels itself and
# actively REJECTS messages whose content holds ``<|channel|>`` text. So
# we drive it through the structured ``tools=`` path (like Gemma): no
# prose injection, no text-history echo. Channel cleanup on the way out
# lives in :func:`harmony.clean_channels`.
_RENDERERS = {
    "chatml": chatml.render_tools,
    "mistral": mistral.render_tools,
    "llama3": llama3.render_tools,
    "gemma": gemma.render_tools,
}

_CALL_RENDERERS = {
    "chatml": chatml.render_tool_call,
    "mistral": mistral.render_tool_call,
    "llama3": llama3.render_tool_call,
}

_RESULT_RENDERERS = {
    "chatml": chatml.render_tool_result,
    "mistral": mistral.render_tool_result,
    "llama3": llama3.render_tool_result,
}

# Families presented + parsed purely as TEXT (we inject a prose tool
# catalogue, the model emits its native text form, the drift parser
# reads it back). For these we ALSO render tool-call history as text and
# never send the structured ``tool_calls`` field into the model's GGUF
# template — those templates are fragile (DeepSeek-R1 crashes on dict
# args / None content; Hermes builds strip the tool section entirely).
# Gemma / unknown are NOT here: Gemma's structured ``tools=`` path works
# through llama-cpp's handler, so we leave it alone.
PROSE_FAMILIES = frozenset(_CALL_RENDERERS)


def render_tools_for(family: str, tools: list[Any]) -> str:
    """Render the system-prompt text presenting ``tools`` in ``family``'s
    native dialect. Returns ``""`` when the family needs no prose
    injection (Gemma / unknown) or there are no tools."""
    renderer = _RENDERERS.get(family)
    if renderer is None:
        return ""
    return renderer(tools)


def render_tool_call_for(family: str, name: str, args: dict[str, Any]) -> str:
    """Render a prior tool call as ``family``'s native text. Empty when
    the family isn't text-driven (Gemma / unknown)."""
    renderer = _CALL_RENDERERS.get(family)
    return renderer(name, args) if renderer else ""


def render_tool_result_for(family: str, content: str) -> str:
    """Render a tool result as ``family``'s native text. Empty when the
    family isn't text-driven (Gemma / unknown)."""
    renderer = _RESULT_RENDERERS.get(family)
    return renderer(content) if renderer else ""


def textify_tool_history(
    wire_messages: list[dict[str, Any]], family: str
) -> list[dict[str, Any]]:
    """Rewrite OpenAI-shape tool history into plain in-dialect text turns
    for a text-driven ``family``.

    For each message:
      * assistant + ``tool_calls`` → a plain assistant turn whose content
        appends each call rendered as native text; the structured
        ``tool_calls`` field is dropped.
      * ``tool`` (a tool result) → a plain ``user`` turn carrying the
        result rendered as native text.
      * everything else passes through untouched.

    The point: the model's GGUF chat template only ever sees plain
    user/assistant/system string content, so its fragile native
    tool-rendering branch never fires. Non-prose families are returned
    unchanged (they keep the structured path).
    """
    if family not in PROSE_FAMILIES:
        return wire_messages
    out: list[dict[str, Any]] = []
    for m in wire_messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            parts: list[str] = []
            content = m.get("content")
            if content:
                parts.append(str(content))
            for tc in m.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        import json as _json
                        args = _json.loads(raw_args) if raw_args else {}
                    except (TypeError, ValueError):
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                if name:
                    parts.append(render_tool_call_for(family, name, args))
            new_m = {k: v for k, v in m.items() if k != "tool_calls"}
            new_m["content"] = "\n".join(parts)
            out.append(new_m)
        elif role == "tool":
            result = render_tool_result_for(family, str(m.get("content") or ""))
            out.append({"role": "user", "content": result})
        else:
            out.append(m)
    return out


__all__ = [
    # extraction
    "extract_tool_calls",
    "parse_harmony",
    "repair_arguments",
    "normalize_tool_name",
    # presentation
    "render_tools_for",
    "render_tool_call_for",
    "render_tool_result_for",
    "textify_tool_history",
    "PROSE_FAMILIES",
    # classification
    "detect_family",
    "detect_reasoning",
    "strip_think_blocks",
    "strip_reasoning_channels",
    "FAMILIES",
]
