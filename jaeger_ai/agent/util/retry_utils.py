"""Retry utilities — jittered backoff for decorrelated retries.

Replaces naive fixed exponential backoff with jittered delays so
multiple concurrent sessions hitting the same rate-limited provider
don't all retry at the same instant (thundering-herd avoidance).

Use case in JROS:
  • Per-tool retry policies (transient HTTP 429 / 502 / timeouts)
  • Adapter-level credential rotation pauses
  • Background-job rescheduling after transient failures

Ported from :mod:`python_hermes_agent.upstream.agent.retry_utils` —
the algorithm is small enough that we keep our own copy rather than
import from the upstream package (whose internals churn).
"""

from __future__ import annotations

import random
import threading
import time


# Monotonic per-process counter for jitter-seed uniqueness. Multiple
# threads / coroutines retrying simultaneously increment this so each
# computes a different seed from a clock that may not have updated
# between back-to-back calls.
_jitter_counter = 0
_jitter_lock = threading.Lock()


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """Compute a jittered exponential-backoff delay in seconds.

    ``min(base * 2^(attempt-1), max_delay) + uniform(0, jitter_ratio *
    delay)``. The jitter range decorrelates concurrent retries; the
    cap prevents catastrophic stalls on a permanently-down provider.

    Args:
        attempt: 1-based retry attempt number. Attempt 1 = ``base_delay``
            (plus jitter); attempt 2 = ``2 * base_delay``; etc.
        base_delay: Seconds for attempt 1's pre-jitter delay.
        max_delay: Cap. Past this, all attempts share the same
            pre-jitter delay (only the jitter portion still varies).
        jitter_ratio: Fraction of the computed delay used as the
            jitter range. ``0.5`` means jitter is uniform in
            ``[0, 0.5 * delay]`` — the default that worked well for
            Hermes' multi-session scenarios.

    Returns:
        Delay in seconds. Always ≥ 0; never NaN/inf.
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    # Guard against absurd attempts that would overflow ``2**N``.
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    # Seed from monotonic-counter XOR'd with the clock so coarse-clock
    # systems still produce distinct seeds for back-to-back calls.
    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)
    return delay + jitter


def retry_with_backoff(
    fn,
    *,
    max_attempts: int = 3,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    on_retry=None,
):
    """Call ``fn()``; on exception in ``retry_on``, sleep
    :func:`jittered_backoff` and retry. Returns ``fn``'s result on
    success; re-raises the last exception after ``max_attempts``.

    ``on_retry(attempt, exception, delay)`` (optional) fires before
    each retry sleep so callers can log / surface to the TUI / fire a
    metric. Exceptions inside ``on_retry`` are swallowed.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retry_on as exc:  # noqa: BLE001 — explicit allowlist
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = jittered_backoff(
                attempt, base_delay=base_delay, max_delay=max_delay,
            )
            if on_retry is not None:
                try:
                    on_retry(attempt, exc, delay)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(delay)
    # Past the loop: exhausted attempts.
    assert last_exc is not None
    raise last_exc


__all__ = ["jittered_backoff", "retry_with_backoff"]
