"""Station 3 — the persona output filter (dev/docs/agentic_runners.md).

Workers run vanilla: a character in the execution context costs a 4B ~7
bench points (measured — that's why assemble.py deliberately omits the
persona fragment). The character's voice comes back HERE instead: one
bounded, clean-context call that restyles the FINAL answer only. The
filter's context is the answer + the compiled character block — no tools,
no history, no schemas — so personality tokens can never pollute execution.

Fail-open by design: any failure (model error, empty rewrite, oversized
input) returns the ORIGINAL answer untouched. Losing voice is acceptable;
losing the answer is not.

Applied only at the USER-FACING boundary in main.py — the bench drives the
loop directly and never passes through it, so the engine is always measured
persona-off. Kill switches: ``persona.output_filter: false`` in config, or
``JAEGER_PERSONA_FILTER=0`` in the environment.
"""

from __future__ import annotations

import os
from typing import Any


# Answers longer than this pass through unstyled: rewriting a long report
# risks mangling content and doubles latency exactly when the answer is
# already expensive. Voice matters most on short conversational replies.
DEFAULT_MAX_CHARS = 1600

_STYLE_RULES = (
    "Rewrite the assistant reply below in YOUR voice.\n"
    "HARD RULES:\n"
    "- Preserve every fact, number, unit, name, file path, URL, and code "
    "snippet VERBATIM — change only tone and phrasing.\n"
    "- Same language as the reply. Similar length (never more than ~30% "
    "longer). No new information, no opinions the reply doesn't contain.\n"
    "- Plain terminal text: no markdown emphasis.\n"
    "- Output ONLY the rewritten reply — no preamble, no quotes.\n\n"
    "REPLY TO REWRITE:\n"
)


def filter_enabled() -> bool:
    """Env kill switch — ``JAEGER_PERSONA_FILTER=0`` disables globally."""
    return os.environ.get("JAEGER_PERSONA_FILTER", "1").strip() != "0"


def apply_persona_voice(
    client: Any,
    answer: str,
    character_block: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Restyle ``answer`` in the character's voice. Returns the styled text,
    or the ORIGINAL answer on any skip/failure (fail-open).

    Skips (original returned untouched): empty answer, halt/system notes
    (``[...]``), answers longer than ``max_chars``, an empty character
    block, or the env kill switch.
    """
    text = (answer or "").strip()
    block = (character_block or "").strip()
    if (not text or not block or text.startswith("[")
            or len(text) > max_chars or not filter_enabled()):
        return answer
    try:
        result = client.chat(
            [
                {"role": "system", "content": block},
                {"role": "user", "content": _STYLE_RULES + text},
            ],
            max_tokens=min(600, max(120, len(text) // 2)),
            temperature=0.6,
            top_p=0.9,
            stream=False,
        )
        styled = (getattr(result, "text", None) or "").strip()
    except Exception:  # noqa: BLE001 — voice is optional, the answer is not
        return answer
    # Sanity: an empty or absurdly inflated rewrite means the filter
    # misbehaved — keep the original.
    if not styled or len(styled) > max(len(text) * 2, 400):
        return answer
    return styled


__all__ = ["apply_persona_voice", "filter_enabled", "DEFAULT_MAX_CHARS"]
