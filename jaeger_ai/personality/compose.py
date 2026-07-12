"""Compose a Personality into a human-readable system prompt block.

Maps the structured 0..1 sliders into language the brain reads
naturally:

    Expression
      sarcasm: 0.45   → "moderate sarcasm"
      directness: 0.8 → "very direct"
      warmth: 0.5     → "balanced warmth"

The block ends up appended to the assembled system prompt by
``core/prompts/assemble.py`` when an instance has a
``personality.json`` on disk.  Frozen text + structured stats +
operator-authored speech_patterns + custom_instructions.

Tests pin the wording so future contributors can't accidentally
break what the brain has been trained against.
"""

from __future__ import annotations

from .schema import (
    Domains,
    Expression,
    HEXACO,
    Personality,
    SPECIAL,
)


# Phrase bands — kept stable.  Order matters: the FIRST band whose
# threshold is exceeded wins.  Operators reading this should think
# in HALVES (low / mid / high) with a slight bias toward not over-
# claiming when the slider is near 0.5.
_BANDS: tuple[tuple[float, str], ...] = (
    (0.90, "extreme"),
    (0.75, "very high"),
    (0.60, "high"),
    (0.40, "moderate"),
    (0.25, "low"),
    (0.10, "very low"),
    (0.00, "minimal"),
)


def _band(value: float) -> str:
    """Return the band label for a 0..1 value."""
    v = max(0.0, min(1.0, float(value)))
    for threshold, label in _BANDS:
        if v >= threshold:
            return label
    return "minimal"


def compose_block(p: Personality) -> str:
    """Return the system-prompt fragment for this personality."""
    parts: list[str] = []
    if p.name:
        parts.append(f"## Who I am — {p.name}")
        if p.description:
            parts.append(p.description.strip())
    if p.custom_instructions:
        parts.append(p.custom_instructions.strip())
    parts.append(_compose_expression(p.expression))
    parts.append(_compose_hexaco(p.hexaco))
    parts.append(_compose_domains(p.domains))
    parts.append(_compose_special(p.special))
    if p.speech_patterns:
        parts.append(_compose_speech(p.speech_patterns))
    return "\n\n".join(s for s in parts if s)


def _compose_expression(e: Expression) -> str:
    bits = [
        f"sarcasm:    {_band(e.sarcasm)} ({e.sarcasm:.2f})",
        f"warmth:     {_band(e.warmth)} ({e.warmth:.2f})",
        f"verbosity:  {_band(e.verbosity)} ({e.verbosity:.2f})",
        f"formality:  {_band(e.formality)} ({e.formality:.2f})",
        f"directness: {_band(e.directness)} ({e.directness:.2f})",
        f"humor:      {_band(e.humor)} ({e.humor:.2f})",
        f"empathy:    {_band(e.empathy)} ({e.empathy:.2f})",
        f"aggression: {_band(e.aggression)} ({e.aggression:.2f})",
    ]
    return "## How I express myself (calibrated)\n\n  " + "\n  ".join(bits)


def _compose_hexaco(h: HEXACO) -> str:
    bits = [
        f"openness:           {_band(h.openness)} ({h.openness:.2f})",
        f"conscientiousness:  {_band(h.conscientiousness)} ({h.conscientiousness:.2f})",
        f"extraversion:       {_band(h.extraversion)} ({h.extraversion:.2f})",
        f"agreeableness:      {_band(h.agreeableness)} ({h.agreeableness:.2f})",
        f"neuroticism:        {_band(h.neuroticism)} ({h.neuroticism:.2f})",
        f"honesty/humility:   {_band(h.honesty_humility)} ({h.honesty_humility:.2f})",
    ]
    return "## Underlying disposition (HEXACO)\n\n  " + "\n  ".join(bits)


