"""Model → dialect classification.

The guiding principle (set by the operator 2026-05-27): **we match the
model, the model never drifts to match us.** Each model family was
trained to receive tools and emit tool calls in a specific dialect.
:func:`detect_family` maps a model's name + embedded chat template onto
one of the dialect modules in this package; the agent then presents +
parses tools in that dialect's native form.

Why presentation is needed at all: many local GGUF builds ship a chat
template with the tool-calling section stripped out (verified: the LM
Studio Hermes-3-Llama-3.1-8B GGUF's template has no ``tools``
rendering). So llama-cpp's structured ``tools=`` param silently no-ops
and the model never sees the tools → it answers as a plain chatbot. To
fix that WITHOUT forcing a format, JROS injects the tool catalogue into
the system prompt **in the model's own native dialect**, then the
dialect's parser reads back whatever the model natively emits.
"""

from __future__ import annotations

import re


# Tool dialects we know how to present + parse natively. ``gemma`` and
# ``unknown`` deliberately inject no presentation prose — Gemma's
# structured ``tools=`` path works through llama-cpp's handler, so
# injecting prose would be redundant (and risks perturbing a model that
# already works).
FAMILIES = ("chatml", "mistral", "llama3", "harmony", "gemma", "unknown")


def detect_family(model_name: str = "", chat_template: str = "") -> str:
    """Classify a model into its native tool-call dialect.

    Name takes precedence over template signature, because finetunes
    invert the two: Hermes-3 is *built on* Llama-3 (its chat template
    uses Llama-3 ``<|start_header_id|>`` headers) but was *trained to
    tool-call* in the ChatML/Hermes ``<tool_call>`` convention. So a
    name match (``hermes``) correctly picks ``chatml`` even though the
    template looks like Llama-3.
    """
    name = (model_name or "").lower()
    tmpl = (chat_template or "").lower()

    # ── name-based (most reliable for finetunes) ──────────────────
    if "gpt-oss" in name or "gpt_oss" in name:
        return "harmony"
    if "hermes" in name or "qwen" in name or "deephermes" in name:
        return "chatml"
    if "mistral" in name or "ministral" in name or "nemo" in name:
        return "mistral"
    if "gemma" in name:
        return "gemma"
    if "llama" in name:
        # Plain Llama (not a Hermes/tool finetune) → Llama-3 tool dialect.
        return "llama3"

    # ── template-signature fallback ───────────────────────────────
    if "harmony" in tmpl or "<|channel|>" in tmpl:
        return "harmony"
    if "[tool_calls]" in tmpl or "[available_tools]" in tmpl:
        return "mistral"
    if "<|im_start|>" in tmpl:
        return "chatml"
    if "<start_of_turn>" in tmpl:
        return "gemma"
    if "<|start_header_id|>" in tmpl:
        return "llama3"
    return "unknown"


def detect_reasoning(model_name: str = "", chat_template: str = "") -> bool:
    """True when the model is a reasoning / hybrid-reasoning model that
    emits ``<think>…</think>`` deliberation before its answer.

    Reasoning models matter for two pipeline behaviours:
      * Their ``<think>`` blocks must be stripped before tool-call
        parsing (the call comes AFTER the think).
      * They legitimately spend far longer per turn, so the stall
        watchdog needs a higher floor — otherwise it fires mid-think,
        abandons the llama worker, and the next call hits a corrupted
        KV cache and crashes the run (the 2026-05-28 ``0/1`` aborts).

    We detect generously (a false positive only buys a longer timeout,
    which is harmless — the watchdog still fires on a genuine hang).
    """
    name = (model_name or "").lower()
    tmpl = (chat_template or "").lower()
    for marker in ("reasoning", "deephermes", "qwq", "-r1", "r1-",
                   "deepseek-r1", "thinking"):
        if marker in name:
            return True
    # Hermes 4.x is hybrid-reasoning (thinks when it decides to).
    if "hermes-4" in name or "hermes-4.3" in name or "hermes_4" in name:
        return True
    if "<think>" in tmpl or "thinking" in tmpl:
        return True
    return False


def extract_think_blocks(text: str) -> tuple[str, str]:
    """Split model output into ``(visible_answer, deliberation)``.

    The deliberation half used to be dropped on the floor. Surfaces have a
    thinking view they could never fill because this was the only place the
    text existed, and it was discarded here. Returning it lets the bridge emit
    a ``reasoning`` frame without changing what the answer looks like.

    Handles a dangling unterminated ``<think>`` (model cut off mid-thought) by
    treating everything from the tag onward as deliberation.
    """
    if not text or "<think>" not in text:
        return text, ""
    thoughts = [
        match.group(1)
        for match in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    ]
    out = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Dangling open block (no close) → the rest of the text is deliberation.
    if "<think>" in out:
        dangling = re.search(r"<think>(.*)$", out, flags=re.DOTALL)
        if dangling:
            thoughts.append(dangling.group(1))
        out = re.sub(r"<think>.*$", "", out, flags=re.DOTALL)
    return out.strip(), "\n".join(part.strip() for part in thoughts if part.strip())


def strip_think_blocks(text: str) -> str:
    """Remove ``<think>…</think>`` deliberation from model output so the
    tool-call parser + the visible answer see only the post-reasoning
    content.

    Thin wrapper over :func:`extract_think_blocks`, kept because callers and
    tests depend on the string-returning shape. Use ``extract_think_blocks``
    when you also want the deliberation.
    """
    visible, _deliberation = extract_think_blocks(text)
    return visible


__all__ = [
    "FAMILIES",
    "detect_family",
    "detect_reasoning",
    "strip_think_blocks",
    "extract_think_blocks",
]
