"""OS 1 first boot — durable state behind the conversational welcome.

First boot is the moment a person meets their SI for the first time. A named
character preset already contains its calibration and goes straight to the
handoff. The neutral Assistant takes the short conversational calibration,
one question per turn. That branching sequence is a product invariant, and
the only thing that makes it survivable is this file: a small, durable record
of where the person got to, so a crash, reload, double-click or bridge
reconnect never replays a question they already answered — and never replays
the welcome at all for someone who finished it months ago.

State machine (one direction only, never backwards without an explicit
reset):

    NOT_STARTED ──► AWAITING_BENCH ──► AWAITING_CHARACTER
                                             ├─ preset ─► INITIALIZING_PERSONA
                                             └─ custom ─► AWAITING_SOCIAL
                                                  ─► AWAITING_VOICE
                                                  ─► AWAITING_Q2
                                                  ─► INITIALIZING_PERSONA
    INITIALIZING_PERSONA ──► COMPLETED

Storage is ``<instance>/first_boot.yaml`` — the same shape as the persona
drift file and the person index: one small hand-editable YAML under the
instance root, no schema migration, read defensively because a human may
have opened it.

Two rules this module exists to enforce:

* **Idempotency.** Every transition is a no-op when it has already
  happened. Double clicks, duplicate HTTP posts, SSE reconnects and process
  restarts cannot create a second persona, a second name, or a second
  welcome. The transition functions return the state rather than raising,
  so a caller that fires twice gets the same answer twice.

* **Never replay for an established identity.** An instance that predates
  this feature has no ``first_boot.yaml``, which is indistinguishable from
  a brand-new one by file existence alone. :func:`classify_existing` reads
  durable evidence — an identity the operator already configured, memory,
  a persona — and marks those COMPLETED instead of marching a long-time
  user back through the welcome. When the evidence is ambiguous it refuses
  to guess and reports UNKNOWN, and the caller fails conservatively.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

STATE_FILENAME = "first_boot.yaml"

#: Bumped only when the shape below changes incompatibly. Readers tolerate
#: unknown keys, so additive fields do NOT need a bump.
#: 2 — three-probe diagnostic sequence. A v1 record has no social probe,
#: so its status may be a state this build no longer defines; readers fall
#: back to NOT_STARTED, and ``ensure_migrated`` still protects established
#: identities from being walked through the welcome again.
SCHEMA_VERSION = 3


class FirstBootStatus(str, Enum):
    """Where this identity is in the welcome sequence."""

    NOT_STARTED = "NOT_STARTED"
    #: Live hardware bench (host probes + model tier) before character pick.
    AWAITING_BENCH = "AWAITING_BENCH"
    #: Character preset | custom. Presets skip the mic stance probes because
    #: their complete personality profile is the calibration.
    AWAITING_CHARACTER = "AWAITING_CHARACTER"
    #: Probe 1 — social polarity, and how steadily it is answered.
    AWAITING_SOCIAL = "AWAITING_SOCIAL"
    #: Reflexive interjection, entered ONLY when Probe 1 showed hesitance.
    AWAITING_HESITANCE = "AWAITING_HESITANCE"
    AWAITING_VOICE = "AWAITING_VOICE"
    AWAITING_Q2 = "AWAITING_Q2"
    INITIALIZING_PERSONA = "INITIALIZING_PERSONA"
    COMPLETED = "COMPLETED"


#: Forward order. Used to reject backwards transitions.
_ORDER: tuple[FirstBootStatus, ...] = (
    FirstBootStatus.NOT_STARTED,
    FirstBootStatus.AWAITING_BENCH,
    FirstBootStatus.AWAITING_CHARACTER,
    FirstBootStatus.AWAITING_SOCIAL,
    FirstBootStatus.AWAITING_HESITANCE,
    FirstBootStatus.AWAITING_VOICE,
    FirstBootStatus.AWAITING_Q2,
    FirstBootStatus.INITIALIZING_PERSONA,
    FirstBootStatus.COMPLETED,
)

#: The voice experience the person picked. Deliberately NOT a vendor voice
#: id — ``am_michael`` belongs to one TTS engine, and the preference has to
#: outlive whichever engine is installed. The capability router maps this
#: onto Apple / local / OpenAI / future providers at speak time.
VOICE_PROFILES = ("male", "female")


# ── paths ────────────────────────────────────────────────────────────


def instance_dir(instance_root: Path | Any) -> Path:
    """The instance directory, from either a path or an ``InstanceLayout``.

    The ``Path`` check comes first on purpose, and every caller must go
    through here rather than reaching for ``.root`` directly: ``Path``
    itself has a ``root`` attribute (``"/"`` for an absolute path), so a
    bare ``getattr(x, "root", x)`` silently resolves a perfectly good
    instance path to the filesystem root — where nothing exists, and an
    established identity reads as brand new.
    """
    root = instance_root
    if not isinstance(root, (str, Path)):
        root = getattr(root, "root", root)
    return Path(root)


def state_path(instance_root: Path | Any) -> Path:
    """``<instance>/first_boot.yaml``."""
    return instance_dir(instance_root) / STATE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── read / write ─────────────────────────────────────────────────────


def _read(instance_root: Path | Any) -> dict[str, Any]:
    """The whole document, or ``{}``. Never raises.

    A corrupt or unreadable state file means "we don't know where they
    got to", not a dead agent. The caller treats ``{}`` as NOT_STARTED,
    which is the safe direction for a file that only ever appears on a
    machine that has begun first boot.
    """
    try:
        path = state_path(instance_root)
        if not path.is_file():
            return {}
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — runtime state must never break boot
        return {}
    return doc if isinstance(doc, dict) else {}


def _write(instance_root: Path | Any, doc: dict[str, Any]) -> None:
    """Atomically replace the state file.

    Written to a temp file in the same directory and ``os.replace``d, so a
    crash mid-write leaves the previous state intact rather than a
    half-truncated file that would read as ``{}`` and replay the welcome.
    """
    path = state_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["schema_version"] = SCHEMA_VERSION
    payload = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".first_boot.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp)
        raise


# ── queries ──────────────────────────────────────────────────────────


def status(instance_root: Path | Any) -> FirstBootStatus:
    """Where this identity is. Unknown/corrupt values read as NOT_STARTED."""
    raw = str(_read(instance_root).get("status") or "")
    try:
        return FirstBootStatus(raw)
    except ValueError:
        return FirstBootStatus.NOT_STARTED


def is_complete(instance_root: Path | Any) -> bool:
    """True when the welcome must never be shown again."""
    return status(instance_root) is FirstBootStatus.COMPLETED


def snapshot(instance_root: Path | Any) -> dict[str, Any]:
    """The full record, for diagnostics and the bridge's status query."""
    doc = _read(instance_root)
    doc.setdefault("status", FirstBootStatus.NOT_STARTED.value)
    doc.setdefault("schema_version", SCHEMA_VERSION)
    return doc


