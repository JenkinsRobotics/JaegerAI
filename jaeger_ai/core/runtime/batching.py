"""Asking the model to batch independent tool calls.

The runtime half of parallel dispatch is already built and matches
Hermes: the loop's ``_batch_is_parallel_safe`` admits a batch when every
call is a read or a path-scoped file op and no two conflict, then runs
it on a pool. What was missing is upstream — nothing ever asked the
model to EMIT a batch, so the machinery mostly had one call at a time to
work with.

This is the missing sentence, and it is deliberately gated rather than
always-on, for a reason the project already measured: added system-prompt
text costs the small local models points. ``agentic_runners.md`` records
a planning gate that regressed E4B from 73 to 66 and was reverted. A
batching instruction is much lighter than a planning gate, but it is the
same class of change — instructions aimed at a model that improvises
well and follows procedure badly.

So the guidance follows the brain, like everything else in this program:

  * a brain that **serializes decode** (in-process llama.cpp / MLX) does
    not get it by default. Parallel dispatch saves wall-clock there only
    on the non-model part of tool work, so the upside is small and the
    prompt-regression risk is exactly where it has been measured before;
  * a **server or cloud** brain gets it. Those models follow batching
    instructions reliably, their tool calls really do run concurrently,
    and each avoided round-trip also avoids re-sending the conversation.

``JAEGER_BATCH_GUIDANCE`` forces it either way — ``1`` to bench the
local case, ``0`` to rule it out while bisecting a regression.
"""

from __future__ import annotations

import os
from typing import Any

BATCH_GUIDANCE = (
    "PARALLEL TOOL CALLS: when several tool calls are independent — "
    "reading different files, checking several things at once — emit "
    "them together in ONE message instead of one per turn. They run "
    "concurrently and you get all the results back at once. Keep calls "
    "separate when one depends on another's result, and when writing to "
    "a path something else in the batch reads."
)


def _override() -> bool | None:
    raw = os.environ.get("JAEGER_BATCH_GUIDANCE", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def guidance_enabled(profile: Any) -> bool:
    """Whether to spend prompt tokens asking this brain to batch."""
    override = _override()
    if override is not None:
        return override
    if not bool(getattr(profile, "parallel_tools", True)):
        return False
    return not bool(getattr(profile, "serializes_decode", True))


def batch_guidance_block(profile: Any = None) -> str:
    """The guidance for this brain, or ``""`` when it should not get it.

    Empty string rather than None so the caller can concatenate without
    a branch — an absent block costs nothing and changes no bytes of a
    prompt that would otherwise be prefix-cache stable.
    """
    if profile is None:
        from jaeger_ai.core.models.brain_profile import active_profile

        profile = active_profile()
    return BATCH_GUIDANCE if guidance_enabled(profile) else ""


__all__ = ["BATCH_GUIDANCE", "batch_guidance_block", "guidance_enabled"]
