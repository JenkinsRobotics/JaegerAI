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

def _through_character(root):
    """Hello → bench → character, ready for mic stance probes."""
    fb.begin(root)
    fb.record_bench(root, recommendation={"tier_label": "test"})
    fb.record_character(root, "custom", character_id="assistant")
    return fb.status(root)


def _through_commissioning(root):
    """Drive automatic commissioning to the persona handoff."""
    from jaeger_ai.core.instance.commissioning import CommissioningCoordinator
    return CommissioningCoordinator(root).tick(budget_s=30.0)


def _to_voice(root):
    """Walk Probe 1 with a steady answer so we land on the voice question."""
    _through_character(root)
    fb.record_social(root, "Social.", latency_ms=400)
    return fb.status(root)


def test_fresh_identity_enters_first_boot(inst):
    assert fb.status(inst) is FirstBootStatus.NOT_STARTED
    assert fb.begin(inst) is FirstBootStatus.AWAITING_BENCH
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

def test_opening_turn_greets_by_name_and_asks_probe_one(inst):
    fb.begin(inst)
    turn = script.next_turn(inst)
    assert turn.lines[0].startswith("Hello")      # host-derived, never asked
    assert turn.lines[1] == script.WELCOME
    assert turn.lines[2] == script.BENCH_NARRATION
    assert turn.awaits_reply is False
    assert turn.speaker == "os1"
    assert turn.status is FirstBootStatus.AWAITING_BENCH


def test_preset_character_skips_the_custom_interview(inst):
    fb.begin(inst)
    assert script.QUESTION_SOCIAL not in script.next_turn(inst).text
    fb.record_bench(inst, recommendation={"tier_label": "32 GB"})
    assert fb.status(inst) is FirstBootStatus.AWAITING_CHARACTER
    assert script.next_turn(inst).lines == (script.QUESTION_CHARACTER,)
    fb.record_character(inst, "preset", character_id="jarvis")
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS
    _through_commissioning(inst)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert script.PERSONA_FIRST_WORDS in script.next_turn(inst).lines
    state = fb.snapshot(inst)
    assert state["calibration_source"] == "character_preset"
    assert "social_response" not in state
    assert "voice_profile" not in state
    assert "q2_response" not in state
    assert not state.get("persona_name")


def test_custom_walk_commits_name_voice_stance_and_character(tmp_path):
    """The hybrid conversation must land in the files the agent actually reads."""
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, Identity, ModelConfig, dump_yaml, load_yaml
    from jaeger_ai.features.personality import persona_state
    from jaeger_ai.features.personality.character import active_character_id

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="Assistant", role="assistant", personality="helpful"))
    dump_yaml(layout.config_path, Config(
        instance_name="inst", model=ModelConfig(model_path="/dev/null")))
    layout.manifest_path.write_text("{}", encoding="utf-8")

    fb.begin(layout)
    fb.record_bench(layout, recommendation={"tier_label": "32 GB"})
    fb.record_character(layout, "custom", character_id="assistant")
    fb.record_social(layout, "Anti-social.", latency_ms=300)
    fb.record_voice(layout, "male")
    fb.record_q2(layout, "Fine.")
    fb.record_model_selection(layout, "in-process", "gemma-4-e4b-it-q4_k_m")
    fb.complete(layout)

    identity = load_yaml(layout.identity_path, Identity)
    config = load_yaml(layout.config_path, Config)
    snap = fb.snapshot(layout)
    assert snap["status"] == FirstBootStatus.COMPLETED.value
    assert identity.name == snap["persona_name"]
    assert identity.voice_id == "am_michael"
    assert config.kokoro_tts.voice == "am_michael"
    assert active_character_id(layout.root) == "assistant"
    stance = snap["latent_stance"]["stance"]
    overrides = persona_state.load_overrides(layout.root, "assistant")
    assert overrides.get("expression")
    assert stance in {"grounded", "pragmatic", "disarming", "attentive"}


def test_custom_assistant_enters_the_guided_interview(inst):
    fb.begin(inst)
    fb.record_bench(inst)
    fb.record_character(inst, "custom", character_id="assistant")
    assert fb.status(inst) is FirstBootStatus.AWAITING_SOCIAL
    # The calibration preamble rides the first probe's turn: why the
    # questions exist is spoken once, ahead of the question itself.
    turn = script.next_turn(inst)
    assert turn.lines == (script.CALIBRATION_PREAMBLE, script.QUESTION_SOCIAL)
    assert fb.snapshot(inst)["calibration_source"] == "guided_interview"


