"""Lead triage: which standing specialist a conversation belongs to.

Coded and conservative (Claude Code / Agents-SDK style handoff, owner in the
loop): the lead keeps the conversation and records a *suggestion*; the owner
accepts it from the chat header ("Hand off to …"), which is the override path.
Nothing is moved automatically, because a specialist turn is model-only and a
silent move would take tools away from a request that needs them.
"""
from __future__ import annotations

import re

from jaeger_ai.core.agent_registry.specialists import STANDING_SPECIALISTS

_WORD = re.compile(r"[a-z0-9]+(?:[ -][a-z0-9]+)?")


def suggest_specialist(text: str) -> str | None:
    """Agent id of the one specialist whose keywords clearly match, else None."""
    low = f" {str(text or '').lower()} "
    scores: dict[str, int] = {}
    for spec in STANDING_SPECIALISTS:
        hits = sum(1 for kw in spec.get("keywords", ()) if re.search(rf"\b{re.escape(kw)}\b", low))
        if hits:
            scores[f"native:{spec['name']}"] = hits
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None  # ambiguous: the lead keeps it
    return ranked[0][0]
