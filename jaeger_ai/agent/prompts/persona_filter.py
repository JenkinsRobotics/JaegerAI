"""Station 3 — the persona output filter (dev/docs/reality/agentic_runners.md).

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
import re
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
    "- Keep EVERY piece of information, suggestion, and question from the "
    "reply. Dropping content is failure.\n"
    "- If the reply IS the deliverable — a joke, story, poem, quote, or "
    "list — deliver it intact in your voice: restyle the framing, never "
    "replace, analyze, or explain the content.\n"
    "- ADD NOTHING: no remarks, jabs, lectures, or commentary of your own. "
    "Your character shows in HOW things are said, never in extra sentences. "
    "Never be rude to the user.\n"
    "- Same language as the reply. Similar length (never more than ~30% "
    "longer).\n"
    "- Plain terminal text: no markdown emphasis.\n"
    "- Output ONLY the rewritten reply — no preamble, no quotes.\n\n"
    "REPLY TO REWRITE:\n"
)

# Content-survival guard: stopword-stripped content-word overlap between the
# original answer and the styled rewrite. This is the mechanical enforcement
# of "losing voice is acceptable; losing the answer is not" — a rewrite can
# change every word's clothing but not swap the content for commentary about
# the content (the "Lilith turns a joke into meta-analysis" bug).
_OVERLAP_THRESHOLD = 0.5

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "at", "by", "for", "with", "about", "as", "into", "like",
    "through", "after", "over", "between", "out", "against", "during",
    "without", "before", "under", "around", "among", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "you", "your", "yours", "i", "me", "my", "mine", "we", "our",
    "ours", "he", "she", "they", "them", "him", "his", "her", "hers",
    "their", "theirs", "not", "no", "nor", "do", "does", "did", "so",
    "than", "too", "very", "can", "will", "just", "should", "would",
    "could", "up", "down", "off", "again", "further", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "only", "own", "same",
    "from", "have", "has", "had", "who", "whom", "which", "what", "because",
    "sir", "ma'am", "dear", "indeed", "ah", "oh", "well", "truly", "quite",
})

# Tokens: word characters plus internal ./:-_@ so file paths, URLs, emails,
# and version numbers survive as single content tokens rather than being
# shredded into meaningless fragments.
_WORD_RE = re.compile(r"[a-z0-9](?:[a-z0-9_./:@-]*[a-z0-9])?", re.IGNORECASE)


def _content_words(text: str) -> set[str]:
    """Lowercase, tokenize, and drop stopwords/short filler — but numbers,
    paths, and names (any token carrying a digit) always count, per the
    contract that they must survive VERBATIM."""
    words = _WORD_RE.findall(text.lower())
    out: set[str] = set()
    for word in words:
        if any(ch.isdigit() for ch in word):
            out.add(word)
            continue
        if len(word) < 3 or word in _STOPWORDS:
            continue
        out.add(word)
    return out


def _preserves_content(original: str, styled: str) -> bool:
    """True if ``styled`` retains at least ``_OVERLAP_THRESHOLD`` of the
    original's content words. A restyle may reword freely; it may not
    replace the substance with commentary/analysis about the substance."""
    orig_words = _content_words(original)
    if not orig_words:
        return True
    styled_words = _content_words(styled)
    overlap = len(orig_words & styled_words) / len(orig_words)
    return overlap >= _OVERLAP_THRESHOLD


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
            temperature=0.3,
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
    # Content-survival guard: a rewrite that lost the substance (mangled
    # into analysis/commentary, or dropped facts) is worse than no rewrite.
    if not _preserves_content(text, styled):
        return answer
    return styled


__all__ = [
    "apply_persona_voice",
    "filter_enabled",
    "DEFAULT_MAX_CHARS",
    "_content_words",
    "_preserves_content",
]
