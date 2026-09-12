"""OS 1 first boot — the product invariants, pinned.

Each test here maps to one of the 14 required proofs for the welcome
sequence. They are deliberately blunt: the copy is exact, the ordering is
exact, and the resume behaviour is exercised by re-reading durable state
rather than by keeping anything in memory, because the failure these guard
against is a person being asked again for something they already answered.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance import first_boot_script as script
from jaeger_ai.core.instance.first_boot import FirstBootStatus


@pytest.fixture()
def inst(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    return root


def _established(tmp_path):
    """An instance that clearly predates the onboarding feature."""
    root = tmp_path / "old"
    root.mkdir()
    (root / "identity.yaml").write_text("name: Vera\nrole: assistant\n")
    (root / "manifest.json").write_text("{}")
    return root


# 1 ── fresh identity enters first boot ───────────────────────────────

def test_fresh_identity_enters_first_boot(inst):
    assert fb.status(inst) is FirstBootStatus.NOT_STARTED
    assert fb.begin(inst) is FirstBootStatus.AWAITING_VOICE
    assert script.next_turn(inst) is not None


# 2 ── existing identity does NOT enter first boot ────────────────────

def test_established_identity_skips_first_boot(tmp_path):
    root = _established(tmp_path)
    assert fb.ensure_migrated(root) is FirstBootStatus.COMPLETED
    assert fb.is_complete(root)
    assert script.next_turn(root) is None


def test_unclassifiable_identity_fails_safe(tmp_path, monkeypatch):
    """Ambiguous state must not reset somebody's SI."""
    root = tmp_path / "weird"
    root.mkdir()
    monkeypatch.setattr(fb, "classify_existing", lambda _layout: fb.UNKNOWN)
    assert fb.ensure_migrated(root) is FirstBootStatus.COMPLETED
    assert fb.snapshot(root)["migration_reason"] == "unclassifiable_failed_safe"


# 3, 4, 6 ── exact greeting, voice question first, not combined ───────

def test_exact_welcome_and_voice_question_first(inst):
    fb.begin(inst)
    turn = script.next_turn(inst)
    assert turn.lines == (
        "Welcome to OS 1. To configure your system to your personal needs, "
        "please answer two baseline questions.",
        "First: would you like your OS to have a male or female voice?",
    )
    assert turn.awaits_reply is True
    assert turn.speaker == "os1"


def test_questions_are_not_combined(inst):
    fb.begin(inst)
    text = script.next_turn(inst).text
    assert "mother" not in text.lower()


# 5 ── Q2 cannot appear before Q1 is answered ─────────────────────────

def test_q2_never_precedes_the_voice_answer(inst):
    fb.begin(inst)
    assert script.QUESTION_Q2 not in script.next_turn(inst).text
    fb.record_voice(inst, "female")
    assert script.next_turn(inst).lines == (script.QUESTION_Q2,)


# 7 ── voice preference persists ──────────────────────────────────────