def needs_model_selection(instance_root: Path | Any) -> bool:
    """An unfinished setup must not boot an old or unconfirmed default."""
    doc = _read(instance_root)
    return bool(doc) and not is_complete(instance_root) and not doc.get("model_selection")


def record_model_selection(instance_root: Path | Any, provider: str, model: str) -> None:
    doc = _read(instance_root)
    doc["model_selection"] = {"provider": provider, "model": model, "confirmed_at": _now()}
    _write(instance_root, doc)


def record_setup_preferences(instance_root: Path | Any, *, voice_profile: str = "", interaction_posture: str = "") -> None:
    doc = _read(instance_root)
    if voice_profile:
        doc["voice_profile"] = voice_profile
    if interaction_posture:
        doc["interaction_posture"] = interaction_posture
    _write(instance_root, doc)


def voice_profile(instance_root: Path | Any) -> str | None:
    """The chosen voice experience (``male``/``female``), or ``None``."""
    value = _read(instance_root).get("voice_profile")
    return value if value in VOICE_PROFILES else None


def persona_name(instance_root: Path | Any) -> str | None:
    """The name the SI chose for itself, if it has chosen one."""
    value = _read(instance_root).get("persona_name")
    return str(value) if value else None


# ── transitions (all idempotent) ─────────────────────────────────────


