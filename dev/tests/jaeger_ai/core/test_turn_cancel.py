"""Turn cancellation — the user-interrupt scope.

A turn must be stoppable without killing the process. ``begin_turn_cancel_scope``
opens a fresh scope, ``request_turn_cancel`` trips it, and the agent loop
(``_run_via_iter``) checks the Event between steps and halts gracefully.
The loop itself needs a live model, so only the scope contract is unit-
tested here.
"""

from __future__ import annotations

from jaeger_ai.main import (
    _pipeline,
    begin_turn_cancel_scope,
    request_turn_cancel,
)


def test_fresh_scope_starts_clear() -> None:
    ev = begin_turn_cancel_scope()
    assert not ev.is_set()


def test_request_cancel_sets_the_event() -> None:
    ev = begin_turn_cancel_scope()
    request_turn_cancel()
    assert ev.is_set()


def test_begin_scope_reclears_a_stale_cancel() -> None:
    # A cancel left over from a prior turn must not kill the next turn.
    first = begin_turn_cancel_scope()
    request_turn_cancel()
    assert first.is_set()
    second = begin_turn_cancel_scope()
    assert second is first        # the same Event is reused …
    assert not second.is_set()    # … but re-cleared for the new turn


def test_request_cancel_without_scope_is_safe() -> None:
    # No scope ever opened — request must be a silent no-op, not a crash.
    _pipeline.pop("cancel_event", None)
    request_turn_cancel()
    # And a scope opened afterwards is still clean.
    assert not begin_turn_cancel_scope().is_set()
