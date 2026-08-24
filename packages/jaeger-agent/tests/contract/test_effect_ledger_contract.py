"""Shared EffectLedger contract — an authoritative action happens once.

These tests are the reason the ledger exists: resumption re-runs code,
and re-running "send the invoice" is not a retry, it is a second
invoice.
"""

from __future__ import annotations

import pytest

from jaeger_agent.cognition.effects import (
    EffectError,
    EffectIndeterminate,
    EffectLedger,
)


def test_adapter_satisfies_the_protocol(effect_ledger):
    assert isinstance(effect_ledger, EffectLedger)


def test_first_call_executes(effect_ledger):
    calls = []
    result, executed = effect_ledger.once(
        "invoice:42", "send_email", lambda: calls.append(1) or "sent"
    )
    assert (result, executed, calls) == ("sent", True, [1])


def test_second_call_replays_without_executing(effect_ledger):
    calls = []

    def send():
        calls.append(1)
        return "sent"

    effect_ledger.once("invoice:42", "send_email", send)
    result, executed = effect_ledger.once("invoice:42", "send_email", send)

    assert result == "sent"
    assert executed is False
    assert calls == [1], "the effect ran twice"


def test_distinct_keys_are_independent(effect_ledger):
    effect_ledger.once("invoice:42", "send", lambda: "a")
    result, executed = effect_ledger.once("invoice:43", "send", lambda: "b")
    assert (result, executed) == ("b", True)


def test_recorded_effect_is_inspectable(effect_ledger):
    effect_ledger.once("invoice:42", "send_email", lambda: {"id": 7},
                       run_id="r-1")
    effect = effect_ledger.get("invoice:42")
    assert effect.status == "done"
    assert effect.action == "send_email"
    assert effect.result == {"id": 7}
    assert effect.run_id == "r-1"
    assert effect.completed_at


def test_unknown_key_is_none(effect_ledger):
    assert effect_ledger.get("never:claimed") is None


# ── the crash case ─────────────────────────────────────────────────


def test_a_failing_effect_leaves_the_claim_pending(effect_ledger):
    """It may have half-landed. The ledger must not pretend otherwise."""
    with pytest.raises(ZeroDivisionError):
        effect_ledger.once("invoice:42", "send_email", lambda: 1 / 0)

    effect = effect_ledger.get("invoice:42")
    assert effect is not None
    assert effect.status == "pending"


def test_retrying_an_indeterminate_effect_refuses_to_guess(effect_ledger):
    calls = []

    with pytest.raises(ZeroDivisionError):
        effect_ledger.once("invoice:42", "send_email", lambda: 1 / 0)

    with pytest.raises(EffectIndeterminate) as caught:
        effect_ledger.once("invoice:42", "send_email",
                           lambda: calls.append(1) or "sent")

    assert calls == [], "re-executed an effect of unknown outcome"
    assert "verify externally" in str(caught.value)


def test_resolve_settles_an_indeterminate_effect(effect_ledger):
    """The operator checked: it did land. Record the truth and move on."""
    with pytest.raises(ZeroDivisionError):
        effect_ledger.once("invoice:42", "send_email", lambda: 1 / 0)

    effect_ledger.resolve("invoice:42", "sent-after-all")

    result, executed = effect_ledger.once("invoice:42", "send_email",
                                          lambda: "sent again")
    assert (result, executed) == ("sent-after-all", False)


def test_abandon_frees_the_key_for_a_real_retry(effect_ledger):
    """The operator checked: it never landed. Retrying is now correct."""
    with pytest.raises(ZeroDivisionError):
        effect_ledger.once("invoice:42", "send_email", lambda: 1 / 0)

    effect_ledger.abandon("invoice:42")

    result, executed = effect_ledger.once("invoice:42", "send_email",
                                          lambda: "sent")
    assert (result, executed) == ("sent", True)


def test_cannot_resolve_a_settled_effect(effect_ledger):
    effect_ledger.once("invoice:42", "send_email", lambda: "sent")
    with pytest.raises(EffectError, match="already done"):
        effect_ledger.resolve("invoice:42", "sent twice")


def test_cannot_abandon_a_settled_effect(effect_ledger):
    """Abandoning a done effect would re-arm a real side effect."""
    effect_ledger.once("invoice:42", "send_email", lambda: "sent")
    with pytest.raises(EffectError, match="already done"):
        effect_ledger.abandon("invoice:42")


def test_resolve_unknown_key_is_an_error(effect_ledger):
    with pytest.raises(EffectError, match="no effect"):
        effect_ledger.resolve("never:claimed")


def test_abandon_unknown_key_is_an_error(effect_ledger):
    with pytest.raises(EffectError, match="no effect"):
        effect_ledger.abandon("never:claimed")