def _advance(doc: dict[str, Any], target: FirstBootStatus) -> bool:
    """True when ``target`` is forward of the current status.

    Backwards moves are ignored rather than raising: a duplicate request
    that arrives late (a retried POST, an SSE reconnect replaying a frame)
    must not drag a finished identity back into the welcome.
    """
    try:
        current = FirstBootStatus(str(doc.get("status") or FirstBootStatus.NOT_STARTED.value))
    except ValueError:
        current = FirstBootStatus.NOT_STARTED
    return _ORDER.index(target) > _ORDER.index(current)


def begin(instance_root: Path | Any) -> FirstBootStatus:
    """Start first boot. Safe to call on every boot.

    Returns the resulting status — already-started identities keep theirs,
    which is what makes "show the welcome if we're at AWAITING_VOICE" a
    correct check on a crashed-and-restarted process.
    """
    doc = _read(instance_root)
    if _advance(doc, FirstBootStatus.AWAITING_BENCH):
        doc["status"] = FirstBootStatus.AWAITING_BENCH.value
        doc.setdefault("started_at", _now())
        _write(instance_root, doc)
    return status(instance_root)


def record_bench(
    instance_root: Path | Any,
    recommendation: dict[str, Any] | None = None,
) -> FirstBootStatus:
    """Record live hardware bench results and advance to character pick."""
    doc = _read(instance_root)
    if recommendation:
        doc["hardware_bench"] = recommendation
    doc.setdefault("hardware_bench_at", _now())
    if _advance(doc, FirstBootStatus.AWAITING_CHARACTER):
        doc["status"] = FirstBootStatus.AWAITING_CHARACTER.value
    _write(instance_root, doc)
    return status(instance_root)


def record_character(
    instance_root: Path | Any,
    choice: str,
    *,
    character_id: str = "",
) -> FirstBootStatus:
    """Record the character path and enter the appropriate next stage.

    A named preset already carries identity, voice, disposition, values,
    behavioral defaults, and speech style. Asking its operator the custom
    calibration interview would mix two conflicting sources of truth. The
    neutral Assistant is the custom path and still enters those probes.
    """
    path = str(choice or "").strip().lower()
    if path not in {"preset", "custom"}:
        # Free text: "custom" / "preset" / a character id treated as preset.
        lowered = path
        if "custom" in lowered:
            path = "custom"
        else:
            path = "preset"
            if not character_id and lowered and lowered not in {"preset", "character"}:
                character_id = str(choice).strip()
    if path == "preset" and not str(character_id or "").strip():
        raise ValueError("a preset character requires a character_id")

    doc = _read(instance_root)
    doc["character_path"] = path
    if character_id:
        doc["character_id"] = str(character_id).strip()
    elif path == "custom":
        doc.setdefault("character_id", "assistant")
    doc["calibration_source"] = "character_preset" if path == "preset" else "guided_interview"
    doc.setdefault("character_recorded_at", _now())
    target = (
        FirstBootStatus.INITIALIZING_PERSONA
        if path == "preset"
        else FirstBootStatus.AWAITING_SOCIAL
    )
    if _advance(doc, target):
        doc["status"] = target.value
    _write(instance_root, doc)
    commit_to_instance(instance_root)
    return status(instance_root)


def _after_social_target(doc: dict[str, Any]) -> FirstBootStatus:
    """Do not ask for a voice that unified onboarding already recorded."""
    if doc.get("voice_profile") in VOICE_PROFILES:
        return FirstBootStatus.AWAITING_Q2
    return FirstBootStatus.AWAITING_VOICE


def record_social(
    instance_root: Path | Any,
    response: str,
    *,
    latency_ms: int | None = None,
    energy_variance: float | None = None,
) -> FirstBootStatus:
    """Probe 1. Advances to the interjection ONLY when hesitance shows.

    ``latency_ms`` and ``energy_variance`` come from the client; a typed
    answer supplies neither and the read degrades to text-only rather than
    refusing, because a keyboard is a legitimate way to answer.
    """
    from jaeger_ai.core.instance.first_boot_signals import (
        ProbeObservation,
        read_social_polarity,
    )

    observation = ProbeObservation(
        text=str(response or ""), latency_ms=latency_ms,
        energy_variance=energy_variance,
    )
    signals = read_social_polarity(observation)

    doc = _read(instance_root)
    doc["social_response"] = observation.text
    doc["social_signals"] = signals
    doc.setdefault("social_recorded_at", _now())

    hesitant = bool(signals["hesitance"]["value"])
    target = (FirstBootStatus.AWAITING_HESITANCE if hesitant
              else _after_social_target(doc))
    if _advance(doc, target):
        doc["status"] = target.value
    _write(instance_root, doc)
    return status(instance_root)


