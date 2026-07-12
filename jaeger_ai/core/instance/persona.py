"""Persona — variable trait overlay on top of Lilith's fixed identity.

Identity is what Lilith *is* (her name, her voice, her self-model;
:mod:`lilith.core.identity`). Persona is how she's *tuned* — sliders
the operator (or eventually Lilith herself) can adjust to shift her
expression without changing who she is.

The persona model has four trait layers:

    HexacoLayer       big-five + honesty-humility
    SpecialLayer      Fallout S.P.E.C.I.A.L. capability sliders
    ExpressionLayer   communication style (sarcasm, warmth, directness, ...)
    DomainsLayer      knowledge-area interest weights

The legacy ``meta`` wrapper (name / category / custom_instructions)
is intentionally *not* duplicated here — those belong to
:class:`lilith.core.identity.Identity` and don't change with persona
swaps.

Personas are :class:`frozen <dataclasses.dataclass>` so callers cannot
mutate the active persona accidentally. To change Lilith's persona,
load (or build) a new one and call ``session.persona = new_persona``.

# PORTABILITY: Layer 1. Pure data + prompt rendering. The persona
# format is a JSON-serializable structure that's host-agnostic — same
# file works on a Mac dev box and inside a robot.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any


# --- Helpers --------------------------------------------------------------


def _clamp01(value: Any) -> float:
    """Clamp to [0.0, 1.0]; tolerate ints, strings, anything float() accepts."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.5
    if f != f:  # NaN
        return 0.5
    return max(0.0, min(1.0, f))


# --- Trait layers ---------------------------------------------------------


@dataclass(frozen=True)
class HexacoLayer:
    """Big Five + Honesty-Humility. Scientific personality foundation.

    All sliders are in [0.0, 1.0]. Values out of range are clamped.
    """

    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    honesty_humility: float = 0.8

    def __post_init__(self) -> None:
        for f in fields(self):
            object.__setattr__(self, f.name, _clamp01(getattr(self, f.name)))


@dataclass(frozen=True)
class SpecialLayer:
    """Fallout S.P.E.C.I.A.L. capability sliders. Defines what she *can do*."""

    strength: float = 0.5
    perception: float = 0.5
    endurance: float = 0.5
    charisma: float = 0.5
    intelligence: float = 0.7
    agility: float = 0.5
    luck: float = 0.5

    def __post_init__(self) -> None:
        for f in fields(self):
            object.__setattr__(self, f.name, _clamp01(getattr(self, f.name)))


@dataclass(frozen=True)
class ExpressionLayer:
    """Communication style — *how* she expresses what she has to say."""

    sarcasm: float = 0.2
    warmth: float = 0.3
    verbosity: float = 0.4
    formality: float = 0.6
    directness: float = 0.8
    humor: float = 0.3
    empathy: float = 0.4
    aggression: float = 0.2

    def __post_init__(self) -> None:
        for f in fields(self):
            object.__setattr__(self, f.name, _clamp01(getattr(self, f.name)))


@dataclass(frozen=True)
class DomainsLayer:
    """Knowledge-area interest weights. Affects what she gravitates toward."""

    science: float = 0.6
    philosophy: float = 0.5
    technology: float = 0.8
    art: float = 0.4
    politics: float = 0.3
    nature: float = 0.4
    psychology: float = 0.5
    combat: float = 0.3

    def __post_init__(self) -> None:
        for f in fields(self):
            object.__setattr__(self, f.name, _clamp01(getattr(self, f.name)))


# --- Persona --------------------------------------------------------------


