"""Farewell detection — end-of-conversation heuristic (VoiceLLM port).

Field problem this solves: after "good night", the follow-up window
re-opened and ambient noise got transcribed + burned an LLM turn just
to be ignored. When the user says farewell AND the assistant's reply
acknowledges it, the voice loop suppresses the follow-up window — STT
stays on, but the robot stops soliciting a reply into an empty room.

BOTH sides must mirror before the conversation counts as closed: a
stray "goodbye" inside a story must not close the loop.
"""

from __future__ import annotations

import re

_FAREWELL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\bgood\s*night\b",
        r"\bg'?night\b",
        r"\bgood\s*bye\b",
        r"\bbye+\b",
        r"\bbye-?bye\b",
        r"\bsee\s+you(\s+(later|tomorrow|soon|then))?\b",
        r"\bsee\s+ya\b",
        r"\bcatch\s+you\s+later\b",
        r"\btalk\s+to\s+you\s+later\b",
        r"\bttyl\b",
        r"\bsleep\s+well\b",
        r"\bhave\s+a\s+good\s+(day|night|evening|one|weekend)\b",
        r"\bfarewell\b",
        r"\btake\s+care\b",
        r"\buntil\s+next\s+time\b",
        r"\bsigning\s+off\b",
    )
]


def is_farewell(text: str) -> bool:
    """True when ``text`` reads as a goodbye. Used on BOTH the user's
    phrase and the assistant's reply — only the mirrored pair closes
    the conversation."""
    return bool(text) and any(p.search(text) for p in _FAREWELL_PATTERNS)


__all__ = ["is_farewell"]
