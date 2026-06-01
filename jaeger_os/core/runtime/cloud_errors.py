"""Cloud-provider error classification + jittered retry (audit A8).

JROS now runs on cloud brains — ``ollama-cloud``, ``openai``,
``anthropic``, ``gemini`` (see ``external_model.py`` / audit B2). When
one of those calls fails, the vendor SDK surfaces a raw exception with
no classification: the agent — and the user — cannot tell a bad API key
from a transient 500 from a rate-limit-retry-in-30s.

This module maps a provider exception to a small, *actionable* taxonomy
and gives a jittered-backoff retry for the failures worth retrying. It is
deliberately SDK-agnostic — it classifies by HTTP status and
exception-class name via duck-typed attributes, so it never imports
``openai`` / ``anthropic`` / ``requests``.

Folds in audit A7 (jittered backoff) — ``retry_call`` is that helper.
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Error classes — what the agent should DO about a failure.
AUTH = "auth"              # bad / missing / revoked key — stop, tell the user
NOT_FOUND = "not_found"    # wrong model id — stop, tell the user
RATE_LIMIT = "rate_limit"  # 429 — back off and retry
TRANSIENT = "transient"    # 5xx / connection / timeout — retry
UNKNOWN = "unknown"        # unclassified — surface as-is, do not spin

# Classes worth retrying — the rest are pointless to repeat.
_RETRYABLE = frozenset({RATE_LIMIT, TRANSIENT})


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an arbitrary provider exception."""
    for attr in ("status_code", "status", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int) and 100 <= v <= 599:
            return v
    # openai / httpx nest the status on a `.response` object.
    resp = getattr(exc, "response", None)
    if resp is not None:
        v = getattr(resp, "status_code", None)
        if isinstance(v, int) and 100 <= v <= 599:
            return v
    return None


def classify_exception(exc: BaseException) -> str:
    """Map a provider exception to AUTH / NOT_FOUND / RATE_LIMIT /
    TRANSIENT / UNKNOWN — by HTTP status and exception-class name."""
    name = type(exc).__name__.lower()
    status = _status_of(exc)

    if status in (401, 403) or "authenticat" in name or "permissiondenied" in name:
        return AUTH
    if status == 404 or "notfound" in name:
        return NOT_FOUND
    if status == 429 or "ratelimit" in name:
        return RATE_LIMIT
    if (status is not None and status >= 500) or any(
        k in name for k in (
            "timeout", "connection", "apiconnection", "serviceunavailable",
            "overloaded", "internalserver", "badgateway",
        )
    ):
        return TRANSIENT
    return UNKNOWN


# Match the LMStudio / llama.cpp-server 400 we keep hitting: the loaded
# context is smaller than the prompt the agent assembled. The raw error
# (status_code: 400, model_name: …, body: "The number of tokens to keep
# from the initial prompt is greater than the context length. …") is
# opaque — surface a clear, server-side fix.
_CONTEXT_OVERFLOW_HINTS = (
    "tokens to keep",
    "context length",
    "context window",
    "exceed context window",
    "exceeds the maximum context",
    "input is too long",
)


def friendly_error_text(error: str, *, model_name: str = "") -> str:
    """Rewrite a raw model-server error message into a one-screen,
    actionable hint when we recognise it. Returns ``error`` unchanged for
    anything we don't know how to improve.

    Today this catches one big offender: the LMStudio 400 that fires when
    the loaded model's context is smaller than the prompt. Jaeger's status
    bar shows its *local* ctx (``config.model.ctx``); LMStudio carries its
    own per-load ctx and the two need to match.
    """
    text = (error or "").lower()
    if not any(needle in text for needle in _CONTEXT_OVERFLOW_HINTS):
        return error
    who = model_name or "the loaded model"
    return (
        f"The model server loaded {who} with a context smaller than the "
        "prompt needs.\n\n"
        "Fix on the server side:\n"
        "  • LMStudio — eject the model, then reload it and set Context "
        "Length to at least 16384 (match config.model.ctx).\n"
        "  • Ollama   — bump num_ctx in the model's Modelfile, or set the "
        "OLLAMA_NUM_CTX environment variable.\n\n"
        "Jaeger's status bar shows its OWN ctx setting; the server has its "
        "own — the two have to match for a turn to fit.\n\n"
        f"Raw error: {error}"
    )


def friendly_overflow_text(*,
                           estimated: int, budget: int,
                           system_prompt_tokens: int, tools_tokens: int,
                           latest_user_tokens: int) -> str:
    """Render the pre-flight :class:`ContextOverflow` from
    :mod:`jaeger_os.agent.util.context_guard` as actionable advice.

    Parallel to :func:`friendly_error_text` (which catches the *reactive*
    side — the server's 400 after we sent too much) but fired *before*
    any network call. The numbers are exact, so we can show the operator
    where their tokens went."""
    return (
        "Refused to send: this turn's prompt won't fit Jaeger's context "
        f"budget ({budget} tokens of usable prompt room).\n\n"
        f"  prompt estimate:   ~{estimated} tokens\n"
        f"  system prompt:     ~{system_prompt_tokens} tokens\n"
        f"  tool schemas:      ~{tools_tokens} tokens\n"
        f"  latest user msg:   ~{latest_user_tokens} tokens\n\n"
        "Fix one of:\n"
        "  • Raise config.model.ctx (and reload the model on the server "
        "    so its loaded ctx matches — LMStudio 'Context Length', "
        "    Ollama 'num_ctx').\n"
        "  • Send a shorter message, or break the request into steps.\n"
        "  • Narrow the active toolsets — the tool-schema JSON itself is "
        "    a few thousand tokens with all toolsets active."
    )


def friendly_message(exc: BaseException, *, provider: str = "") -> str:
    """A one-line, plain message for the agent / user — no stack trace."""
    who = provider or "the model provider"
    return {
        AUTH: f"{who} rejected the API key — check the stored credential "
              f"for {who}.",
        NOT_FOUND: f"{who} has no such model — check the model id.",
        RATE_LIMIT: f"{who} rate-limited the request and was still limited "
                    f"after retries.",
        TRANSIENT: f"{who} hit a transient error and did not recover after "
                   f"retries.",
        UNKNOWN: f"{who} call failed — {type(exc).__name__}: {exc}",
    }[classify_exception(exc)]


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    on_retry: Callable[[int, str, float], None] | None = None,
) -> T:
    """Call ``fn`` with jittered exponential backoff.

    Retries only RATE_LIMIT / TRANSIENT failures (up to ``attempts``
    total tries). AUTH / NOT_FOUND / UNKNOWN are re-raised immediately —
    retrying a bad key just wastes the user's time. The exception from
    the final attempt propagates. ``on_retry(attempt, error_class,
    delay)`` is an optional progress hook (e.g. a TUI status line)."""
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below
            cls = classify_exception(exc)
            if cls not in _RETRYABLE or attempt >= attempts:
                raise
            # base * 2^(n-1), ±25% jitter, capped at max_delay.
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = max(0.0, delay * (1.0 + random.uniform(-0.25, 0.25)))
            if on_retry is not None:
                try:
                    on_retry(attempt, cls, delay)
                except Exception:  # noqa: BLE001 — a hook must never break retry
                    pass
            time.sleep(delay)
    raise RuntimeError("unreachable: retry_call exhausted without raising")


__all__ = [
    "AUTH", "NOT_FOUND", "RATE_LIMIT", "TRANSIENT", "UNKNOWN",
    "classify_exception", "friendly_message", "retry_call",
]