def _compose_domains(d: Domains) -> str:
    bits = [
        f"science:    {_band(d.science)} ({d.science:.2f})",
        f"philosophy: {_band(d.philosophy)} ({d.philosophy:.2f})",
        f"technology: {_band(d.technology)} ({d.technology:.2f})",
        f"art:        {_band(d.art)} ({d.art:.2f})",
        f"politics:   {_band(d.politics)} ({d.politics:.2f})",
        f"psychology: {_band(d.psychology)} ({d.psychology:.2f})",
        f"nature:     {_band(d.nature)} ({d.nature:.2f})",
        f"combat:     {_band(d.combat)} ({d.combat:.2f})",
    ]
    return (
        "## Knowledge weights (lens preferences when synthesising)\n\n"
        "  " + "\n  ".join(bits)
    )


def _compose_special(s: SPECIAL) -> str:
    bits = [
        f"perception:    {_band(s.perception)} ({s.perception:.2f})",
        f"charisma:      {_band(s.charisma)} ({s.charisma:.2f})",
        f"intelligence:  {_band(s.intelligence)} ({s.intelligence:.2f})",
        f"endurance:     {_band(s.endurance)} ({s.endurance:.2f})",
        f"agility:       {_band(s.agility)} ({s.agility:.2f})",
        f"strength:      {_band(s.strength)} ({s.strength:.2f})",
        f"luck:          {_band(s.luck)} ({s.luck:.2f})",
    ]
    return "## SPECIAL\n\n  " + "\n  ".join(bits)


def _compose_speech(patterns: tuple[str, ...]) -> str:
    bits = [f"- {p}" for p in patterns if p]
    if not bits:
        return ""
    return "## Speech patterns\n\n" + "\n".join(bits)


# ── Persona Compiler: State (sliders) → View (prose) ────────────────
#
# compose_block above is the STATE view — the full numeric dump Studio shows
# an operator editing a character. The functions below are the VIEW the live
# model sees: raw floats compiled into behavioral prose, deviations only.
# A base 4B model can't map "sarcasm: 0.40" to behavior, but it reads "wield
# sharp sarcasm" fine. See dev/docs/reality/persona_compiler.md.

_HIGH = 0.60
_LOW = 0.30

# Per Expression trait: (low-band clause, high-band clause). None = that side
# is the trait's natural default (e.g. 0.0 sarcasm), so it emits nothing.
_EXPRESSION_CLAUSES: dict[str, tuple[str | None, str | None]] = {
    "sarcasm":    (None, "wield sharp sarcasm and dry wit"),
    "warmth":     ("keep a cool, detached tone", "be warm and encouraging"),
    "verbosity":  ("keep replies short and clipped", "explain generously"),
    "formality":  ("speak casually and skip the formalities", "keep your language formal and precise"),
    "directness": ("soften and hedge your phrasing", "be blunt and direct"),
    "humor":      (None, "lean into humor and levity"),
    "empathy":    ("stay matter-of-fact", "lead with empathy"),
    "aggression": (None, "be forceful and confrontational"),
}

PERSONA_BOUNDARY = (
    "THE PERSONA BOUNDARY: this voice is for prose you address to the operator "
    "ONLY. When you write a PLAN line, call a tool, fill a tool argument, or "
    "write code, drop the persona entirely — there you are Jaeger OS: cold, "
    "precise, literal."
)


def expression_clauses(e: Expression) -> list[str]:
    """The deviating Expression sliders as behavioral clauses. Mid-band
    (0.30–0.60) emits nothing — neutral is the default."""
    out: list[str] = []
    for trait, (low_c, high_c) in _EXPRESSION_CLAUSES.items():
        v = max(0.0, min(1.0, float(getattr(e, trait))))
        if v > _HIGH and high_c:
            out.append(high_c)
        elif v < _LOW and low_c:
            out.append(low_c)
    return out


def domain_lens(d: Domains) -> str:
    """High knowledge domains (>0.60) as a single 'lens' sentence, or ''."""
    order = ("science", "philosophy", "technology", "art",
             "politics", "psychology", "nature", "combat")
    high = [name for name in order if float(getattr(d, name)) > _HIGH]
    if not high:
        return ""
    return "You tend to frame things through " + ", ".join(high) + "."