def test_step_back_rewinds_one_question_and_clears_the_answer(inst):
    """Backwards navigation: one step = one question, answers invalidated.

    From Q2 the voice answer stays (revising q2 keeps voice). From VOICE
    the profile is cleared — a stale ``voice_profile`` would silently skip
    the question on re-advance (``_after_social_target`` reads it).
    """
    fb.begin(inst)
    fb.record_character(inst, "custom", character_id="assistant")
    fb.record_social(inst, "I guess maybe social", latency_ms=2400)
    fb.record_hesitance_reply(inst, "no")
    fb.record_voice(inst, "female")
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_VOICE
    doc = fb._read(inst)
    assert "q2_response" not in doc and doc.get("voice_profile") == "female"
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_HESITANCE
    assert "voice_profile" not in fb._read(inst)
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_SOCIAL
    assert "hesitance_reply" not in fb._read(inst)
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_CHARACTER
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_BENCH
    assert fb.step_back(inst) is FirstBootStatus.NOT_STARTED
    assert fb.step_back(inst) is FirstBootStatus.NOT_STARTED  # stays put


def test_step_back_from_voice_lands_on_the_real_previous_question(inst, tmp_path):
    """With the interjection, VOICE's previous question is HESITANCE.

    Without it, VOICE steps back to SOCIAL directly — the interjection
    only counts as "previous" when it actually ran. The answer keys are
    durable by design, so the two branches need separate instances.
    """
    other = tmp_path / "no-interjection"
    other.mkdir()
    fb.begin(other)
    fb.record_character(inst, "custom", character_id="assistant")
    fb.record_social(inst, "I guess maybe social", latency_ms=2400)
    fb.record_hesitance_reply(inst, "no")
    fb.record_voice(inst, "male")
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_VOICE
    assert fb.step_back(inst) is FirstBootStatus.AWAITING_HESITANCE

    fb.record_character(other, "custom", character_id="assistant")
    fb.record_social(other, "Social.", latency_ms=300)
    fb.record_voice(other, "male")
    assert fb.step_back(other) is FirstBootStatus.AWAITING_VOICE
    assert fb.step_back(other) is FirstBootStatus.AWAITING_SOCIAL


def test_step_back_never_rewinds_arrival_or_completion(inst):
    """Once the persona begins arriving, a late frame must not drag a
    finished identity back into the welcome."""
    fb.begin(inst)
    fb.record_character(inst, "custom", character_id="assistant")
    fb.record_social(inst, "social."); fb.record_voice(inst, "male")
    fb.record_q2(inst, "close.")
    _through_commissioning(inst)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert fb.step_back(inst) is FirstBootStatus.INITIALIZING_PERSONA
    # And re-answering forward after a pending rewind re-asks cleanly.
    fb.record_social(inst, "Social.", latency_ms=200)


def test_unnamed_preset_is_rejected_without_advancing(inst):
    fb.begin(inst)
    fb.record_bench(inst)
    with pytest.raises(ValueError, match="character_id"):
        fb.record_character(inst, "preset")
    assert fb.status(inst) is FirstBootStatus.AWAITING_CHARACTER


def test_opening_turn_withholds_later_probes(inst):
    fb.begin(inst)
    text = script.next_turn(inst).text.lower()
    assert "mother" not in text
    assert "male or female" not in text





# 5 ── Q2 cannot appear before Q1 is answered ─────────────────────────

def test_q2_never_precedes_the_voice_answer(inst):
    _to_voice(inst)
    assert script.QUESTION_Q2 not in script.next_turn(inst).text
    fb.record_voice(inst, "female")
    assert script.next_turn(inst).lines == (script.QUESTION_Q2,)


# 7 ── voice preference persists ──────────────────────────────────────

def test_voice_preference_persists(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    assert fb.voice_profile(inst) == "female"


def test_unified_onboarding_does_not_ask_for_voice_twice(inst):
    _through_character(inst)
    fb.record_setup_preferences(inst, voice_profile="female")
    fb.record_social(inst, "Social.", latency_ms=400)
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2
    assert script.next_turn(inst).lines == (script.QUESTION_Q2,)


def test_hesitance_probe_also_skips_an_already_selected_voice(inst):
    _through_character(inst)
    fb.record_setup_preferences(inst, voice_profile="male")
    fb.record_social(inst, "I suppose.", latency_ms=2400)
    assert fb.status(inst) is FirstBootStatus.AWAITING_HESITANCE
    fb.record_hesitance_reply(inst, "No.")
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2


def test_voice_profile_is_vendor_neutral(inst):
    """The stored value is an experience, never a TTS engine's voice id."""
    _to_voice(inst)
    fb.record_voice(inst, "male")
    assert fb.voice_profile(inst) in fb.VOICE_PROFILES
    assert not fb.voice_profile(inst).startswith(("am_", "af_"))


def test_unknown_voice_answer_is_rejected(inst):
    _to_voice(inst)
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
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Complicated, but we talk every week.")
    assert fb.snapshot(inst)["q2_response"].startswith("Complicated")
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS


def test_q2_refusal_is_accepted_and_advances(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "I don't want to answer that.", refused=True)
    snap = fb.snapshot(inst)
    assert snap["q2_refused"] is True
    assert snap["q2_response"] == ""        # a non-answer is not disclosure
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS


def test_refusal_is_not_re_asked(inst):
    _to_voice(inst)
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
    _to_voice(inst)
    seen = []
    seen.append(script.next_turn(inst).text)
    fb.record_voice(inst, "female")
    seen.append(script.next_turn(inst).text)
    fb.record_q2(inst, "She was difficult when I was young.")
    _through_commissioning(inst)
    seen.append(script.next_turn(inst).text)
    blob = " ".join(seen).lower()
    for term in _CLINICAL:
        assert term not in blob, term


def test_q2_storage_records_no_inference(inst):
    """The state file holds the answer, never a conclusion about the person."""
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "She was difficult when I was young.")
    keys = set(fb.snapshot(inst))
    assert not {k for k in keys if "diagnos" in k or "disorder" in k}


