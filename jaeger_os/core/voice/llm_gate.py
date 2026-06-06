"""LLM-gated speech parser — companion to ``rules.VOICE_LLM_GATE_RULE``.

When the operator turns on ``config.voice.llm_gate``, the system prompt
instructs the agent to begin every reply with ``<ignore>`` or
``<reply>``.  This module parses the agent's response to decide whether
the voice loop should speak it.

The parse is intentionally lenient
-----------------------------------
A missing tag defaults to **speak** rather than silence.  Reason: an
agent that occasionally forgets the protocol is far less surprising
to the operator than one that silently swallows a valid reply.  The
operator can always tighten the system prompt rule, but they can't
recover a reply the voice loop never spoke.

Pattern source
--------------
Adopted from VoiceLLM's orchestrator gate, see
``dev_docs/library_review/voicellm.md``.
"""

from __future__ import annotations

import re


GATE_IGNORE = "ignore"
GATE_REPLY = "reply"

# Leading ``<ignore>`` or ``<reply>`` — case-insensitive, allows
# preceding whitespace + a few common punctuation runs the model
# might emit before the tag.  The capture group is the tag name
# (lowercase, normalised by the parser).
_GATE_RE = re.compile(
    r"^\s*<\s*(ignore|reply)\s*>\s*",
    re.IGNORECASE,
)


def parse_gate(text: str | None) -> tuple[bool, str]:
    """Return ``(should_speak, cleaned_text)``.

    - ``<ignore>...``  → ``(False, "")``  (any text after the tag is
      dropped — the rule says ``<ignore>`` means no further output;
      we don't speak whatever else the model emitted)
    - ``<reply>X``     → ``(True, "X")``  (tag stripped, rest spoken)
    - no tag           → ``(True, text)`` (lenient default — speak)
    - ``None`` / empty → ``(False, "")``  (nothing to speak)

    The lenient default is deliberate; see the module docstring.
    """
    if not text:
        return False, ""
    m = _GATE_RE.match(text)
    if not m:
        return True, text
    tag = m.group(1).lower()
    rest = _GATE_RE.sub("", text, count=1).strip()
    if tag == GATE_IGNORE:
        return False, ""
    # ``<reply>`` — speak the remainder
    return True, rest
