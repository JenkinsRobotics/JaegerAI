"""LLM → animation command parser.

The LLM emits structured tags inside its free-text reply so the
animation node can play the right clip without changing the
existing chat-reply channel.

Supported wire forms (all case-insensitive on the tag name):

    Sure! <play name="happy_blink"/> Hope that helps.
    <play>angry_punch</play> Take that.
    [play:idle]  ← bracket form for ultra-terse outputs
    <mode name="rainbow"/>  ← set persistent mode (vs. one-shot play)
    <stop/>                  ← stop whatever's currently playing

The parser is intentionally LENIENT — it ignores malformed tags
rather than rejecting the whole reply.  The LLM is allowed to
"mostly" follow the protocol; we extract what we can.

Returns a list of :class:`AnimationCommand` so the caller can
dispatch them in order, or coalesce (e.g. the last `<play>` wins
when several appear in one reply).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class AnimationCommand:
    """One parsed command extracted from an LLM reply."""
    verb: str               # "play" | "mode" | "stop"
    name: str = ""          # the animation name (empty for "stop")
    raw: str = ""           # the original matched fragment (for debug)


# ── regex patterns ───────────────────────────────────────────────
#
# Order matters: more specific shapes first, since findall doesn't
# back-track between patterns.

_TAG_PATTERNS: list[tuple[re.Pattern, str]] = [
    # <play name="X"/> or <play name='X'/> with optional whitespace.
    # The backreference forces matching quote pairs; newlines inside
    # the name are rejected.  The name is always the LAST group.
    (re.compile(
        r'<(play|mode)\s+name\s*=\s*(["\'])([^"\'\n]+)\2\s*/?>',
        re.IGNORECASE,
    ), "name-attribute"),
    # <play>X</play> with body text
    (re.compile(
        r'<(play|mode)\s*>\s*([^<\n]+?)\s*</\s*\1\s*>',
        re.IGNORECASE,
    ), "body-text"),
    # [play:X] — bracket form
    (re.compile(
        r'\[(play|mode)\s*:\s*([^\]\n]+?)\s*\]',
        re.IGNORECASE,
    ), "bracket"),
]

# Standalone stop tag (no name argument).
_STOP_PATTERN = re.compile(
    r'<stop\s*/?>|\[stop\]',
    re.IGNORECASE,
)


def parse(reply: str) -> list[AnimationCommand]:
    """Extract every animation command in ``reply``.

    Order is preserved (first occurrence first).  Duplicate commands
    are returned as-is — the caller decides whether to coalesce.
    """
    if not reply:
        return []

    commands: list[tuple[int, AnimationCommand]] = []

    for pat, label in _TAG_PATTERNS:
        for m in pat.finditer(reply):
            verb = m.group(1).lower()
            # Every pattern puts the name in its LAST capture group.
            name = m.groups()[-1].strip()
            if not name:
                continue
            commands.append((m.start(), AnimationCommand(
                verb=verb,
                name=name,
                raw=m.group(0),
            )))

    for m in _STOP_PATTERN.finditer(reply):
        commands.append((m.start(), AnimationCommand(
            verb="stop",
            name="",
            raw=m.group(0),
        )))

    commands.sort(key=lambda pair: pair[0])
    return [cmd for _, cmd in commands]


def coalesce(commands: Iterable[AnimationCommand]) -> AnimationCommand | None:
    """When the operator wants only the FINAL intent, pick the last
    play/mode (and respect a trailing stop)."""
    last: AnimationCommand | None = None
    for cmd in commands:
        if cmd.verb in ("play", "mode", "stop"):
            last = cmd
    return last


def strip_tags(reply: str) -> str:
    """Return ``reply`` with every recognised tag removed.  Useful
    when forwarding the cleaned text to TTS so the operator hears
    "Hope that helps" instead of "Hope that helps play happy blink".
    """
    out = reply
    for pat, _ in _TAG_PATTERNS:
        out = pat.sub("", out)
    out = _STOP_PATTERN.sub("", out)
    # Collapse double spaces produced by removals.
    out = re.sub(r"  +", " ", out).strip()
    return out
