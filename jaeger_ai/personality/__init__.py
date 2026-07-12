"""Personality — structured persona model the agent USES every turn.

Replaces 0.1.0's single free-text ``personality`` field on
``Identity`` with a five-dimension structured model the brain
composes into its system prompt:

    HEXACO          six big-five-like personality factors (0..1)
    SPECIAL         Fallout-style stat block (charisma, perception, ...)
                    operator-friendly metaphor for traits that
                    aren't strict personality but matter for
                    response shaping
    Expression      conversational sliders (sarcasm, warmth,
                    verbosity, formality, directness, humor,
                    empathy, aggression)
    Domains         knowledge weights — which topics the agent
                    skews toward when synthesising
    SpeechPatterns  short fragments characterising HOW the agent
                    phrases things (operator-authored micro-rules)

Source data for this module shape comes directly from operator's
Lilith-AI prior work (``/Users/jonathanjenkins/GITHUB/Lilith-AI/
archive/lilith-0.2.2/persona.json``).  We carry the schema forward
exactly so existing personas port without conversion.

Public surface::

    from jaeger_os.personality import (
        Personality, HEXACO, SPECIAL, Expression, Domains,
        load_personality, save_personality, compose_block,
    )

The brain's system prompt assembler appends ``compose_block(p)``
when an instance has personality_v2 set, gating off the legacy
free-text ``Identity.personality`` field when both are present
(operator preference: structured wins).
"""

from .compose import compose_block
from .schema import (
    Domains,
    Expression,
    HEXACO,
    Personality,
    SPECIAL,
    load_personality,
    save_personality,
)

__all__ = [
    "Domains",
    "Expression",
    "HEXACO",
    "Personality",
    "SPECIAL",
    "compose_block",
    "load_personality",
    "save_personality",
]
