"""Diagnostic probes — signal extraction and latent calibration.

The line this must not cross: these read HOW someone answered, never what
their answer means about them. §9 forbids clinical inference, and the
maternal probe is the obvious place to violate it, so the storage shape is
asserted as well as the behaviour.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance import first_boot_script as script
from jaeger_ai.core.instance import first_boot_signals as sig
from jaeger_ai.core.instance.first_boot import FirstBootStatus


@pytest.fixture()
def inst(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    return root


# ── hesitance detection ──────────────────────────────────────────────

def test_hedging_language_reads_as_hesitance():
    obs = sig.ProbeObservation(text="Well, I guess mostly? Sort of, I mean.")
    assert obs.hedging_density > 0
    assert obs.shows_hesitance


def test_delayed_onset_reads_as_hesitance_without_hedging():
    # A long pause before a confident word is still hesitance.
    obs = sig.ProbeObservation(text="Social.", latency_ms=2600)
    assert obs.is_delayed
    assert obs.shows_hesitance


def test_unsteady_delivery_reads_as_hesitance():
    obs = sig.ProbeObservation(text="Social.", latency_ms=300, energy_variance=0.5)
    assert obs.shows_hesitance


def test_prompt_confident_answer_is_not_hesitant():
    obs = sig.ProbeObservation(text="Social.", latency_ms=350, energy_variance=0.05)
    assert not obs.shows_hesitance


def test_typed_answer_degrades_to_text_only():
    """No acoustics is normal — a keyboard is a legitimate way to answer."""
    obs = sig.ProbeObservation(text="Anti-social.", latency_ms=None)
    assert not obs.is_delayed
    assert not obs.shows_hesitance


# ── the interjection branch ──────────────────────────────────────────

def test_hesitant_answer_triggers_the_interjection(inst):
    fb.begin(inst)
    fb.record_social(inst, "Well, I guess, sort of?", latency_ms=2400)
    assert fb.status(inst) is FirstBootStatus.AWAITING_HESITANCE
    assert script.next_turn(inst).text == script.INTERJECTION_HESITANCE


def test_steady_answer_skips_straight_to_voice(inst):
    fb.begin(inst)
    fb.record_social(inst, "Social.", latency_ms=350)
    assert fb.status(inst) is FirstBootStatus.AWAITING_VOICE
    assert script.INTERJECTION_HESITANCE not in script.next_turn(inst).text


def test_denying_hesitance_lowers_confidence_not_the_record(inst):
    """Correcting the system in its first minute is itself information."""
    fb.begin(inst)
    fb.record_social(inst, "Well, I guess?", latency_ms=2400)
    fb.record_hesitance_reply(inst, "No, not really.")

    snap = fb.snapshot(inst)
    assert snap["hesitance_confirmed"] is False
    hesitance = snap["social_signals"]["hesitance"]
    assert hesitance["value"] is False
    assert hesitance["confidence"] < 0.2, "a denied inference must not stay confident"
    assert fb.status(inst) is FirstBootStatus.AWAITING_VOICE


def test_agreeing_keeps_the_observation(inst):
    fb.begin(inst)
    fb.record_social(inst, "Well, I guess?", latency_ms=2400)
    fb.record_hesitance_reply(inst, "Yeah, probably.")
    assert fb.snapshot(inst)["hesitance_confirmed"] is True


# ── clinical truncation ──────────────────────────────────────────────

@pytest.mark.parametrize(("seconds", "clauses", "expected"), [
    (6.5, 1, True),      # time threshold
    (2.0, 3, True),      # clause threshold
    (2.0, 1, False),     # neither
    (0.0, 0, False),
])
def test_truncation_thresholds(seconds, clauses, expected):
    assert script.should_truncate(seconds, clauses) is expected


def test_handoff_is_the_clinical_exit_phrase():
    assert "Please wait" in script.HANDOFF
    assert "individualized operating system" in script.HANDOFF


# ── latent calibration ───────────────────────────────────────────────

def test_hesitance_calibrates_to_a_grounded_stance():
    social = sig.read_social_polarity(
        sig.ProbeObservation(text="Well, I guess?", latency_ms=2400))
    stance = sig.calibrate(social, {})
    assert stance.stance == "grounded"
    assert stance.traits["boundaries"] == "firm"


def test_terse_reserved_calibrates_to_pragmatic():
    social = sig.read_social_polarity(
        sig.ProbeObservation(text="Anti-social.", latency_ms=300))
    relational = sig.read_relational_narrative(sig.ProbeObservation(text="Fine."))
    stance = sig.calibrate(social, relational)
    assert stance.stance == "pragmatic"
    assert stance.traits["verbosity"] == "low"


def test_flat_affect_calibrates_to_disarming():
    social = sig.read_social_polarity(
        sig.ProbeObservation(text="Social.", latency_ms=300))
    relational = sig.read_relational_narrative(
        sig.ProbeObservation(text="She lives in Leeds and works as a nurse there."))
    stance = sig.calibrate(social, relational)
    assert stance.stance in {"disarming", "attentive"}


def test_every_stance_is_known_and_carries_confidence():
    for text, latency in [("Well, I guess?", 2400), ("Anti-social.", 300),
                          ("Social.", 300), ("Very social indeed.", 400)]:
        social = sig.read_social_polarity(
            sig.ProbeObservation(text=text, latency_ms=latency))
        stance = sig.calibrate(social, {})
        assert stance.stance in sig.STANCES
        assert 0 < stance.confidence < 1.0, "never certainty from one probe"
        assert stance.rationale


# ── §9: no clinical inference, anywhere ──────────────────────────────

_FORBIDDEN_KEYS = (
    "attachment", "diagnos", "disorder", "trauma", "patholog",
    "syndrome", "neuros", "therapy",
)


def test_relational_read_stores_no_clinical_conclusion():
    obs = sig.ProbeObservation(
        text="She was difficult when I was young and we barely speak now.")
    record = sig.read_relational_narrative(obs)
    blob = " ".join(str(k) for k in record).lower()
    for term in _FORBIDDEN_KEYS:
        assert term not in blob, term
    # It describes the TELLING, not the relationship.
    assert "narrative_style" in record


def test_full_sequence_stores_no_clinical_conclusion(inst):
    fb.begin(inst)
    fb.record_social(inst, "Well, I guess?", latency_ms=2400)
    fb.record_hesitance_reply(inst, "yes")
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "She was difficult. We barely speak.")

    blob = str(fb.snapshot(inst)).lower()
    for term in _FORBIDDEN_KEYS:
        assert term not in blob, term


def test_stance_is_injected_before_the_persona_speaks(inst):
    fb.begin(inst)
    fb.record_social(inst, "Social.", latency_ms=300)
    fb.record_voice(inst, "male")
    fb.record_q2(inst, "We're close.")
    stance = fb.latent_stance(inst)
    assert stance and stance["stance"] in sig.STANCES
    # and the name follows the calibrated register
    assert fb.persona_name(inst)


def test_refused_q2_still_calibrates(inst):
    fb.begin(inst)
    fb.record_social(inst, "Social.", latency_ms=300)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "I'd rather not", refused=True)
    stance = fb.latent_stance(inst)
    assert stance["stance"] == "grounded", "a withheld answer is a firm boundary"