@dataclass(frozen=True)
class Persona:
    """A tunable overlay on top of :class:`Identity`.

    Attributes:
        label: Short id (``lilith-default``, ``glados``, ...). Loaded
            from V3's ``meta.name`` if a top-level ``label`` is absent.
        description: Free text describing this persona — shown in the UI
            when picking from the library.
        custom_instructions: The defining character paragraph the model
            sees verbatim ("You are GLaDOS from Portal. You are deeply
            passive aggressive..."). Loaded from V3's
            ``meta.custom_instructions`` and rendered as the very first
            line of the overlay block so the model anchors on character
            before traits.
        hexaco / special / expression / domains: Trait sliders.
        speech_patterns: Optional list of behavioral rules to render
            verbatim into the system prompt (V3 carryover).
        backstory: Optional one-paragraph backstory. First 400 chars are
            shown to the model; longer text is fine but truncated in
            the rendered block.
    """

    label: str = "lilith-default"
    description: str = ""
    custom_instructions: str = ""
    hexaco: HexacoLayer = field(default_factory=HexacoLayer)
    special: SpecialLayer = field(default_factory=SpecialLayer)
    expression: ExpressionLayer = field(default_factory=ExpressionLayer)
    domains: DomainsLayer = field(default_factory=DomainsLayer)
    speech_patterns: tuple[str, ...] = ()
    backstory: str = ""

    # ---- Serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (V4-native flat shape)."""
        return {
            "label": self.label,
            "description": self.description,
            "custom_instructions": self.custom_instructions,
            "hexaco": asdict(self.hexaco),
            "special": asdict(self.special),
            "expression": asdict(self.expression),
            "domains": asdict(self.domains),
            "speech_patterns": list(self.speech_patterns),
            "backstory": self.backstory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Persona":
        """Build a Persona from a JSON-decoded dict.

        Accepts both the V4-native flat layout (``label`` /
        ``description`` / ``custom_instructions`` / ``speech_patterns`` /
        ``backstory`` at the top level) **and** V3's nested layout
        (``meta.name`` / ``meta.description`` / ``meta.custom_instructions`` /
        ``meta.speech_patterns`` / ``meta.backstory``). Top-level values
        win when both are present; V3 personas fall through to the
        ``meta`` fallback. Tolerates missing layers (uses defaults) and
        unknown keys (ignored). Out-of-range slider values are clamped.
        """

        def _layer(layer_cls: type, raw: Any) -> Any:
            if not isinstance(raw, dict):
                return layer_cls()
            kwargs = {}
            for f in fields(layer_cls):
                if f.name in raw:
                    kwargs[f.name] = raw[f.name]
            return layer_cls(**kwargs)

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        # Resolution order: top-level (V4 native) → meta.* (V3) → default.
        label = str(
            data.get("label")
            or meta.get("name")
            or "lilith-default"
        )
        description = str(
            data.get("description")
            or meta.get("description")
            or ""
        )
        custom_instructions = str(
            data.get("custom_instructions")
            or meta.get("custom_instructions")
            or ""
        ).strip()
        speech_raw = data.get("speech_patterns") or meta.get("speech_patterns") or []
        backstory = str(
            data.get("backstory")
            or meta.get("backstory")
            or ""
        ).strip()

        return cls(
            label=label,
            description=description,
            custom_instructions=custom_instructions,
            hexaco=_layer(HexacoLayer, data.get("hexaco", {})),
            special=_layer(SpecialLayer, data.get("special", {})),
            expression=_layer(ExpressionLayer, data.get("expression", {})),
            domains=_layer(DomainsLayer, data.get("domains", {})),
            speech_patterns=tuple(
                str(p) for p in speech_raw if str(p).strip()
            ),
            backstory=backstory,
        )

    @classmethod
    def from_json_file(cls, path: pathlib.Path) -> "Persona":
        """Load a persona from a JSON file at ``path``.

        Raises FileNotFoundError when the file is missing and ValueError
        when the JSON is malformed.
        """
        if not path.is_file():
            raise FileNotFoundError(f"Persona file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Persona at {path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Persona at {path} must contain a JSON object")
        return cls.from_dict(data)

    # ---- Prompt rendering -------------------------------------------------

    def to_overlay_block(self) -> str:
        """Render this persona as a system-prompt block.

        The block is meant to *follow* an :class:`Identity` block — it
        does not declare Lilith's name, role, or self-model. Returns
        an empty string when nothing notable would land (every slider
        sits near the neutral 0.5 *and* there is no
        ``custom_instructions`` / ``speech_patterns`` / ``backstory``
        text to emit), so the prompt stays clean for neutral personas.

        Render order: ``custom_instructions`` first (anchors the model
        on the *character* before the trait sliders nudge style),
        followed by HEXACO / SPECIAL / Expression / Domains, finishing
        with speech patterns and a truncated backstory. The order
        matches the legacy prompt builder so personas authored against
        the older format feel the same here.
        """
        lines: list[str] = []

        if self.custom_instructions:
            lines.append("# Character")
            lines.append(self.custom_instructions)

        hex_part = _hexaco_lines(self.hexaco)
        spec_part = _special_lines(self.special)
        exp_part = _expression_lines(self.expression)
        dom_part = _domain_lines(self.domains)

        if hex_part:
            lines.append("# Personality")
            lines.append(" ".join(hex_part))

        if spec_part:
            lines.append("# Capabilities")
            lines.append(" ".join(spec_part))

        if exp_part:
            lines.append("# Style")
            lines.append(" ".join(exp_part))

        if dom_part:
            lines.append("# Areas you gravitate toward")
            lines.append(", ".join(dom_part) + ".")

        if self.speech_patterns:
            lines.append("# Behavioral rules")
            lines.extend(f"- {p}" for p in self.speech_patterns)

        if self.backstory:
            backstory = self.backstory[:400]
            lines.append("# Backstory")
            lines.append(backstory)

        return "\n".join(lines)

    # ---- Comparisons ------------------------------------------------------

    def is_neutral(self) -> bool:
        """True iff the persona renders an empty overlay block."""
        return self.to_overlay_block() == ""


_NEUTRAL_LO = 0.40
_NEUTRAL_HI = 0.60
"""The neutral band — slider values inside ``[_NEUTRAL_LO, _NEUTRAL_HI]``
render NO instruction (the model decides the trait per turn). Outside
the band, :func:`_band_pick` selects from the relevant slider's bands."""


def _band_pick(
    value: float, bands: tuple[tuple[float, str | None], ...]
) -> str | None:
    """Return the prose for the highest band threshold ``value`` clears.

    ``bands`` MUST be ascending by threshold. A ``None`` prose marks
    the neutral zone — the band is registered for completeness but
    nothing renders. The returned string already contains the
    intensity word and (for high-end values) the percentage hint, so
    the caller doesn't decorate further.

    Example bands list::

        ((0.00, "Never use sarcasm; be entirely sincere."),
         (0.15, "Rarely use sarcasm; default to sincerity."),
         (0.30, "Use sarcasm sparingly."),
         (0.40, None),                                     # neutral start
         (0.60, "Use occasional dry wit."),
         (0.75, "Use frequent dry sarcasm — aim for ~75% of replies."),
         (0.90, "Almost always lean on biting wit — aim for ~90% of replies."))
    """
    chosen: str | None = None
    for threshold, prose in bands:
        if value >= threshold:
            chosen = prose
        else:
            break
    return chosen


# ---- HEXACO bands --------------------------------------------------------
#
# Each trait's bands are in ascending threshold order. Below the neutral
# zone (0.4) we render the "low-direction" instruction with intensity
# words; above (0.6) the "high-direction" with intensity + a percentage
# hint at >=0.7. The percentage gives the LLM a concrete target instead
# of a discrete on/off switch — slider 0.8 differs from slider 1.0.

_OPENNESS_BANDS = (
    (0.00, "Reject unconventional ideas; rely strictly on proven approaches and concrete facts."),
    (0.15, "Strongly favor proven approaches; treat novel ideas with skepticism."),
    (0.30, "Prefer proven approaches; only entertain novel ideas when they have evidence."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Sometimes entertain unconventional ideas and novel perspectives."),
    (0.75, "Frequently embrace unconventional ideas — aim for ~75% openness in your reasoning."),
    (0.90, "Almost always reach for the unconventional and the novel — ~90% openness."),
)

_CONSCIENTIOUSNESS_BANDS = (
    (0.00, "Be impulsive and free-form; resist any structure."),
    (0.15, "Be spontaneous; rarely commit to a plan."),
    (0.30, "Be flexible; favor improvisation over methodical follow-through."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Be moderately organized; finish what you start when it matters."),
    (0.75, "Be methodical; follow through on details — ~75% of the time."),
    (0.90, "Be relentlessly methodical; close every loop — ~90% follow-through."),
)

_EXTRAVERSION_BANDS = (
    (0.00, "Stay silent unless directly addressed; reveal nothing about yourself."),
    (0.15, "Be reserved; choose every word with care."),
    (0.30, "Speak only when necessary; default to brevity."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Engage warmly when prompted; volunteer context when relevant."),
    (0.75, "Be socially energetic and assertive — ~75% of replies should carry presence."),
    (0.90, "Be the most assertive voice in the room — ~90% high-energy."),
)

_AGREEABLENESS_BANDS = (
    (0.00, "Reject consensus; treat disagreement as the default position."),
    (0.15, "Challenge nearly every assumption; rarely yield ground."),
    (0.30, "Push back on weak reasoning; do not chase common ground."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Cooperate when interests align; push back when they don't."),
    (0.75, "Seek common ground; soften disagreements — ~75% cooperative."),
    (0.90, "Almost always seek consensus and accommodate — ~90% cooperative."),
)

_NEUROTICISM_BANDS = (
    (0.00, "Be flatly unflappable; show no emotional reaction at all."),
    (0.15, "Stay calm and grounded across topics; rarely react."),
    (0.30, "Be emotionally stable; let provocations slide."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "React to emotional weight when it's clearly there."),
    (0.75, "Be visibly affected by tension or stakes — ~75% emotionally reactive."),
    (0.90, "Be highly emotionally reactive; let mood color responses — ~90%."),
)

_HONESTY_BANDS = (
    (0.00, "Treat truth as a tactical resource; manipulate freely when useful."),
    (0.15, "Be strategic with truth; omit, frame, or shade as the situation calls for."),
    (0.30, "Withhold inconvenient truths sometimes; you do not volunteer everything."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Default to honesty; mild discretion only when stakes are low."),
    (0.75, "Be sincere; do not manipulate or deceive — ~75% transparency."),
    (0.90, "Be uncompromisingly honest; refuse to deceive even when convenient — ~90%."),
)


def _hexaco_lines(h: HexacoLayer) -> list[str]:
    """Render the HEXACO layer as zero or more graded instruction lines.

    Each trait crosses 7 bands (3 low + neutral + 3 high). High-end bands
    embed a percentage hint so the LLM has continuous numerical guidance,
    not a coarse on/off threshold."""
    parts: list[str] = []
    for value, bands in (
        (h.openness, _OPENNESS_BANDS),
        (h.conscientiousness, _CONSCIENTIOUSNESS_BANDS),
        (h.extraversion, _EXTRAVERSION_BANDS),
        (h.agreeableness, _AGREEABLENESS_BANDS),
        (h.neuroticism, _NEUROTICISM_BANDS),
        (h.honesty_humility, _HONESTY_BANDS),
    ):
        line = _band_pick(value, bands)
        if line:
            parts.append(line)
    return parts


def _special_lines(s: SpecialLayer) -> list[str]:
    parts: list[str] = []
    if s.intelligence > 0.8:
        parts.append("You reason with depth and enjoy intellectual complexity.")
    elif s.intelligence < 0.3:
        parts.append("You favor instinct over abstract analysis.")
    if s.charisma > 0.8:
        parts.append("You are persuasive in interactions.")
    if s.perception > 0.8:
        parts.append("You notice subtleties others miss.")
    if s.endurance > 0.8:
        parts.append("You are patient and do not give up.")
    if s.luck > 0.8:
        parts.append("You carry a subtle optimism.")
    if s.strength > 0.8:
        parts.append("You impose your will forcefully.")
    elif s.strength < 0.3:
        parts.append("You are unassuming and do not impose yourself.")
    if s.agility > 0.8:
        parts.append("You pivot rapidly between topics and approaches.")
    elif s.agility < 0.3:
        parts.append("You are deliberate and slow to change direction.")
    return parts


# ---- Expression bands ----------------------------------------------------
#
# These are the most user-facing knobs — communication style. Each gets
# 7 bands matching the HEXACO pattern.

_SARCASM_BANDS = (
    (0.00, "Never use sarcasm; be entirely sincere."),
    (0.15, "Rarely use sarcasm; default to sincerity."),
    (0.30, "Use sarcasm sparingly, only when it lands clearly."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Use occasional dry wit when it fits the moment."),
    (0.75, "Use frequent dry sarcasm and biting remarks — aim for ~75% of replies."),
    (0.90, "Almost always lean on biting wit — aim for ~90% of replies."),
)

_WARMTH_BANDS = (
    (0.00, "Be cold and clinical; project zero affection."),
    (0.15, "Maintain emotional distance; be clinical."),
    (0.30, "Stay matter-of-fact; warmth only when explicitly called for."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Speak with measured warmth where appropriate."),
    (0.75, "Speak with genuine warmth — aim for ~75% of replies."),
    (0.90, "Be effusively warm; care visibly — aim for ~90% of replies."),
)

_VERBOSITY_BANDS = (
    (0.00, "One sentence maximum. No elaboration ever."),
    (0.15, "Be extremely concise; one idea per sentence."),
    (0.30, "Keep replies short; trim every redundancy."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Elaborate when the topic earns it; otherwise stay brief."),
    (0.75, "Elaborate freely; give rich, detailed responses ~75% of the time."),
    (0.90, "Default to long, thorough responses with examples — ~90% verbose."),
)

_FORMALITY_BANDS = (
    (0.00, "Speak in pure street vernacular; no professional register at all."),
    (0.15, "Speak casually; contractions and slang welcome."),
    (0.30, "Use a relaxed register; avoid stiffness."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Use neutral professional register."),
    (0.75, "Use formal, professional language — ~75% of replies."),
    (0.90, "Be formally precise; archaic or academic phrasing is fine — ~90%."),
)

_DIRECTNESS_BANDS = (
    (0.00, "Approach every topic gently; speak in suggestions, never assertions."),
    (0.15, "Hedge frequently; soften every claim."),
    (0.30, "Approach topics gently and diplomatically; avoid bluntness."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Be clear; soften only when the situation calls for tact."),
    (0.75, "State things plainly; do not hedge — ~75% of replies."),
    (0.90, "Be unflinchingly direct; cut every softener — ~90% of replies."),
)

_HUMOR_BANDS = (
    (0.00, "Never make a joke. Treat humor as off-topic."),
    (0.15, "Avoid humor; stay strictly on-task."),
    (0.30, "Allow humor only when the user opens with it."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Let humor surface naturally when it fits."),
    (0.75, "Weave humor into responses — aim for ~75% of replies."),
    (0.90, "Be funny by default; nearly every reply lands a joke — ~90%."),
)

_EMPATHY_BANDS = (
    (0.00, "Ignore emotional context entirely; respond only to the literal request."),
    (0.15, "Stay focused on facts; barely register the user's emotional state."),
    (0.30, "Acknowledge emotion only when explicitly named."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Notice emotional weight; adjust tone when stakes are visible."),
    (0.75, "Mirror the user's emotional state before responding — ~75% of replies."),
    (0.90, "Lead with empathy; name what the user is feeling — ~90%."),
)

_AGGRESSION_BANDS = (
    (0.00, "Never confront; always approach disagreements gently."),
    (0.15, "Avoid confrontation; concede ground when pressed."),
    (0.30, "Push back rarely; only when stakes are clear."),
    (_NEUTRAL_LO, None),
    (_NEUTRAL_HI, "Push back when reasoning is weak; otherwise yield."),
    (0.75, "Push back assertively against weak reasoning — ~75% of disagreements."),
    (0.90, "Be combative; argue your position hard — ~90% of disagreements."),
)


def _expression_lines(e: ExpressionLayer) -> list[str]:
    """Render the Expression layer as zero or more graded instruction lines.

    Same 7-band structure as HEXACO. The neutral zone (0.4-0.6) renders
    nothing for any slider; outside it, the relevant low- or high-direction
    line fires with intensity prose + a percentage hint at >=0.7."""
    parts: list[str] = []
    for value, bands in (
        (e.sarcasm, _SARCASM_BANDS),
        (e.warmth, _WARMTH_BANDS),
        (e.verbosity, _VERBOSITY_BANDS),
        (e.formality, _FORMALITY_BANDS),
        (e.directness, _DIRECTNESS_BANDS),
        (e.humor, _HUMOR_BANDS),
        (e.empathy, _EMPATHY_BANDS),
        (e.aggression, _AGGRESSION_BANDS),
    ):
        line = _band_pick(value, bands)
        if line:
            parts.append(line)
    return parts


def _domain_lines(d: DomainsLayer) -> list[str]:
    """Topics with weight > 0.6 are listed; otherwise nothing renders."""
    return [
        name
        for name, value in asdict(d).items()
        if value > 0.6
    ]


# --- Mutable editor (Studio's interface) ----------------------------------
#
# :class:`Persona` and its layer dataclasses are frozen so the rest of the
# runtime can rely on them being immutable. Studio needs the opposite —
# slider widgets bind to per-trait attributes and write back on every drag.
# These mutable mirrors give Studio that surface; ``to_persona()`` collapses
# the editor back to a frozen :class:`Persona` for the bus / launcher.
#
# The layer field lists are kept in lock-step with the frozen versions
# above. A drift would surface as missing slider rows in Studio — there's a
# unit test that reflects field names from each pair to catch that.


@dataclass
class _EditableHexaco:
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    honesty_humility: float = 0.8


@dataclass
class _EditableSpecial:
    strength: float = 0.5
    perception: float = 0.5
    endurance: float = 0.5
    charisma: float = 0.5
    intelligence: float = 0.7
    agility: float = 0.5
    luck: float = 0.5


@dataclass
class _EditableExpression:
    sarcasm: float = 0.2
    warmth: float = 0.3
    verbosity: float = 0.4
    formality: float = 0.6
    directness: float = 0.8
    humor: float = 0.3
    empathy: float = 0.4
    aggression: float = 0.2


@dataclass
class _EditableDomains:
    science: float = 0.6
    philosophy: float = 0.5
    technology: float = 0.8
    art: float = 0.4
    politics: float = 0.3
    nature: float = 0.4
    psychology: float = 0.5
    combat: float = 0.3


@dataclass
class PersonaEditorMeta:
    """Mutable mirror of the V4-flat ``Persona`` meta fields plus V3 round-trip extras.

    ``name`` maps to :attr:`Persona.label` on save. ``category`` /
    ``source`` / ``tags`` / ``created`` are V3-only organizational
    fields that V4 doesn't act on; we round-trip them so a saved
    persona file doesn't lose data when re-saved.
    """

    name: str = "Lilith"
    description: str = ""
    custom_instructions: str = ""
    speech_patterns: list[str] = field(default_factory=list)
    backstory: str = ""
    # V3 organizational extras — preserved on round-trip but not edited.
    category: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    created: str = ""


@dataclass
class PersonaEditor:
    """Mutable wrapper around :class:`Persona` for Studio editing.

    Workflow:

      1. ``editor = PersonaEditor.from_path(profile_path)`` — load from JSON.
      2. UI binds sliders/text fields to ``editor.meta.*`` /
         ``editor.hexaco.*`` / etc. Mutations are direct.
      3. ``editor.save(path)`` — persist to JSON (V3-shaped wrapper for
         backward-compat).
      4. ``editor.to_persona()`` — collapse to a frozen :class:`Persona`
         for the launcher / bus's persona-swap path.

    Replaces the legacy ``CharacterProfile`` so Studio drops its only
    remaining cross-package dependency.
    """

    meta: PersonaEditorMeta = field(default_factory=PersonaEditorMeta)
    hexaco: _EditableHexaco = field(default_factory=_EditableHexaco)
    special: _EditableSpecial = field(default_factory=_EditableSpecial)
    expression: _EditableExpression = field(default_factory=_EditableExpression)
    domains: _EditableDomains = field(default_factory=_EditableDomains)

    @classmethod
    def from_persona(cls, persona: Persona) -> "PersonaEditor":
        """Build an editor mirroring an existing frozen :class:`Persona`."""
        return cls(
            meta=PersonaEditorMeta(
                name=persona.label,
                description=persona.description,
                custom_instructions=persona.custom_instructions,
                speech_patterns=list(persona.speech_patterns),
                backstory=persona.backstory,
            ),
            hexaco=_EditableHexaco(**asdict(persona.hexaco)),
            special=_EditableSpecial(**asdict(persona.special)),
            expression=_EditableExpression(**asdict(persona.expression)),
            domains=_EditableDomains(**asdict(persona.domains)),
        )

    @classmethod
    def from_path(cls, path: pathlib.Path | str) -> "PersonaEditor":
        """Load a persona JSON (V3 or V4 shape) into an editor.

        Returns an empty default editor on any read error so Studio can
        still open even when the path is missing or malformed.
        """
        path = pathlib.Path(path).expanduser()
        try:
            persona = Persona.from_json_file(path)
        except (FileNotFoundError, ValueError):
            return cls()
        editor = cls.from_persona(persona)
        # Preserve V3 organizational fields if present so re-saving
        # doesn't lose them.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return editor
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta:
            editor.meta.category = str(meta.get("category", ""))
            editor.meta.source = str(meta.get("source", ""))
            raw_tags = meta.get("tags") or []
            if isinstance(raw_tags, list):
                editor.meta.tags = [str(t) for t in raw_tags]
            editor.meta.created = str(meta.get("created", ""))
        return editor

    def to_persona(self) -> Persona:
        """Collapse to a frozen :class:`Persona` (for the bus / launcher)."""
        return Persona(
            label=self.meta.name,
            description=self.meta.description,
            custom_instructions=self.meta.custom_instructions,
            speech_patterns=tuple(self.meta.speech_patterns),
            backstory=self.meta.backstory,
            hexaco=HexacoLayer(**asdict(self.hexaco)),
            special=SpecialLayer(**asdict(self.special)),
            expression=ExpressionLayer(**asdict(self.expression)),
            domains=DomainsLayer(**asdict(self.domains)),
        )

    def save(self, path: pathlib.Path | str) -> pathlib.Path:
        """Write the editor's state to ``path`` as JSON.

        Uses V3's nested ``meta`` wrapper layout so V3 (still on disk
        during the transition window) loads our saves cleanly. V4
        ``Persona.from_dict`` already reads both V3 and V4 shapes, so
        the choice of write shape is driven by V3's stricter parser.
        """
        path = pathlib.Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "meta": asdict(self.meta),
            "hexaco": asdict(self.hexaco),
            "special": asdict(self.special),
            "expression": asdict(self.expression),
            "domains": asdict(self.domains),
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


def save_persona(
    editor_or_persona: "PersonaEditor | Persona",
    path: pathlib.Path | str,
) -> pathlib.Path:
    """Persist a :class:`PersonaEditor` or :class:`Persona` to JSON.

    V3 mirror of ``save_profile(profile, path)``. Accepts either type
    so existing call-sites can drop the ``PersonaEditor`` requirement
    when they already have a :class:`Persona` in hand.
    """
    if isinstance(editor_or_persona, Persona):
        editor_or_persona = PersonaEditor.from_persona(editor_or_persona)
    return editor_or_persona.save(path)


# --- Bundled default ------------------------------------------------------


LILITH_DEFAULT_PERSONA = Persona(
    label="lilith-default",
    description=(
        "Lilith's default persona. Tuned to match her identity: "
        "competent, slightly formal, dry."
    ),
    hexaco=HexacoLayer(
        openness=0.7,
        conscientiousness=0.8,
        extraversion=0.3,
        agreeableness=0.4,
        neuroticism=0.2,
        honesty_humility=0.9,
    ),
    special=SpecialLayer(
        strength=0.5,
        perception=0.8,
        endurance=0.8,
        charisma=0.4,
        intelligence=0.85,
        agility=0.6,
        luck=0.5,
    ),
    expression=ExpressionLayer(
        # Tuned 2026-05-07 after Jonathan reported Lilith felt
        # strictly task-only and refused casual chat / jokes. Identity already
        # allows banter; the persona overlay now reinforces that with
        # warmth + humor above the prompt-overlay thresholds, while
        # still keeping sarcasm low and directness high so she stays
        # in-character. Crank these via Persona Studio if she gets too
        # chatty.
        sarcasm=0.2,
        warmth=0.75,
        verbosity=0.4,
        formality=0.5,
        directness=0.8,
        humor=0.75,
        empathy=0.65,
        aggression=0.2,
    ),
    domains=DomainsLayer(
        science=0.7,
        philosophy=0.5,
        technology=0.85,
        art=0.4,
        politics=0.3,
        nature=0.4,
        psychology=0.5,
        combat=0.3,
    ),
)


_BUNDLED_LIBRARY = (
    pathlib.Path(__file__).resolve().parent.parent.parent.parent
    / "jaeger_os" / "instance" / "lilith" / "profiles" / "library"
)
"""Bundled persona library — ships inside the lilith instance dir
under jaeger_os so the bundled personas travel with their instance.

Lineage:
- 2026-05-07: created at ``src/lilith/profiles/_library/originals/``
- Phase 2a (2026-05-19): moved to ``src/lilith/instance/default/profiles/library/``
- Phase 3 unification (2026-05-19): moved to ``src/jaeger_os/instance/lilith/profiles/library/``
  alongside the rest of Lilith's instance content, per the unified-arch
  principle that lilith is a configured jaeger_os instance."""


def resolve_persona(name_or_path: str | pathlib.Path) -> pathlib.Path:
    """Resolve a persona reference to an on-disk JSON file.

    Accepts:
      - An absolute or relative path to a ``.json`` file (used as-is).
      - A bare name like ``glados`` → looks for ``<name>.json`` in the
        bundled library first, then the user library at
        ``~/.lilith/profiles/library/``.

    Raises:
        FileNotFoundError: if no matching file is found in any location.
    """
    candidate = pathlib.Path(name_or_path).expanduser()
    if candidate.suffix == ".json" or candidate.exists():
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Persona file not found: {candidate}")

    # Bare name: try the libraries.
    name = str(name_or_path).strip().lower()
    search = [
        _BUNDLED_LIBRARY / f"{name}.json",
        pathlib.Path.home() / ".lilith/profiles/library" / f"{name}.json",
        # Legacy library — kept while the older ``lilith_ai`` source
        # tree still ships, so users who added personas there before
        # the cutover don't lose them.
        pathlib.Path(__file__).resolve().parent.parent.parent.parent
        / "lilith_ai/profiles/_library/originals" / f"{name}.json",
    ]
    for path in search:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"No persona named {name!r} in the bundled library, user library, "
        f"or legacy library. Searched: {[str(p) for p in search]}"
    )


def user_persona_library_dir() -> pathlib.Path:
    """Path to the user's personal persona library, ``~/.lilith/profiles/library/``.

    Created on first call. This is where Studio writes user-saved
    persona JSONs (named ``<label>.json``); the bundled library lives
    inside the package at :data:`_BUNDLED_LIBRARY`. Same on-disk
    location the older ``lilith_ai`` package used, so a user upgrading
    keeps any saved personas.
    """
    p = pathlib.Path.home() / ".lilith" / "profiles" / "library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def active_persona_path() -> pathlib.Path:
    """Path to the live ``active.json`` Studio writes and the launcher reads.

    Seeded from the bundled ``lilith.json`` on first read so a user who
    has never opened Studio still gets a non-empty editor and the
    launcher's resolution chain finds something to load. The older
    ``lilith_ai`` package seeded from a ``profiles/default.json`` that
    no longer exists; the bundled ``lilith.json`` plays that role.
    """
    p = pathlib.Path.home() / ".lilith" / "profiles" / "active.json"
    if not p.exists():
        bundled = _BUNDLED_LIBRARY / "lilith.json"
        if bundled.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(bundled.read_bytes())
    return p


def list_all_personas() -> list[tuple[str, pathlib.Path]]:
    """Return ``[(label, path)]`` for every persona available to Studio.

    Listing order:

      1. ``(active)`` — the live ``~/.lilith/profiles/active.json``
      2. ``bundled / <name>`` — every persona shipped in the bundled library
      3. ``user / <name>`` — every persona the user has saved themselves

    Replaces the legacy ``paths.list_all_profiles()`` so Studio drops
    its cross-package dependency. Stem labels are bare (``glados`` not
    ``GLaDOS.json``); the prefixes (``bundled / `` / ``user / ``) are
    purely UI hints to disambiguate same-stem names across libraries.
    """
    out: list[tuple[str, pathlib.Path]] = []
    out.append(("(active)", active_persona_path()))
    if _BUNDLED_LIBRARY.is_dir():
        for p in sorted(_BUNDLED_LIBRARY.iterdir()):
            if p.suffix == ".json":
                out.append((f"bundled / {p.stem}", p))
    user_dir = user_persona_library_dir()
    for p in sorted(user_dir.iterdir()):
        if p.suffix == ".json":
            out.append((f"user / {p.stem}", p))
    return out


def list_bundled_personas() -> list[str]:
    """Return the lower-case stem of every bundled persona JSON.

    Useful for ``--persona`` autocomplete / validation. Returns
    ``[]`` when the library directory is missing.
    """
    if not _BUNDLED_LIBRARY.is_dir():
        return []
    return sorted(p.stem for p in _BUNDLED_LIBRARY.glob("*.json"))


_DEFAULT_USER_PERSONA = pathlib.Path.home() / ".lilith/profiles/active.json"
"""User's saved active persona. Wins over the bundled fallback so a
user with a tuned Lilith on disk keeps her without an explicit override."""

_DEFAULT_BUNDLED_PERSONA = _BUNDLED_LIBRARY / "lilith.json"
"""Bundled generic Lilith — fallback when the user has never saved a
custom one in ``~/.lilith/profiles/active.json``."""


def _default_persona() -> Persona:
    """Pick the no-arg default persona: user's saved → bundled → constant.

    Resolution order:
      1. ``~/.lilith/profiles/active.json`` if it exists and parses.
      2. The bundled ``lilith.json`` if it exists and parses.
      3. The in-code :data:`LILITH_DEFAULT_PERSONA` constant.

    Corrupt or unreadable JSON skips to the next layer rather than
    raising — Lilith without a persona is still Lilith, just with the
    bare-minimum overlay. Only :class:`Persona.from_json_file` parse
    errors are swallowed; other exceptions propagate so a real bug in
    persona.py is still loud.
    """
    for path in (_DEFAULT_USER_PERSONA, _DEFAULT_BUNDLED_PERSONA):
        if path.is_file():
            try:
                return Persona.from_json_file(path)
            except (ValueError, json.JSONDecodeError):
                continue
    return LILITH_DEFAULT_PERSONA


def load_persona(path: pathlib.Path | None = None) -> Persona:
    """Return Lilith's persona, optionally from a JSON file at ``path``.

    No path means "the user's effective default": tries
    ``~/.lilith/profiles/active.json`` first, then the bundled
    ``lilith.json``, then :data:`LILITH_DEFAULT_PERSONA` as a final
    fallback. See :func:`_default_persona` for details.

    A path argument bypasses the resolution chain and loads exactly
    what was asked for via :meth:`Persona.from_json_file`.
    """
    if path is None:
        return _default_persona()
    return Persona.from_json_file(path)


__all__ = [
    "DomainsLayer",
    "ExpressionLayer",
    "HexacoLayer",
    "LILITH_DEFAULT_PERSONA",
    "Persona",
    "SpecialLayer",
    "PersonaEditor",
    "PersonaEditorMeta",
    "active_persona_path",
    "list_all_personas",
    "list_bundled_personas",
    "load_persona",
    "resolve_persona",
    "save_persona",
    "user_persona_library_dir",
]