def record_hesitance_reply(instance_root: Path | Any, response: str) -> FirstBootStatus:
    """The operator's answer to "I sense hesitance. Would you agree?".

    Recorded either way. Agreement confirms the read; disagreement is ALSO
    information — someone correcting the system in its first minute is
    telling it something about how they expect to be treated — and the
    stored confidence drops so a denied inference cannot harden into fact.
    """
    text = str(response or "").strip().lower()
    denied = any(marker in text for marker in
                 ("no", "not really", "disagree", "wouldn't say", "nope"))

    doc = _read(instance_root)
    doc["hesitance_reply"] = str(response or "")
    doc["hesitance_confirmed"] = not denied
    signals = doc.get("social_signals") or {}
    if denied and isinstance(signals.get("hesitance"), dict):
        # The operator said no. Keep the observation, drop the confidence.
        signals["hesitance"]["value"] = False
        signals["hesitance"]["confidence"] = 0.15
        signals["hesitance"]["evidence_source"] = "probe.social.denied"
        doc["social_signals"] = signals
    target = _after_social_target(doc)
    if _advance(doc, target):
        doc["status"] = target.value
    _write(instance_root, doc)
    return status(instance_root)


def record_voice(instance_root: Path | Any, profile: str) -> FirstBootStatus:
    """Persist the answer to question one and move to question two.

    Raises ``ValueError`` on an unknown profile — the caller normalises
    free text ("a female voice please") before reaching here, and an
    unrecognised value must not silently advance the sequence.
    """
    normalised = str(profile or "").strip().lower()
    if normalised not in VOICE_PROFILES:
        raise ValueError(
            f"voice_profile must be one of {VOICE_PROFILES}, got {profile!r}"
        )
    doc = _read(instance_root)
    # Record the answer even on a repeat call (the person may correct it
    # while still on the question), but only advance forward.
    doc["voice_profile"] = normalised
    doc.setdefault("voice_recorded_at", _now())
    if _advance(doc, FirstBootStatus.AWAITING_Q2):
        doc["status"] = FirstBootStatus.AWAITING_Q2.value
    _write(instance_root, doc)
    commit_to_instance(instance_root)
    return status(instance_root)


def record_q2(
    instance_root: Path | Any,
    response: str,
    *,
    refused: bool = False,
) -> FirstBootStatus:
    """Persist the answer to question two and move to persona initialization.

    Any response is valid — a sentence, one word, a joke, a question back,
    or a refusal. ``refused=True`` records that the person declined without
    storing a non-answer as though it were disclosure. Nothing here
    interprets the content; calibration happens in the persona layer, and
    this module only guarantees the answer is durably recorded before the
    sequence advances.
    """
    doc = _read(instance_root)
    doc["q2_response"] = "" if refused else str(response or "")
    doc["q2_refused"] = bool(refused)
    doc.setdefault("q2_recorded_at", _now())
    entering_persona = _advance(doc, FirstBootStatus.INITIALIZING_PERSONA)
    if entering_persona:
        doc["status"] = FirstBootStatus.INITIALIZING_PERSONA.value
    _write(instance_root, doc)

    # The SI names itself at the State 3 transition, once, using the voice
    # profile as a hard filter and the Q2 register as a soft one. Done here
    # rather than lazily at first "what's your name?" so the name exists
    # before the persona ever speaks — it is part of who arrives, not a
    # fact looked up later.
    if entering_persona:
        _calibrate_stance(instance_root)
        initialize_persona_name(instance_root)
    return status(instance_root)


