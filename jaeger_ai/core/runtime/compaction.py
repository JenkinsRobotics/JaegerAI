"""Who writes the compaction digest — and whether this lane can afford it.

When the context guard has to drop old turns, it folds them into a
digest rather than letting them vanish (see
:mod:`jaeger_agent.util.context_guard`). That digest has two authors:

  * the **deterministic** one — user asks, tools used, errors seen,
    assembled from the dropped messages with no model call. Free,
    sub-millisecond, and lossy in a predictable way.
  * the **LLM-written** one — a bounded model call that compresses the
    span into prose. Better recall of decisions and open threads, at
    the cost of one call.

This module owns the two questions the choice turns on: *who can pay*,
and *how the call is made on this brain*.

**Who can pay** used to be answered by ``key.startswith("deepthink")`` —
a string test on the session key. The intent was right (background work
is latency-free, so the call is free there) but the reasoning was the
LOCAL brain's: an in-process model has ONE decode lane, so a compaction
call blocks the turn behind it for seconds. On a server or cloud brain
the call overlaps with nothing and returns in a round-trip, so the
latency argument that justifies the cheap digest simply does not apply.
Same shape as the subagent-concurrency leak: a local cost written down
as a universal rule. :func:`llm_digest_enabled` asks the brain instead.

**How the call is made** is already brain-agnostic and needs no branch
here: ``client.chat()`` is the two-host contract. On an in-process model
it runs on the AUX LANE — a second ``llama_context`` over the same
weights, which cannot evict the worker's warm KV prefix (the whole
reason that lane exists). On an external client it is a second HTTP
request. One call, two very different mechanisms, and this module does
not need to know which it got.
"""

from __future__ import annotations

import os
from typing import Any, Callable

# Session keys that are background work by construction — no one is
# waiting on the turn, so the better digest is always worth its call.
_BACKGROUND_PREFIXES = ("deepthink", "daemon", "cron", "review")

# Bounds for the digest call. Small on purpose: this is a compression
# pass, and a digest that grows toward the span it replaced has failed
# at its job.
_DIGEST_MAX_TOKENS = 400
_DIGEST_TEMPERATURE = 0.2

_DIGEST_SYSTEM = (
    "You compress agent conversation history into a dense factual "
    "digest. Output ONLY the digest."
)


def _flag(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def is_background_session(session_key: str) -> bool:
    """Whether ``session_key`` names work nobody is waiting on."""
    key = str(session_key or "").strip().lower()
    return key.startswith(_BACKGROUND_PREFIXES)


def llm_digest_enabled(profile: Any, session_key: str = "") -> bool:
    """Should this lane pay for an LLM-written digest?

    Yes when either is true:

      * the session is **background work** — deep think, the daemon, a
        scheduled prompt, a review sweep. Nobody is waiting, so the
        call is free on any brain.
      * the brain **does not serialize decode** — a server or cloud
        lane, where the call overlaps other work and costs a round-trip
        rather than blocking the one decode loop. Compaction only fires
        when the window is genuinely full, and on that turn a second of
        latency buys back history that would otherwise be dropped.

    An in-process model in an interactive session gets the
    deterministic digest: there, the call is seconds long AND holds the
    only decode lane, which is exactly the cost the voice path cannot
    absorb.

    ``JAEGER_LLM_DIGEST`` overrides in both directions — ``0`` forces
    the deterministic digest everywhere, ``1`` forces the LLM digest
    everywhere.
    """
    override = _flag("JAEGER_LLM_DIGEST")
    if override in {"0", "false", "no", "off"}:
        return False
    if override in {"1", "true", "yes", "on"}:
        return True

    if is_background_session(session_key):
        return True
    return not bool(getattr(profile, "serializes_decode", True))


def _result_text(result: Any) -> str:
    """The text out of whatever ``client.chat()`` returned.

    Every client returns a small result OBJECT — ``_ChatResult`` for the
    local lanes, ``ExtChatResult`` for external — never a bare string.
    Passing one to ``str()`` yields its dataclass repr, so the digest
    that reached the transcript read
    ``ExtChatResult(text='…', latency_s=0.4, ttft_s=0.0)``: the summary
    was in there, wrapped in Python syntax, eating the digest's
    character cap. Read ``.text``; accept a plain string too, so a
    future client that returns one still works.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


def make_summarizer(client: Any) -> Callable[[str], str]:
    """A digest writer bound to ``client``.

    The returned callable takes the guard's assembled prompt and returns
    digest text — ``""`` on any failure, because the guard falls back to
    the deterministic digest and compaction must never break a turn over
    a summarizer hiccup.
    """

    def _summarize(prompt_text: str) -> str:
        try:
            result = client.chat(
                [
                    {"role": "system", "content": _DIGEST_SYSTEM},
                    {"role": "user", "content": prompt_text},
                ],
                max_tokens=_DIGEST_MAX_TOKENS,
                temperature=_DIGEST_TEMPERATURE,
            )
        except Exception:  # noqa: BLE001 — the deterministic digest stands in
            return ""
        return _result_text(result)

    return _summarize


def summarizer_for(client: Any, session_key: str = "", profile: Any = None) -> Any:
    """The summarizer to hand :func:`build_jaeger_agent`, or ``None``.

    ``None`` means "use the deterministic digest" — the guard's default,
    and a valid answer rather than a degraded one.
    """
    if client is None:
        return None
    if profile is None:
        from jaeger_ai.core.models.brain_profile import profile_for

        profile = profile_for(client)
    if not llm_digest_enabled(profile, session_key):
        return None
    return make_summarizer(client)


__all__ = [
    "is_background_session",
    "llm_digest_enabled",
    "make_summarizer",
    "summarizer_for",
]
