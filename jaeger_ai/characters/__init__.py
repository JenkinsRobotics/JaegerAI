"""Portable character packs and structured persona models.

Each direct child carrying ``character.yaml`` is one ``character/v1`` pack.
The structured layers describe the speaking/agentic half:

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

Public surface::

    from jaeger_ai.characters import (
        Personality, HEXACO, SPECIAL, Expression, Domains,
        load_personality, save_personality, compose_block,
    )

The main agent's worker prompt remains persona-free. Character prose and
compiled traits are applied by Jaeger AI's response-voice path, keeping tool
arguments and plans literal.
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
