"""Single-pass structured error classification & deadline-bound jittered retries.

Synthesizes:
- hermes-agent (`error_classifier.py`): single-pass `ClassifiedError` with
  explicit action booleans (`retryable`, `should_compress`,
  `should_rotate_credential`, `should_fallback`).
- pydantic-ai (`retry_on_model_errors.py`) & gemini-cli (`retry.ts`):
  `Retry-After` header honoring, `x-should-retry` respect, and deadline-capped
  jittered exponential backoff.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from .engine import FailoverReason, classify_error

T = TypeVar("T")

# Canonical legacy-compatible error-class constants.
AUTH = "auth"
NOT_FOUND = "not_found"
QUOTA = "quota"
RATE_LIMIT = "rate_limit"
TRANSIENT = "transient"
UNKNOWN = "unknown"

_RETRYABLE = frozenset({RATE_LIMIT, TRANSIENT})


@dataclass(frozen=True)
class ClassifiedError:
    """Structured classification returned once per provider/runtime exception."""

    reason: FailoverReason
    retryable: bool
    should_compress: bool
    should_rotate_credential: bool
    should_fallback: bool
    retry_after_s: float | None = None
    provider_forbids_retry: bool = False


def _extract_retry_headers(exc: BaseException) -> tuple[float | None, bool]:
    """Read optional ``Retry-After`` and ``x-should-retry`` headers via duck typing."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else getattr(exc, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None, False
    forbid = False
    should_retry_raw = headers.get("x-should-retry") or headers.get("X-Should-Retry")
    if isinstance(should_retry_raw, str) and should_retry_raw.strip().lower() == "false":
        forbid = True
    retry_after: float | None = None
    ra_raw = headers.get("retry-after") or headers.get("Retry-After")
    if ra_raw is not None:
        try:
            retry_after = max(0.0, float(str(ra_raw).strip()))
        except ValueError:
            retry_after = None
    return retry_after, forbid


def classify_error_detailed(exc: BaseException) -> ClassifiedError:
    """Single-pass structured classification with explicit recovery booleans."""
    raw = classify_error(exc)
    reason = FailoverReason(raw)
    retry_after, forbid = _extract_retry_headers(exc)
    retryable = (not forbid) and reason in (
        FailoverReason.RATE_LIMIT,
        FailoverReason.TRANSIENT,
        FailoverReason.EMPTY_RESPONSE,
    )
    return ClassifiedError(
        reason=reason,
        retryable=retryable,
        should_compress=(reason == FailoverReason.CONTEXT_OVERFLOW),
        should_rotate_credential=(reason in (FailoverReason.AUTH, FailoverReason.QUOTA, FailoverReason.RATE_LIMIT)),
        should_fallback=(reason in (
            FailoverReason.AUTH,
            FailoverReason.QUOTA,
            FailoverReason.RATE_LIMIT,
            FailoverReason.TRANSIENT,
            FailoverReason.NOT_FOUND,
            FailoverReason.CONTEXT_OVERFLOW,
        )),
        retry_after_s=retry_after,
        provider_forbids_retry=forbid,
    )


def classify_exception(exc: BaseException) -> str:
    """Map a provider exception to AUTH / NOT_FOUND / QUOTA / RATE_LIMIT / TRANSIENT / UNKNOWN."""
    reason = classify_error(exc)
    return {
        FailoverReason.AUTH.value: AUTH,
        FailoverReason.NOT_FOUND.value: NOT_FOUND,
        FailoverReason.QUOTA.value: QUOTA,
        FailoverReason.RATE_LIMIT.value: RATE_LIMIT,
        FailoverReason.TRANSIENT.value: TRANSIENT,
    }.get(reason, UNKNOWN)


_CONTEXT_OVERFLOW_HINTS = (
    "tokens to keep",
    "context length",
    "context window",
    "exceed context window",
    "exceeds the maximum context",
    "input is too long",
)


def friendly_error_text(error: str, *, model_name: str = "") -> str:
    """Rewrite a raw model-server context overflow error into actionable advice."""
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


def friendly_overflow_text(
    *,
    estimated: int,
    budget: int,
    system_prompt_tokens: int,
    tools_tokens: int,
    latest_user_tokens: int,
) -> str:
    """Render pre-flight ContextOverflow token counts as actionable advice."""
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
    """One-line plain message for the operator — no stack trace."""
    who = provider or "the model provider"
    return {
        AUTH: f"{who} rejected the API key — check the stored credential for {who}.",
        NOT_FOUND: f"{who} has no such model — check the model id.",
        QUOTA: (
            f"{who} rejected the request — the account is out of "
            "credits/quota. Add billing or switch to a local model."
        ),
        RATE_LIMIT: f"{who} rate-limited the request and was still limited after retries.",
        TRANSIENT: f"{who} hit a transient error and did not recover after retries.",
        UNKNOWN: f"{who} call failed — {type(exc).__name__}: {exc}",
    }[classify_exception(exc)]


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    deadline_s: float | None = None,
    on_retry: Callable[[int, str, float], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call ``fn`` with deadline-bound, Retry-After-aware jittered backoff."""
    attempts = max(1, attempts)
    deadline = (clock() + deadline_s) if deadline_s is not None else None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below
            detailed = classify_error_detailed(exc)
            cls = classify_exception(exc)
            if detailed.provider_forbids_retry or cls not in _RETRYABLE or attempt >= attempts:
                raise
            if detailed.retry_after_s is not None:
                if detailed.retry_after_s > max_delay:
                    raise
                delay = detailed.retry_after_s
            else:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay = max(0.0, delay * (1.0 + random.uniform(-0.25, 0.25)))
            if deadline is not None:
                remaining = deadline - clock()
                if delay > remaining:
                    raise
            if on_retry is not None:
                try:
                    on_retry(attempt, cls, delay)
                except Exception:  # noqa: BLE001
                    pass
            sleep_fn(delay)
    raise RuntimeError("unreachable: retry_call exhausted without raising")


__all__ = [
    "AUTH",
    "NOT_FOUND",
    "QUOTA",
    "RATE_LIMIT",
    "TRANSIENT",
    "UNKNOWN",
    "ClassifiedError",
    "classify_error_detailed",
    "classify_exception",
    "friendly_error_text",
    "friendly_message",
    "friendly_overflow_text",
    "retry_call",
]