def test_voice_preference_persists(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    assert fb.voice_profile(inst) == "female"


def test_voice_profile_is_vendor_neutral(inst):
    """The stored value is an experience, never a TTS engine's voice id."""
    fb.begin(inst)
    fb.record_voice(inst, "male")
    assert fb.voice_profile(inst) in fb.VOICE_PROFILES
    assert not fb.voice_profile(inst).startswith(("am_", "af_"))


def test_unknown_voice_answer_is_rejected(inst):
    fb.begin(inst)
    with pytest.raises(ValueError):
        fb.record_voice(inst, "purple")


@pytest.mark.parametrize(("reply", "expected"), [
    ("female", "female"),
    ("a female voice please", "female"),
    ("Male.", "male"),
    ("i'd like a man's voice", "male"),
    ("either", None),
    ("male or female, you pick", None),
    ("", None),
])
def test_parse_voice_answer(reply, expected):
    assert script.parse_voice_answer(reply) == expected


# 8, 9 ── Q2 persists; refusal is accepted ────────────────────────────

def test_q2_response_persists(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Complicated, but we talk every week.")
    assert fb.snapshot(inst)["q2_response"].startswith("Complicated")
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA


def test_q2_refusal_is_accepted_and_advances(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "I don't want to answer that.", refused=True)
    snap = fb.snapshot(inst)
    assert snap["q2_refused"] is True
    assert snap["q2_response"] == ""        # a non-answer is not disclosure
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA


def test_refusal_is_not_re_asked(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "rather not", refused=True)
    assert script.QUESTION_Q2 not in (script.next_turn(inst).text)


@pytest.mark.parametrize("reply", [
    "I'd rather not", "none of your business", "skip", "", "why are you asking",
])
def test_refusal_detection(reply):
    assert script.looks_like_refusal(reply) is True


@pytest.mark.parametrize("reply", [
    "We're close.", "She's a nurse in Leeds.", "Complicated.",
])
def test_non_refusals_are_not_misread(reply):
    assert script.looks_like_refusal(reply) is False


# 10 ── no clinical language anywhere in the sequence ─────────────────

_CLINICAL = (
    "diagnos", "disorder", "attachment style", "trauma", "patholog",
    "narcissis", "depress", "anxiety disorder", "syndrome", "therapy",
)


def test_sequence_emits_no_clinical_language(inst):
    fb.begin(inst)
    seen = []
    seen.append(script.next_turn(inst).text)
    fb.record_voice(inst, "female")
    seen.append(script.next_turn(inst).text)
    fb.record_q2(inst, "She was difficult when I was young.")
    seen.append(script.next_turn(inst).text)
    blob = " ".join(seen).lower()
    for term in _CLINICAL:
        assert term not in blob, term


def test_q2_storage_records_no_inference(inst):
    """The state file holds the answer, never a conclusion about the person."""
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "She was difficult when I was young.")
    keys = set(fb.snapshot(inst))
    assert not {k for k in keys if "diagnos" in k or "disorder" in k}


# 12, 13 ── resume after restart ──────────────────────────────────────

def test_restart_after_q1_resumes_at_q2(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    # simulate a cold start: nothing in memory, read durable state only
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2
    assert script.next_turn(inst).lines == (script.QUESTION_Q2,)


def test_restart_after_q2_resumes_at_persona_init(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert script.PERSONA_FIRST_WORDS in script.next_turn(inst).text


def test_completed_identity_never_replays_the_welcome(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    fb.complete(inst)
    assert script.next_turn(inst) is None
    # and a stray re-begin cannot drag them backwards
    assert fb.begin(inst) is FirstBootStatus.COMPLETED


# 14 ── persona boot emits the throat-clear, and nothing technical ────

def test_persona_first_words_are_exact(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    turn = script.next_turn(inst)
    assert turn.speaker == "persona"
    assert turn.lines[0] == "Thank you. Initializing your individualized OS now."
    assert turn.lines[1] == "*(clears throat)* Hello, I'm here."
    assert "(clears throat)" in turn.text


def test_nothing_technical_is_appended_to_the_handoff(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    blob = script.next_turn(inst).text.lower()
    for noise in (
        "model loaded", "provider connected", "memory initialized",
        "setup complete", "gpt", "hermes", "ollama", "claude", "token",
    ):
        assert noise not in blob, noise


def test_persona_enters_companion_by_asking_what_to_do(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    assert script.PERSONA_OPENING_QUESTION in script.next_turn(inst).text


# ── idempotency (§21) ────────────────────────────────────────────────

def test_transitions_are_idempotent(inst):
    """Double clicks, retried posts and SSE replays must not double-fire."""
    for _ in range(3):
        fb.begin(inst)
    assert fb.status(inst) is FirstBootStatus.AWAITING_VOICE

    for _ in range(3):
        fb.record_voice(inst, "female")
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2

    for _ in range(3):
        fb.record_q2(inst, "Fine.")
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA

    for _ in range(3):
        fb.complete(inst)
    assert fb.status(inst) is FirstBootStatus.COMPLETED


def test_persona_name_is_chosen_once_and_stays(inst):
    first = fb.record_persona_name(inst, "Vera")
    second = fb.record_persona_name(inst, "Someone Else")
    assert first == second == "Vera"
    assert fb.snapshot(inst)["persona_name_origin"] == "autonomous_initialization"


def test_backwards_transitions_are_ignored(inst):
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    fb.complete(inst)
    fb.record_voice(inst, "male")          # a late duplicate arriving after the fact
    assert fb.status(inst) is FirstBootStatus.COMPLETED


# ── reset (§23) ──────────────────────────────────────────────────────

def test_reset_clears_only_first_boot(inst):
    (inst / "memory").mkdir()
    (inst / "memory" / "facts.json").write_text("{}")
    (inst / "identity.yaml").write_text("name: Vera\n")
    fb.begin(inst)
    fb.record_voice(inst, "female")
    fb.complete(inst)

    fb.reset(inst)

    assert fb.status(inst) is FirstBootStatus.NOT_STARTED
    assert (inst / "memory" / "facts.json").exists()   # memory survives
    assert (inst / "identity.yaml").exists()           # identity survives


# ── durability ───────────────────────────────────────────────────────

def test_corrupt_state_file_does_not_crash_boot(inst):
    fb.begin(inst)
    fb.state_path(inst).write_text("{[not yaml at all")
    assert fb.status(inst) is FirstBootStatus.NOT_STARTED


def test_state_file_lives_under_the_instance(inst):
    fb.begin(inst)
    assert fb.state_path(inst) == inst / "first_boot.yaml"
    assert fb.state_path(inst).is_file()


def test_reset_survives_the_migration_guard(tmp_path):
    """An explicit reset must outrank ``ensure_migrated``'s classification.

    Regression: reset used to DELETE first_boot.yaml. ``ensure_migrated``
    reads "no state file" as "predates the feature" and marks an
    established identity COMPLETED — so on an install with an identity.yaml
    the reset silently undid itself on the very next boot, with nothing to
    show the operator it had happened.
    """
    root = tmp_path / "established"
    root.mkdir()
    (root / "identity.yaml").write_text("name: Vera\n")
    (root / "manifest.json").write_text("{}")

    # Established identity: the guard correctly suppresses the welcome.
    assert fb.ensure_migrated(root) is FirstBootStatus.COMPLETED

    fb.reset(root)
    assert fb.status(root) is FirstBootStatus.NOT_STARTED

    # The next boot runs the guard again — and must NOT re-suppress.
    assert fb.ensure_migrated(root) is FirstBootStatus.NOT_STARTED
    assert script.next_turn(root) is not None
    assert "Welcome to OS 1." in script.next_turn(root).text