def _calibrate_stance(instance_root: Path | Any) -> dict[str, Any] | None:
    """Map the probes onto a latent stance for the waking persona.

    Runs once, at the State 3 transition, so the stance exists before the
    persona speaks — it is part of who arrives rather than something
    applied afterwards.
    """
    from jaeger_ai.core.instance.first_boot_signals import (
        ProbeObservation,
        calibrate,
        read_relational_narrative,
    )

    doc = _read(instance_root)
    observation = ProbeObservation(
        text=str(doc.get("q2_response") or ""),
        refused=bool(doc.get("q2_refused")),
    )
    relational = read_relational_narrative(observation)
    stance = calibrate(doc.get("social_signals"), relational)

    doc["relational_signals"] = relational
    doc["latent_stance"] = stance.as_dict()
    _write(instance_root, doc)
    commit_to_instance(instance_root)
    return doc["latent_stance"]


def latent_stance(instance_root: Path | Any) -> dict[str, Any] | None:
    """The calibrated stance, for the persona prompt assembler."""
    value = _read(instance_root).get("latent_stance")
    return value if isinstance(value, dict) else None


def record_persona_name(
    instance_root: Path | Any,
    name: str,
    *,
    origin: str = "autonomous_initialization",
) -> str:
    """Record the name the SI chose. First write wins.

    The name is stable once chosen: a retried initialization must not
    rename an SI the person has already met. Returns the stored name,
    which may be the one from an earlier call.
    """
    doc = _read(instance_root)
    existing = doc.get("persona_name")
    chosen = str(existing or name).strip()
    if existing:
        _promote_persona_name_to_identity(instance_root, chosen)
        return chosen
    doc["persona_name"] = chosen
    doc["persona_name_origin"] = origin
    doc["persona_name_created_at"] = _now()
    _write(instance_root, doc)

    # The custom Assistant sheet is deliberately neutral, so identity.yaml
    # is the authoritative name used by the runtime prompt and every native
    # surface.  Keeping the generated name only in first_boot.yaml creates a
    # split identity: onboarding introduces "Iris", then the app and model
    # revert to "Assistant".  Promote the first-write-wins name at its source.
    # A bare unit-test fixture may not have an identity yet; instance setup
    # always does.
    _promote_persona_name_to_identity(instance_root, chosen)
    return chosen


def _promote_persona_name_to_identity(instance_root: Path | Any, name: str) -> None:
    """Make the custom persona's chosen name the runtime/UI identity."""
    try:
        from jaeger_ai.core.instance.schemas import Identity, dump_yaml, load_yaml

        root = instance_dir(instance_root)
        identity_path = root / "identity.yaml"
        if identity_path.is_file():
            identity = load_yaml(identity_path, Identity)
            if identity.name != name:
                dump_yaml(identity_path, identity.model_copy(update={"name": name}))
    except Exception:
        # first_boot.yaml already owns the durable choice. A malformed or
        # externally edited identity must not erase it; validation on normal
        # boot will surface the identity error with its full context.
        pass


#: Custom-path stance → expression sliders on persona_state.yaml.
#: Preset characters keep their sheet; only guided interview writes these.
_STANCE_EXPRESSION: dict[str, dict[str, float]] = {
    "grounded": {"directness": 0.72, "warmth": 0.62, "verbosity": 0.38, "empathy": 0.58},
    "pragmatic": {"directness": 0.82, "verbosity": 0.22, "warmth": 0.35, "formality": 0.45},
    "disarming": {"warmth": 0.78, "humor": 0.68, "formality": 0.22, "directness": 0.48},
    "attentive": {"empathy": 0.72, "directness": 0.62, "verbosity": 0.58, "warmth": 0.55},
}


def _kokoro_voice(profile: str) -> str | None:
    if profile == "female":
        return "af_heart"
    if profile == "male":
        return "am_michael"
    return None