# 12, 13 ── resume after restart ──────────────────────────────────────

def test_restart_after_q1_resumes_at_q2(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    # simulate a cold start: nothing in memory, read durable state only
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2
    assert script.next_turn(inst).lines == (script.QUESTION_Q2,)


def test_restart_after_q2_resumes_commissioning_not_the_questions(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS
    assert script.QUESTION_Q2 not in script.next_turn(inst).text
    _through_commissioning(inst)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert script.PERSONA_FIRST_WORDS in script.next_turn(inst).text


def test_completed_identity_never_replays_the_welcome(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    fb.complete(inst)
    assert script.next_turn(inst) is None
    # and a stray re-begin cannot drag them backwards
    assert fb.begin(inst) is FirstBootStatus.COMPLETED


# 14 ── persona boot emits the throat-clear, and nothing technical ────

def test_persona_first_words_are_exact(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    _through_commissioning(inst)
    turn = script.next_turn(inst)
    assert turn.speaker == "persona"
    assert turn.lines[0] == script.HANDOFF
    assert "Please wait" in turn.lines[0]
    assert script.PERSONA_FIRST_WORDS in turn.lines
    assert "(clears throat)" in turn.text
    # Live self-naming with reasons sits between handoff and first words.
    assert any("chose" in line.lower() or "name" in line.lower()
               for line in turn.lines[1:-1]) or fb.persona_name(inst)


def test_nothing_technical_is_appended_to_the_handoff(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    _through_commissioning(inst)
    blob = script.next_turn(inst).text.lower()
    for noise in (
        "model loaded", "provider connected", "memory initialized",
        "setup complete", "gpt", "hermes", "ollama", "claude", "token",
    ):
        assert noise not in blob, noise


def test_persona_enters_companion_by_asking_what_to_do(inst):
    _to_voice(inst)
    fb.record_voice(inst, "female")
    fb.record_q2(inst, "Fine.")
    _through_commissioning(inst)
    assert script.PERSONA_OPENING_QUESTION in script.next_turn(inst).text


# ── idempotency (§21) ────────────────────────────────────────────────

def test_transitions_are_idempotent(inst):
    """Double clicks, retried posts and SSE replays must not double-fire."""
    for _ in range(3):
        fb.begin(inst)
    assert fb.status(inst) is FirstBootStatus.AWAITING_BENCH

    for _ in range(3):
        fb.record_bench(inst, recommendation={"tier_label": "test"})
    assert fb.status(inst) is FirstBootStatus.AWAITING_CHARACTER

    for _ in range(3):
        fb.record_character(inst, "custom", character_id="assistant")
    assert fb.status(inst) is FirstBootStatus.AWAITING_SOCIAL

    for _ in range(3):
        fb.record_social(inst, "Social.", latency_ms=400)
    assert fb.status(inst) is FirstBootStatus.AWAITING_VOICE

    for _ in range(3):
        fb.record_voice(inst, "female")
    assert fb.status(inst) is FirstBootStatus.AWAITING_Q2

    for _ in range(3):
        fb.record_q2(inst, "Fine.")
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS
    _through_commissioning(inst)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA

    for _ in range(3):
        fb.complete(inst)
    assert fb.status(inst) is FirstBootStatus.COMPLETED


def test_persona_name_is_chosen_once_and_stays(inst):
    first = fb.record_persona_name(inst, "Vera")
    second = fb.record_persona_name(inst, "Someone Else")
    assert first == second == "Vera"
    assert fb.snapshot(inst)["persona_name_origin"] == "autonomous_initialization"


def test_generated_persona_name_becomes_runtime_identity(inst):
    from jaeger_ai.core.instance.schemas import Identity, dump_yaml, load_yaml

    identity_path = inst / "identity.yaml"
    dump_yaml(identity_path, Identity(
        name="Assistant",
        role="general assistant",
        personality="calm and direct",
    ))

    assert fb.record_persona_name(inst, "Iris") == "Iris"
    assert load_yaml(identity_path, Identity).name == "Iris"

    # First write wins across both records.
    assert fb.record_persona_name(inst, "Someone Else") == "Iris"
    assert load_yaml(identity_path, Identity).name == "Iris"


def test_backwards_transitions_are_ignored(inst):
    _to_voice(inst)
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
    _to_voice(inst)
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
    assert "Welcome to" in script.next_turn(root).text and "OS 1" in script.next_turn(root).text
