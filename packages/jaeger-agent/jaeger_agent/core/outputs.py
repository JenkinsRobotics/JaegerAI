"""Typed final-output routing for multimodal JaegerAgent faces.

Final speech is not a tool action. The model returns one compact channel
directive with its final answer, and the engine routes the resulting text to
its own output nodes. A turn-scoped flag lets the normal tool-availability
gate hide external speech tools while this self-contained face is running.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Literal

DYNAMIC_OUTPUT_PROMPT = """

# Dynamic output routing
This face can emit text, speech, or both. You choose per turn:
- Each user turn begins with `[input: text]` or `[input: speech]`; use it as
  context when choosing the most natural response channel.
- For `[input: speech]`, normally answer with SPEECH so the user hears the
  reply. Choose BOTH if a written copy is useful or requested. Use TEXT alone
  only when the user explicitly requests no speech, or the answer is primarily
  code or a large table that should be read on screen.
- For `[input: text]`, normally answer with TEXT. If the user asks you to say,
  speak, read aloud, or answer by voice, use SPEECH or BOTH.
- Begin the final response with exactly one directive: `[OUTPUT:TEXT]`,
  `[OUTPUT:SPEECH]`, `[OUTPUT:BOTH]`, or `[OUTPUT:SILENT]`.
- Put the response after the directive. SILENT has no response body.
- Do not call `text_to_speech` for final user-facing speech. That external
  narration tool is intentionally unavailable in this multimodal face.
Choose naturally from the request, conversational context, and input modality.
The harness removes the directive and routes the content through its own output
nodes. These rules override the base text-only/default-TTS guidance.
"""

OutputMode = Literal["dynamic", "speech", "text", "mirror"]


@dataclass(frozen=True)
class OutputDecision:
    display_text: str
    speech_text: str
    channels: tuple[str, ...]
    source: str


_MULTIMODAL_OUTPUT_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jaeger_agent_multimodal_output_active", default=False
)
_OUTPUT_DIRECTIVE = re.compile(
    r"^\s*\[OUTPUT:(TEXT|SPEECH|BOTH|SILENT)\]\s*", re.IGNORECASE
)
_TRAILING_OUTPUT_DIRECTIVE = re.compile(
    r"\s*\[OUTPUT:(TEXT|SPEECH|BOTH|SILENT)\]\s*$", re.IGNORECASE
)


@contextmanager
def multimodal_output_scope() -> Iterator[None]:
    """Mark schema building and execution as owned by a multimodal face."""
    token = _MULTIMODAL_OUTPUT_ACTIVE.set(True)
    try:
        yield
    finally:
        _MULTIMODAL_OUTPUT_ACTIVE.reset(token)


def multimodal_output_active() -> bool:
    """Whether final output is currently owned by the multimodal engine."""
    return _MULTIMODAL_OUTPUT_ACTIVE.get()


def split_output_directive(reply: str) -> tuple[str, str]:
    """Return ``(channel, body)``; tolerate a model putting its tag last."""
    clean = (reply or "").strip()
    match = _OUTPUT_DIRECTIVE.match(clean)
    if match is not None:
        return match.group(1).upper(), clean[match.end():].strip()
    # Tool-result finalization occasionally makes small local models append
    # the directive despite being told to prefix it. The choice is still
    # unambiguous, so route it and keep the control marker out of the UI/TTS.
    match = _TRAILING_OUTPUT_DIRECTIVE.search(clean)
    if match is not None:
        return match.group(1).upper(), clean[:match.start()].strip()
    return "", clean


def transform_output_content(reply: str, transform: Callable[[str], str]) -> str:
    """Restyle final content without allowing a filter to lose its channel."""
    channel, body = split_output_directive(reply)
    if not channel:
        return transform(body)
    marker = f"[OUTPUT:{channel}]"
    if channel == "SILENT":
        return marker
    transformed = (transform(body) or "").strip()
    return f"{marker} {transformed}".strip()


def _dynamic_decision(
    reply: str,
    input_modality: Literal["text", "speech"],
) -> OutputDecision:
    """Parse a channel directive, falling back to the user's channel."""
    clean = (reply or "").strip()
    if clean.upper() in {"[SILENT]", "<SILENT>", "[NO_RESPONSE]"}:
        return OutputDecision("", "", (), "model-silent")

    channel, content = split_output_directive(clean)
    if not channel:
        if input_modality == "speech":
            return OutputDecision(
                "", clean, ("speech",), "input-modality-fallback"
            )
        return OutputDecision(clean, "", ("text",), "model-text-fallback")

    channel = channel.lower()
    if channel == "silent":
        return OutputDecision("", "", (), "model-output-directive")
    if channel == "speech":
        return OutputDecision("", content, ("speech",), "model-output-directive")
    if channel == "both":
        return OutputDecision(
            content,
            content,
            ("text", "speech"),
            "model-output-directive",
        )
    return OutputDecision(content, "", ("text",), "model-output-directive")


def decide_output(
    *,
    mode: OutputMode,
    input_modality: Literal["text", "speech"],
    reply: str,
) -> OutputDecision:
    """Resolve a typed model choice or one configured compatibility policy."""
    clean = (reply or "").strip()
    if mode == "dynamic":
        return _dynamic_decision(clean, input_modality)
    # A previous turn may leave routing guidance in the model's history.
    # Control directives never belong in captions or synthesized audio,
    # including when the user switches to a fixed output mode.
    channel, clean = split_output_directive(clean)
    if channel == "SILENT":
        clean = ""
    if mode == "speech":
        return OutputDecision(clean, clean, ("text", "speech"), "configured-speech")
    if mode == "text":
        return OutputDecision(clean, "", ("text",), "configured-text")
    if mode == "mirror" and input_modality == "speech":
        return OutputDecision(clean, clean, ("text", "speech"), "mirrored-speech")
    return OutputDecision(clean, "", ("text",), "mirrored-text")


__all__ = [
    "DYNAMIC_OUTPUT_PROMPT",
    "OutputDecision",
    "OutputMode",
    "decide_output",
    "multimodal_output_active",
    "multimodal_output_scope",
    "split_output_directive",
    "transform_output_content",
]