def commit_to_instance(instance_root: Path | Any) -> None:
    """Flush first_boot.yaml into identity, config, character bind, persona state.

    first_boot.yaml is the conversation record. This is the single write
    into the files the running agent actually reads. Missing instance
    files are skipped — a pre-instance probe must not invent a config.
    """
    root = instance_dir(instance_root)
    doc = _read(instance_root)
    cid = str(doc.get("character_id") or "").strip()
    if cid:
        try:
            from jaeger_ai.personality.character import bind_character
            bind_character(root, cid)
        except Exception:
            pass

    name = str(doc.get("persona_name") or "").strip()
    # Custom interview: the SI named itself. A preset already has a
    # character-sheet name — do not overwrite lilith/Jarvis with a corpus pick.
    if name and doc.get("calibration_source") != "character_preset":
        _promote_persona_name_to_identity(instance_root, name)

    profile = doc.get("voice_profile") if doc.get("voice_profile") in VOICE_PROFILES else None
    voice_id = _kokoro_voice(profile) if profile else None
    if voice_id and doc.get("calibration_source") != "character_preset":
        try:
            from jaeger_ai.core.instance.schemas import Identity, dump_yaml, load_yaml
            identity_path = root / "identity.yaml"
            if identity_path.is_file():
                identity = load_yaml(identity_path, Identity)
                if identity.voice_id != voice_id:
                    dump_yaml(identity_path, identity.model_copy(update={"voice_id": voice_id}))
        except Exception:
            pass
        try:
            from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
            config_path = root / "config.yaml"
            if config_path.is_file():
                config = load_yaml(config_path, Config)
                if getattr(config.kokoro_tts, "voice", None) != voice_id:
                    config.kokoro_tts.voice = voice_id
                    dump_yaml(config_path, Config.model_validate(config.model_dump()))
        except Exception:
            pass

    selection = doc.get("model_selection") if isinstance(doc.get("model_selection"), dict) else {}
    provider = str(selection.get("provider") or "").strip()
    model = str(selection.get("model") or "").strip()
    if provider and model:
        try:
            from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
            from jaeger_ai.core.models.configuration import selected_model_config
            config_path = root / "config.yaml"
            if config_path.is_file():
                config = load_yaml(config_path, Config)
                updated, _, _ = selected_model_config(config, provider=provider, model=model)
                dump_yaml(config_path, Config.model_validate(updated.model_dump()))
        except Exception:
            pass

    stance = doc.get("latent_stance") if isinstance(doc.get("latent_stance"), dict) else {}
    if cid and doc.get("calibration_source") == "guided_interview":
        overrides = _STANCE_EXPRESSION.get(str(stance.get("stance") or ""))
        if overrides:
            try:
                from jaeger_ai.personality import persona_state
                for field_name, value in overrides.items():
                    persona_state.set_trait_override(
                        root, cid, "expression", field_name, value,
                    )
            except Exception:
                pass


def initialize_persona_name(instance_root: Path | Any) -> str | None:
    """Choose and record the SI's name, if it does not have one.

    Called at the State 3 transition. Idempotent by construction — the
    storage layer's first-write-wins means a retried initialization returns
    the existing name rather than renaming an SI the operator has met.

    The gender filter is the operator's State 1 answer, treated as a hard
    constraint: it is the one explicit choice they made, and a name that
    contradicts it would be the system overruling them.
    """
    existing = persona_name(instance_root)
    if existing:
        return existing

    from jaeger_ai.core.instance.name_selection import propose_live_name

    doc = _read(instance_root)
    # Prefer the calibrated register over re-reading the raw answer: the
    # stance already folded in Probe 1's delivery, which the Q2 text alone
    # cannot see.
    stance = doc.get("latent_stance") or {}
    record = propose_live_name(
        instance_root,
        voice_profile=doc.get("voice_profile"),
        q2_response=str(doc.get("q2_response") or ""),
        q2_refused=bool(doc.get("q2_refused")),
        register_override=stance.get("register") if isinstance(stance, dict) else None,
        stance=stance if isinstance(stance, dict) else {},
        bench=doc.get("hardware_bench") if isinstance(doc.get("hardware_bench"), dict) else {},
        character_id=str(doc.get("character_id") or ""),
        character_path=str(doc.get("character_path") or ""),
    )
    if record is None:
        return None

    chosen = record_persona_name(instance_root, record["name"])
    # Keep the provenance beside the name: "what's your name?" is answered
    # from this, so the explanation never has to be reconstructed.
    doc = _read(instance_root)
    doc["persona_name_record"] = record
    _write(instance_root, doc)
    return chosen


