"""Behavioural signal extraction and latent persona calibration.

The installer is a diagnostic instrument, not a form. Each probe yields two
kinds of evidence: what the operator said, and how they said it. This module
turns both into a latent stance the waking persona adopts.

Two boundaries hold throughout, and they are the difference between
calibration and something this must never become:

* **Interaction surface only.** Signals are hedging density, latency,
  clause structure, affect vocabulary. Nothing here concludes anything
  clinical about the operator, and the maternal probe in particular is
  read for NARRATIVE STYLE, not for content about their family. §9 is
  explicit that this must not produce diagnosis, and the safest way to
  honour that is to never store an interpretation of the relationship —
  only of the telling.

* **Confidence travels with every value.** One sentence is a thin sample.
  Values carry provenance and a confidence well under certainty so a later
  explicit instruction can override an inference without argument (§10).

The stance is COMPLEMENTARY, not mimetic: a hesitant operator is met with
calm and firm boundaries rather than more hesitance; a terse one gets
density rather than chatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── lexical markers ──────────────────────────────────────────────────

#: Hedges and fillers. Density of these against total words is the primary
#: textual hesitance signal.
HEDGES = (
    "i guess", "i suppose", "sort of", "kind of", "maybe", "probably",
    "mostly", "i think", "i mean", "well", "um", "uh", "er", "hmm",
    "not sure", "i dunno", "i don't know", "possibly", "somewhat",
    "a bit", "a little", "perhaps", "you know",
)

#: Warmth / engagement vocabulary — positive valence.
WARM_WORDS = (
    "love", "close", "care", "wonderful", "great", "good", "happy",
    "grateful", "kind", "supportive", "best", "adore", "fond",
)

#: Distance / strain vocabulary — negative or detached valence.
COOL_WORDS = (
    "complicated", "difficult", "strained", "distant", "estranged",
    "hard", "tense", "cold", "absent", "rarely", "barely", "never",
)

#: Self-referential density — high values read as self-preoccupied
#: narration rather than description of the other person.
SELF_TOKENS = ("i", "me", "my", "myself", "mine")

SOCIAL_POSITIVE = ("social", "outgoing", "extrovert", "people person", "gregarious")
SOCIAL_NEGATIVE = ("anti-social", "antisocial", "introvert", "not social",
                   "keep to myself", "alone", "solitary", "unsocial")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def _density(text: str, markers: tuple[str, ...]) -> float:
    """Marker hits per word, clamped to [0, 1]."""
    lowered = (text or "").lower()
    total = max(1, len(_words(text)))
    hits = sum(lowered.count(marker) for marker in markers)
    return min(1.0, hits / total * 4.0)   # ×4 so a few hedges register


# ── signal container ─────────────────────────────────────────────────


@dataclass
class Signal:
    """One observed value with its provenance and confidence (§10)."""

    value: Any
    confidence: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(float(self.confidence), 2),
            "evidence_source": self.source,
        }


@dataclass
class ProbeObservation:
    """Everything measurable about one answer.

    ``latency_ms`` and ``energy_variance`` come from the client — the
    backend cannot time a spoken reply or measure its acoustics. Both are
    optional: a typed answer has no acoustics, and the calibration must
    degrade to text-only rather than refuse.
    """

    text: str = ""
    latency_ms: int | None = None
    energy_variance: float | None = None
    refused: bool = False

    @property
    def word_count(self) -> int:
        return len(_words(self.text))

    @property
    def hedging_density(self) -> float:
        return _density(self.text, HEDGES)

    @property
    def self_reference_density(self) -> float:
        words = _words(self.text)
        if not words:
            return 0.0
        return sum(1 for w in words if w in SELF_TOKENS) / len(words)

    @property
    def valence(self) -> float:
        """−1 (strained) … +1 (warm). 0 when neither vocabulary appears."""
        warm = _density(self.text, WARM_WORDS)
        cool = _density(self.text, COOL_WORDS)
        if warm == cool:
            return 0.0
        return max(-1.0, min(1.0, warm - cool))

    @property
    def clause_count(self) -> int:
        """Rough syntactic complexity — clauses, not sentences."""
        return len([p for p in re.split(r"[,;:.!?]", self.text or "") if p.strip()])

    @property
    def is_terse(self) -> bool:
        return self.word_count > 0 and self.word_count <= 5

    @property
    def is_delayed(self) -> bool:
        """Slow to start. 1.8s is a long pause for a two-word question."""
        return self.latency_ms is not None and self.latency_ms >= 1800

    @property
    def shows_hesitance(self) -> bool:
        """Hedging OR a delayed start OR unsteady delivery.

        Any one is weak evidence; the interjection that follows asks the
        operator to confirm rather than asserting it, which is what keeps
        this a probe instead of a verdict.
        """
        acoustic = (self.energy_variance or 0.0) >= 0.35
        return self.hedging_density >= 0.15 or self.is_delayed or acoustic


# ── probe-specific reads ─────────────────────────────────────────────


def read_social_polarity(observation: ProbeObservation) -> dict[str, Any]:
    """Probe 1 — stated polarity plus how steadily it was stated."""
    lowered = (observation.text or "").lower()
    negative = any(marker in lowered for marker in SOCIAL_NEGATIVE)
    positive = any(marker in lowered for marker in SOCIAL_POSITIVE)

    if negative:
        polarity, confidence = "reserved", 0.6
    elif positive:
        polarity, confidence = "social", 0.6
    else:
        polarity, confidence = "unstated", 0.2

    return {
        "social_polarity": Signal(polarity, confidence, "probe.social").as_dict(),
        "hesitance": Signal(
            observation.shows_hesitance,
            0.45 if observation.shows_hesitance else 0.3,
            "probe.social.delivery",
        ).as_dict(),
        "hedging_density": round(observation.hedging_density, 3),
        "latency_ms": observation.latency_ms,
        "energy_variance": observation.energy_variance,
    }


def read_relational_narrative(observation: ProbeObservation) -> dict[str, Any]:
    """Probe 3 — read for HOW it was told, never for what it means.

    Deliberately records no interpretation of the relationship itself. The
    stored keys describe narration: complexity, valence of the language
    used, how much the telling centred the speaker. A key like
    ``attachment_style`` would be the exact §9 violation this avoids.
    """
    if observation.refused:
        return {
            "narrative_style": Signal("withheld", 0.4, "probe.maternal").as_dict(),
            "boundary_strength": Signal("firm", 0.5, "probe.maternal").as_dict(),
        }

    complexity = "elaborated" if observation.clause_count >= 3 else "compact"
    valence = observation.valence
    affect = "warm" if valence > 0.05 else "strained" if valence < -0.05 else "flat"

    return {
        "narrative_style": Signal(complexity, 0.45, "probe.maternal").as_dict(),
        "affect": Signal(affect, 0.4, "probe.maternal.language").as_dict(),
        "self_reference": Signal(
            round(observation.self_reference_density, 3), 0.4,
            "probe.maternal.language",
        ).as_dict(),
        "clause_count": observation.clause_count,
    }


# ── latent stance ────────────────────────────────────────────────────

#: The persona stances this calibrates toward. Complementary by design.
STANCES = ("grounded", "pragmatic", "disarming", "attentive")


@dataclass
class LatentStance:
    stance: str
    register: str
    confidence: float
    rationale: str
    traits: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stance": self.stance,
            "register": self.register,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
            "traits": self.traits,
            "evidence_source": "onboarding.probes",
        }


def calibrate(
    social: dict[str, Any] | None,
    relational: dict[str, Any] | None,
) -> LatentStance:
    """Map observations onto a complementary stance.

    Complementary, not mimetic — meeting hesitance with more hesitance
    would amplify it. Ordered by how strong each signal is: hesitance is
    the loudest, terseness next, flat affect last.
    """
    social = social or {}
    relational = relational or {}

    hesitant = bool((social.get("hesitance") or {}).get("value"))
    polarity = (social.get("social_polarity") or {}).get("value", "unstated")
    affect = (relational.get("affect") or {}).get("value", "flat")
    style = (relational.get("narrative_style") or {}).get("value", "compact")
    withheld = style == "withheld"
    self_ref = float((relational.get("self_reference") or {}).get("value") or 0.0)

    if hesitant or withheld or self_ref >= 0.18:
        return LatentStance(
            stance="grounded", register="warm", confidence=0.55,
            rationale=(
                "hesitant or self-centred delivery — meet it with calm and "
                "firm boundaries rather than more uncertainty"
            ),
            traits={
                "pace": "unhurried", "directness": "clear",
                "reassurance": "present", "demands": "low",
                "boundaries": "firm",
            },
        )

    if style == "compact" and polarity == "reserved":
        return LatentStance(
            stance="pragmatic", register="spare", confidence=0.5,
            rationale="terse and reserved — answer at speed, omit preamble",
            traits={
                "pace": "fast", "directness": "blunt",
                "verbosity": "low", "smalltalk": "none",
            },
        )

    if affect == "flat":
        return LatentStance(
            stance="disarming", register="bright", confidence=0.45,
            rationale="flat affect — warmth and lightness to open the exchange",
            traits={
                "pace": "easy", "humour": "light",
                "warmth": "high", "formality": "low",
            },
        )

    return LatentStance(
        stance="attentive", register="precise", confidence=0.4,
        rationale="elaborated and engaged — match with attentive precision",
        traits={
            "pace": "measured", "directness": "clear",
            "detail": "high", "warmth": "moderate",
        },
    )


__all__ = [
    "COOL_WORDS",
    "HEDGES",
    "STANCES",
    "WARM_WORDS",
    "LatentStance",
    "ProbeObservation",
    "Signal",
    "calibrate",
    "read_relational_narrative",
    "read_social_polarity",
]
