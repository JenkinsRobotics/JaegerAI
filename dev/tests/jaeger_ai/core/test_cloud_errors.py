"""Cloud-provider error classification + jittered retry (audit A8).

`core/cloud_errors.py` maps a raw provider exception to an actionable
class (auth / not_found / rate_limit / transient / unknown) and retries
only the ones worth retrying — SDK-agnostic, by HTTP status and class
name. These tests use fake exception classes so no real SDK is needed.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime.cloud_errors import (
    AUTH,
    NOT_FOUND,
    QUOTA,
    RATE_LIMIT,
    TRANSIENT,
    UNKNOWN,
    classify_exception,
    friendly_message,
    retry_call,
)


# ── fake provider exceptions ────────────────────────────────────────


class _Status(Exception):
    """An exception carrying an HTTP status, like the vendor SDKs do."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


class RateLimitError(Exception):       # classified by class name
    pass


class AuthenticationError(Exception):  # classified by class name
    pass


class APIConnectionError(Exception):   # classified by class name
    pass


# ── classify_exception ──────────────────────────────────────────────


@pytest.mark.parametrize("status,expected", [
    (401, AUTH),
    (403, AUTH),
    (404, NOT_FOUND),
    (429, RATE_LIMIT),
    (500, TRANSIENT),
    (503, TRANSIENT),
])
def test_classify_by_http_status(status, expected):
    assert classify_exception(_Status(status)) == expected


def test_classify_by_class_name():
    assert classify_exception(RateLimitError()) == RATE_LIMIT
    assert classify_exception(AuthenticationError()) == AUTH
    assert classify_exception(APIConnectionError()) == TRANSIENT


def test_classify_unknown_falls_through():
    assert classify_exception(ValueError("something odd")) == UNKNOWN


def test_classify_quota_beats_rate_limit_on_a_429():
    """OpenAI returns 429 for BOTH a too-fast burst and an empty wallet.
    An ``insufficient_quota`` 429 is QUOTA (don't retry), not RATE_LIMIT."""
    class _Quota(Exception):
        status_code = 429
        code = "insufficient_quota"
    assert classify_exception(_Quota()) == QUOTA
    # body-dict shape (OpenAI SDK) classifies too.
    class _Body(Exception):
        status_code = 429
        body = {"error": {"code": "insufficient_quota"}}
    assert classify_exception(_Body()) == QUOTA
    # a plain 429 with no quota marker is still a rate limit.
    assert classify_exception(_Status(429)) == RATE_LIMIT


def test_quota_is_not_retried():
    """A credit-exhausted account won't recover on a backoff — re-raise."""
    calls = {"n": 0}
    class _Quota(Exception):
        status_code = 402
    def fn():
        calls["n"] += 1
        raise _Quota()
    with pytest.raises(_Quota):
        retry_call(fn, attempts=3, base_delay=0.0)
    assert calls["n"] == 1  # no retries


def test_classify_reads_status_off_a_response_object():
    class _Resp:
        status_code = 429

    class _Wrapped(Exception):
        response = _Resp()

    assert classify_exception(_Wrapped()) == RATE_LIMIT


# ── friendly_message ────────────────────────────────────────────────


def test_friendly_message_names_the_provider_and_cause():
    msg = friendly_message(_Status(401), provider="gemini")
    assert "gemini" in msg
    assert "key" in msg.lower()
    assert "Traceback" not in msg


# ── retry_call ──────────────────────────────────────────────────────


def test_retry_call_retries_transient_then_succeeds():
    calls = {"n": 0}

    def _flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Status(503)        # transient
        return "ok"

    assert retry_call(_flaky, base_delay=0.001) == "ok"
    assert calls["n"] == 3


def test_retry_call_does_not_retry_auth():
    calls = {"n": 0}

    def _bad_key() -> str:
        calls["n"] += 1
        raise _Status(401)            # auth — pointless to retry

    with pytest.raises(_Status):
        retry_call(_bad_key, base_delay=0.001)
    assert calls["n"] == 1            # tried exactly once


def test_retry_call_gives_up_after_attempts():
    calls = {"n": 0}

    def _always_down() -> str:
        calls["n"] += 1
        raise _Status(500)            # transient, but never recovers

    with pytest.raises(_Status):
        retry_call(_always_down, attempts=3, base_delay=0.001)
    assert calls["n"] == 3            # exhausted the attempt budget


def test_retry_call_fires_the_on_retry_hook():
    seen: list[tuple[int, str]] = []

    def _flaky() -> str:
        if len(seen) < 2:
            raise _Status(429)
        return "done"

    retry_call(
        _flaky, base_delay=0.001,
        on_retry=lambda attempt, cls, delay: seen.append((attempt, cls)),
    )
    assert seen == [(1, RATE_LIMIT), (2, RATE_LIMIT)]


# ── friendly_error_text — surface a clear hint for the LMStudio 400 ────


def test_friendly_error_text_rewrites_context_length_400():
    """The LMStudio HTTP 400 that fires when the loaded ctx is smaller
    than the prompt — a recurring footgun — should turn into an
    actionable hint instead of being shown verbatim."""
    from jaeger_ai.core.runtime.cloud_errors import friendly_error_text

    raw = ("status_code: 400, model_name: gemma-4-26b-a4b, body: The "
           "number of tokens to keep from the initial prompt is greater "
           "than the context length. Try to load the model with a larger "
           "context length, or provide a shorter input")
    out = friendly_error_text(raw, model_name="gemma-4-26b-a4b")
    assert "gemma-4-26b-a4b" in out
    assert "LMStudio" in out
    assert "16384" in out
    # The original message stays attached so the user still sees the raw one.
    assert raw in out


def test_friendly_error_text_passes_unknown_errors_through():
    from jaeger_ai.core.runtime.cloud_errors import friendly_error_text

    raw = "some other random error — definitely not about context"
    assert friendly_error_text(raw) == raw


def test_friendly_error_text_matches_alternate_phrasings():
    from jaeger_ai.core.runtime.cloud_errors import friendly_error_text
    for needle in (
        "exceeds the maximum context",
        "exceed context window",
        "input is too long",
    ):
        rewritten = friendly_error_text(f"...{needle}...")
        assert "server side" in rewritten
