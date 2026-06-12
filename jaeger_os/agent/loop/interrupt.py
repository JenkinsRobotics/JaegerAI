"""Interruptible call primitive + liveness instrumentation.

The agent loop must be cancellable mid-flight — today for Ctrl-C and
voice barge-in, later for the operator pressing E-stop on a robot. The
HTTP / network call inside an adapter cannot be cancelled cleanly from
outside (SDK clients don't expose cancellation hooks consistently), so
the proven pattern — used verbatim in hermes-agent and elsewhere — is:
run the call on a daemon thread, poll an ``Event``, abandon the thread
if the event fires. The thread cleans itself up when the underlying
socket eventually closes or times out; the user sees an immediate
return.

Phase-8 additions:

  • **Stale-call detector** — when a non-streaming HTTP request hangs
    silently (the provider's TCP socket open, but no bytes flowing),
    we'd previously wait the full SDK ``timeout`` (often 600s) before
    surfacing it. The detector raises ``StaleCallTimeout`` after
    ``stale_timeout`` seconds so the agent's adapter-fallback chain or
    a higher-level retry policy can react fast.

  • **Activity heartbeat** — the optional ``on_heartbeat`` callback
    fires every ``poll_interval`` seconds while the wrapped call is
    in flight. The TUI status bar reads this to surface
    "still waiting on the model (12 s elapsed)…" instead of looking
    frozen, and the gateway uses the same hook to keep its
    inactivity-watchdog awake during long generations.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


class AgentInterrupted(Exception):
    """Raised by :func:`interruptible_call` when the interrupt event
    fires before the wrapped call returns. Carries the agent up out of
    the loop so ``JaegerAgent.run_turn`` can bail cleanly."""


class StaleCallTimeout(Exception):
    """Raised by :func:`interruptible_call` when no progress was made
    for ``stale_timeout`` seconds. Distinct from ``AgentInterrupted``
    so the loop's adapter-fallback chain can retry on a sibling
    backend instead of treating it like a user cancel."""


class CallProgress:
    """Worker-side progress beacon for the stale detector.

    Without one of these, ``interruptible_call`` can only measure
    *total elapsed time* — which falsely kills long-but-healthy
    generations (a 4K-token answer takes minutes on a slow backend).
    An adapter that can observe progress (a streamed chunk arriving,
    a token decoded) constructs a ``CallProgress``, passes it to
    :func:`interruptible_call`, and calls :meth:`touch` from inside
    the worker each time bytes flow. The stale timer then measures
    time since the LAST touch — a true no-progress detector.

    Thread contract: ``touch`` is called from the worker thread,
    ``last`` is read from the polling thread. A single float store is
    atomic under the GIL; no lock needed.
    """

    __slots__ = ("_last", "_first")

    def __init__(self) -> None:
        self._last = time.perf_counter()
        self._first: float | None = None

    def touch(self) -> None:
        now = time.perf_counter()
        self._last = now
        if self._first is None:
            self._first = now

    def reset(self) -> None:
        """Re-arm for a fresh call: restart the no-progress timer and
        clear the first-touch mark (adapters reuse one beacon across
        calls — without the reset, TTFT would report the previous
        call's first token)."""
        self._last = time.perf_counter()
        self._first = None

    @property
    def last(self) -> float:
        return self._last

    @property
    def first(self) -> float | None:
        """perf_counter timestamp of the FIRST progress touch this
        call, or None if nothing has flowed yet. ``first - call_start``
        is the time-to-first-token."""
        return self._first


def interruptible_call(
    fn: Callable[[], T],
    interrupt_event: threading.Event,
    *,
    poll_interval: float = 0.1,
    stale_timeout: float | None = None,
    on_heartbeat: Callable[[float], None] | None = None,
    on_abandon: Callable[[], None] | None = None,
    join_on_abandon: float = 0.0,
    progress: CallProgress | None = None,
) -> T:
    """Run ``fn()`` on a daemon thread while the main thread polls the
    interrupt event + heartbeat + stale timer.

    Returns ``fn``'s result on success; re-raises any exception from
    inside ``fn``; raises :class:`AgentInterrupted` if the interrupt
    event is set; raises :class:`StaleCallTimeout` if ``stale_timeout``
    passes without ``fn`` returning.

    ``on_heartbeat(elapsed_s)`` fires on every poll tick while the
    call is in flight — useful for surfacing "still waiting" status
    to the TUI / gateway. Pass ``None`` to disable.

    ``progress`` (when provided) changes what "stale" means: the
    timer measures seconds since the worker's most recent
    ``progress.touch()`` instead of seconds since the call started.
    Adapters that stream (HTTP chunks, per-token decode) should pass
    one — otherwise a long healthy generation is indistinguishable
    from a hung socket and gets killed at ``stale_timeout``.

    **Cancellation contract.** For an HTTP / SDK call, abandoning the
    thread is safe — the socket eventually closes and the request is
    discarded. But an *in-process* call (llama-cpp ``create_chat_completion``)
    keeps running on a SHARED model instance after we abandon it: that
    zombie decode corrupts the KV cache and every subsequent call fails
    with ``llama_decode returned -1/-3`` (the 2026-05-28 Hermes-3
    full-corpus cascade — one stalled case poisoned 42 more). So a
    cancellable in-process adapter passes:

      * ``on_abandon`` — fired the instant we decide to bail (stale OR
        interrupt). The adapter sets an abort flag its generation polls
        (llama-cpp ``stopping_criteria``), so the decode stops cleanly
        at the next token instead of running to completion.
      * ``join_on_abandon`` — after signalling, wait up to this many
        seconds for the worker to actually finish, so the shared model
        is in a clean state before we return and the next call starts.
        ``0`` (default) keeps the pure abandon behaviour for HTTP.
    """

    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    started = time.perf_counter()
    thread.start()

    def _abandon(exc: BaseException) -> None:
        """Signal the worker to stop, optionally wait for it to finish,
        then raise ``exc`` in the caller."""
        if on_abandon is not None:
            try:
                on_abandon()
            except Exception:  # noqa: BLE001 — abort-signal bugs never mask the raise
                pass
            if join_on_abandon > 0:
                thread.join(timeout=join_on_abandon)
        raise exc

    while thread.is_alive():
        if interrupt_event.is_set():
            _abandon(AgentInterrupted("agent loop was interrupted"))
        elapsed = time.perf_counter() - started
        if stale_timeout is not None:
            since_progress = (
                time.perf_counter() - progress.last
                if progress is not None
                else elapsed
            )
            if since_progress > stale_timeout:
                _abandon(StaleCallTimeout(
                    f"no progress for {since_progress:.1f}s "
                    f"({elapsed:.1f}s total, "
                    f"stale_timeout={stale_timeout:.0f}s)"
                ))
        if on_heartbeat is not None:
            try:
                on_heartbeat(elapsed)
            except Exception:  # noqa: BLE001 — heartbeat bugs never break the call
                pass
        thread.join(timeout=poll_interval)

    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


__all__ = [
    "AgentInterrupted",
    "CallProgress",
    "StaleCallTimeout",
    "interruptible_call",
]