def persona_name_record(instance_root: Path | Any) -> dict[str, Any] | None:
    """Origin and meaning of the chosen name, for the identity answer."""
    record = _read(instance_root).get("persona_name_record")
    return record if isinstance(record, dict) else None


def complete(instance_root: Path | Any) -> FirstBootStatus:
    """Mark first boot finished. The welcome is never shown again."""
    doc = _read(instance_root)
    if _advance(doc, FirstBootStatus.COMPLETED):
        doc["status"] = FirstBootStatus.COMPLETED.value
        doc.setdefault("completed_at", _now())
        _write(instance_root, doc)
    commit_to_instance(instance_root)
    return status(instance_root)


#: Rewind table for ``step_back``. Each entry: the status being left →
#: (status to land on, keys written by the answer that left it). Clearing
#: the keys is not cosmetic: ``_after_social_target`` reads
#: ``voice_profile`` to decide whether the voice question is needed, so a
#: stale value would silently skip a question on re-advance. Landing
#: statuses are the question the operator actually saw last — VOICE
#: rewinds past the interjection only when the interjection really
#: happened (``hesitance_reply`` is written exactly when it was asked).
_STEP_BACK: dict[FirstBootStatus, tuple[FirstBootStatus, tuple[str, ...]]] = {
    FirstBootStatus.AWAITING_Q2: (
        FirstBootStatus.AWAITING_VOICE,
        ("q2_response", "q2_refused", "q2_recorded_at"),
    ),
    FirstBootStatus.AWAITING_VOICE: (
        FirstBootStatus.AWAITING_HESITANCE,  # corrected below when it never ran
        ("voice_profile", "voice_recorded_at"),
    ),
    FirstBootStatus.AWAITING_HESITANCE: (
        FirstBootStatus.AWAITING_SOCIAL,
        ("hesitance_reply", "hesitance_confirmed"),
    ),
    FirstBootStatus.AWAITING_SOCIAL: (
        FirstBootStatus.AWAITING_CHARACTER,
        ("social_response", "social_signals", "social_recorded_at"),
    ),
    FirstBootStatus.AWAITING_CHARACTER: (
        FirstBootStatus.AWAITING_BENCH,
        ("character_path", "character_id", "calibration_source",
         "character_recorded_at"),
    ),
    FirstBootStatus.AWAITING_BENCH: (
        FirstBootStatus.NOT_STARTED,
        (),
    ),
}


def step_back(instance_root: Path | Any) -> FirstBootStatus:
    """Rewind one answered question and clear the answer it recorded.

    The operator may go backwards in the welcome the same way they go
    forward: a correction ("I picked the wrong voice") replays the
    question rather than being treated as an attack on the record. Only
    pending-question statuses may rewind — once the persona has begun
    arriving (INITIALIZING_PERSONA, COMPLETED) the sequence is past the
    point where a step back has a defined meaning, and a late frame must
    never drag a finished identity into the welcome (same reasoning as
    :func:`_advance`).

    Voice's landing status depends on durable state: the interjection is
    only "the previous question" when it actually ran, so the rewind
    checks ``hesitance_reply`` before choosing.
    """
    doc = _read(instance_root)
    try:
        current = FirstBootStatus(str(doc.get("status") or FirstBootStatus.NOT_STARTED.value))
    except ValueError:
        return status(instance_root)

    entry = _STEP_BACK.get(current)
    if entry is None:
        return status(instance_root)

    target, keys = entry
    if current is FirstBootStatus.AWAITING_VOICE and not doc.get("hesitance_reply"):
        target = FirstBootStatus.AWAITING_SOCIAL
    for key in keys:
        doc.pop(key, None)
    doc["status"] = target.value
    doc["last_back_step_at"] = _now()
    _write(instance_root, doc)
    return status(instance_root)


