"""Autonomous name selection — dynamic, gender-respecting, non-hardcoded.

The SI names itself at the State 3 transition. Three properties matter and
each has a distinct failure mode:

* **Dynamic** — a hardcoded name makes every install's SI identical, which
  is the opposite of the product claim.
* **Gender-constrained** — the voice profile is the one explicit choice the
  operator made; a name that fights it is the system overruling them.
* **Stable** — a retried initialization must not rename an SI the operator
  has already met.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance import name_selection as ns


@pytest.fixture()
def inst(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    return root


# ── corpus ───────────────────────────────────────────────────────────

def test_corpus_loads_and_is_diverse():
    corpus = ns.load_corpus()
    assert len(corpus) >= 20
    assert {c.gender for c in corpus} == {"male", "female"}
    # Origins must actually vary — a single-origin list is a themed list,
    # not an index.
    assert len({c.origin for c in corpus}) >= 10
    assert {c.register for c in corpus} <= set(ns.REGISTERS)


def test_every_entry_carries_provenance():
    """"What's your name?" needs origin + meaning to answer honestly."""
    for candidate in ns.load_corpus():
        assert candidate.origin and candidate.meaning, candidate.name


# ── gender is a hard constraint ──────────────────────────────────────

@pytest.mark.parametrize("profile", ["female", "male"])
def test_selection_respects_the_voice_profile(tmp_path, profile):
    seen = set()
    for index in range(25):
        root = tmp_path / f"i{index}"
        root.mkdir()
        record = ns.select_name(root, voice_profile=profile, q2_response="We're close.")
        assert record["gender"] == profile, record
        seen.add(record["name"])
    # And it must actually vary across identities, not return one name.
    assert len(seen) > 1, f"selection looks hardcoded: {seen}"


def test_no_profile_still_selects(tmp_path):
    """A refused or unparsed voice answer must not break initialization."""
    root = tmp_path / "x"; root.mkdir()
    assert ns.select_name(root, voice_profile=None)["name"]


# ── style signal, not diagnosis ──────────────────────────────────────

@pytest.mark.parametrize(("reply", "expected"), [
    ("We are very close, I love her dearly and we talk constantly.", "warm"),
    ("Fine.", "spare"),
    ("I would describe it as somewhat complicated; however, we manage.", "precise"),
])
def test_register_reads_style_from_the_answer(reply, expected):
    register, confidence = ns.read_register(reply)
    assert register == expected
    assert 0.0 < confidence <= 0.7, "one sentence is a thin sample"


def test_refusal_is_a_signal_not_a_failure():
    register, confidence = ns.read_register("", refused=True)
    assert register in ns.REGISTERS
    assert confidence < 0.5, "a refusal must not read as confident evidence"


def test_confidence_never_reaches_certainty():
    """§10: inferred values carry uncertainty; they never harden into fact."""
    for reply in ["We are very close and I love her.", "Fine.", "", "Complicated."]:
        _, confidence = ns.read_register(reply)
        assert confidence < 1.0


# ── stability ────────────────────────────────────────────────────────

def test_same_identity_always_gets_the_same_name(tmp_path):
    root = tmp_path / "stable"; root.mkdir()
    first = ns.select_name(root, voice_profile="female", q2_response="Fine.")
    second = ns.select_name(root, voice_profile="female", q2_response="Fine.")
    assert first["name"] == second["name"]


def test_different_identities_get_different_names(tmp_path):
    names = set()
    for index in range(20):
        root = tmp_path / f"id{index}"; root.mkdir()
        names.add(ns.select_name(root, voice_profile="female", q2_response="Fine.")["name"])
    assert len(names) > 1


# ── integration with the state machine ───────────────────────────────

def test_name_is_chosen_at_the_state_3_transition(inst):
    fb.begin(inst)
    fb.record_voice(inst, "male")
    assert fb.persona_name(inst) is None      # not before Q2
    fb.record_q2(inst, "We get on well enough.")
    chosen = fb.persona_name(inst)
    assert chosen, "the SI must have named itself entering State 3"
    record = fb.persona_name_record(inst)
    assert record["gender"] == "male"


def test_name_is_stable_across_retried_initialization(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Close.")
    first = fb.persona_name(inst)
    # A retried State 3 must not rename an SI the operator has met.
    assert fb.initialize_persona_name(inst) == first
    fb.record_q2(inst, "Something else entirely.")
    assert fb.persona_name(inst) == first


def test_refused_q2_still_yields_a_name(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "I'd rather not", refused=True)
    assert fb.persona_name(inst)


def test_explanation_describes_the_real_mechanism(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "We're close.")
    text = ns.explain_selection(fb.persona_name_record(inst))
    assert fb.persona_name(inst) in text
    assert "index" in text.lower()
    # No invented backstory — only what actually happened.
    for invented in ("dreamed", "always liked", "felt drawn"):
        assert invented not in text.lower()


def test_name_is_not_hardcoded_in_the_script():
    """The script must not contain a literal persona name."""
    from pathlib import Path
    src = Path(ns.__file__).with_name("first_boot_script.py").read_text(encoding="utf-8")
    for candidate in list(ns.load_corpus())[:10]:
        assert candidate.name not in src, f"{candidate.name} hardcoded in the script"