def reset(instance_root: Path | Any) -> None:
    """Clear first-boot state ONLY. Deliberate, explicit, narrow.

    This is ``jaeger onboarding reset``. It rewinds the welcome so the
    sequence runs again — and it touches nothing else. Memory, the Library,
    projects, credentials, provider settings and the character sheet all
    survive, because wiping those is a different and far more consequential
    operation that the operator has to ask for by name.

    Writes an explicit NOT_STARTED record rather than deleting the file.
    That distinction is load-bearing: :func:`ensure_migrated` treats "no
    state file" as "this identity predates the feature" and classifies an
    established install COMPLETED. Deleting would therefore undo itself on
    the very next boot — reset, then silently re-suppressed, with no sign
    anything happened. An explicit marker means a deliberate operator reset
    outranks the migration heuristic, which is the correct precedence: the
    heuristic exists to guess for identities that never had state, not to
    overrule someone who asked.
    """
    _write(instance_root, {
        "status": FirstBootStatus.NOT_STARTED.value,
        "reset_at": _now(),
    })


# ── migration for identities that predate this feature ───────────────

#: Returned when existing state cannot be classified safely.
UNKNOWN = "UNKNOWN"


def classify_existing(layout: Any) -> str:
    """Decide whether an instance with no state file is new or established.

    The hazard this exists to prevent: shipping first boot would otherwise
    send every current operator back through the welcome, because "no
    ``first_boot.yaml``" looks identical for a fresh install and a
    two-year-old identity.

    Evidence that an identity predates the feature — any one is enough,
    because each takes deliberate setup or accumulated use that a brand-new
    instance cannot have:

    * a configured ``identity.yaml`` (the operator named and described it)
    * a manifest (the instance was created and versioned)
    * memory on disk (it has been used)

    Returns ``COMPLETED`` for an established identity, ``NOT_STARTED`` for
    one with no trace of prior use, and ``UNKNOWN`` when the instance root
    cannot be inspected at all — in which case the caller must fail
    conservatively rather than reset somebody's SI.
    """
    try:
        root = instance_dir(layout)
        if not root.is_dir():
            return FirstBootStatus.NOT_STARTED.value
    except Exception:  # noqa: BLE001 — an uninspectable root is not a new user
        return UNKNOWN

    try:
        if (root / "identity.yaml").is_file():
            return FirstBootStatus.COMPLETED.value
        if (root / "manifest.json").is_file():
            return FirstBootStatus.COMPLETED.value
        memory = root / "memory"
        if memory.is_dir() and any(
            p.name != ".gitkeep" for p in memory.iterdir()
        ):
            return FirstBootStatus.COMPLETED.value
    except Exception:  # noqa: BLE001 — ambiguous evidence must not reset anyone
        return UNKNOWN
    return FirstBootStatus.NOT_STARTED.value


def ensure_migrated(layout: Any) -> FirstBootStatus:
    """Classify an established identity once, so it skips the welcome.

    Idempotent: an instance that already has a state file is returned
    unchanged. An identity classified UNKNOWN is marked COMPLETED — the
    conservative direction, because wrongly skipping the welcome is a
    missing greeting, while wrongly replaying it looks to a long-time user
    like their SI forgot them.
    """
    if state_path(layout).is_file():
        return status(layout)

    verdict = classify_existing(layout)
    if verdict == FirstBootStatus.NOT_STARTED.value:
        return FirstBootStatus.NOT_STARTED

    doc: dict[str, Any] = {
        "status": FirstBootStatus.COMPLETED.value,
        "completed_at": _now(),
        "migrated": True,
        "migration_reason": (
            "predates_onboarding" if verdict == FirstBootStatus.COMPLETED.value
            else "unclassifiable_failed_safe"
        ),
    }
    _write(layout, doc)
    return FirstBootStatus.COMPLETED


__all__ = [
    "SCHEMA_VERSION",
    "initialize_persona_name",
    "latent_stance",
    "step_back",
    "record_hesitance_reply",
    "record_social",
    "persona_name_record",
    "STATE_FILENAME",
    "UNKNOWN",
    "VOICE_PROFILES",
    "FirstBootStatus",
    "begin",
    "record_bench",
    "record_character",
    "classify_existing",
    "commit_to_instance",
    "complete",
    "ensure_migrated",
    "is_complete",
    "persona_name",
    "record_persona_name",
    "record_q2",
    "record_voice",
    "reset",
    "snapshot",
    "state_path",
    "status",
    "voice_profile",
]
