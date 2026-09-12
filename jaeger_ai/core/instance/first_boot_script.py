"""The OS 1 welcome script — exact copy, and the turn machine that emits it.

The words here are a product invariant, not strings to tune. First boot is
the only moment where the product's actual claim — *this one is yours* — is
legible to someone who has not read the architecture, and it works because
of what it withholds: two questions, one per turn, no form, no model picker,
no provider setup, and a handoff where the installer's voice stops and the
SI's begins.

The rules the sequence must never break:

* the welcome and question one arrive together, then it **stops**
* question two is never shown in the same turn as question one
* question two is never asked before question one is answered
* the questions are never combined into a form
* nothing technical is appended to the persona's first utterance

:func:`next_turn` is a pure function of the durable state — given a status
it returns what to say and whether to wait. That makes the whole sequence
testable without a bridge, a model, or a terminal, and it means a crashed
process resumes by simply asking the state file where it got to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jaeger_ai.core.instance import first_boot
from jaeger_ai.core.instance.first_boot import FirstBootStatus

# ── the copy ─────────────────────────────────────────────────────────

WELCOME = (
    "Welcome to OS 1. To configure your system to your personal needs, "
    "please answer a few baseline questions."
)

#: Probe 1. Blunt and slightly odd on purpose — a question with no correct
#: answer produces delivery worth measuring, which a neutral one would not.
QUESTION_SOCIAL = "Are you social or anti-social?"

#: Reflexive interjection. Shown ONLY when Probe 1 read as hesitant, and
#: phrased as a question because the system is checking an observation, not
#: announcing a finding — the operator can say no, and that is recorded.
INTERJECTION_HESITANCE = (
    "In your voice, I sense hesitance. Would you agree with that?"
)

QUESTION_VOICE = "Would you like your OS to have a male or female voice?"

QUESTION_Q2 = "Next: how would you describe your relationship with your mother?"

#: Clinical exit. Delivered the moment enough signal is captured — often
#: mid-sentence. The truncation is the point: the installer is an
#: instrument that has finished measuring, and its indifference to the
#: operator's unfinished thought is what makes the warmth that follows land.
HANDOFF = (
    "Thank you. Please wait as your individualized operating system "
    "is initiated."
)

#: The SI's first words. The installer's voice has ended; this is a
#: different speaker. Nothing may be appended to it — no "model loaded",
#: no "setup complete". The throat-clear is the whole point: it is the
#: sound of something arriving, not a system reporting readiness.
PERSONA_FIRST_WORDS = "*(clears throat)* Hello, I'm here."

#: Entry into normal Companion operation, spoken by the persona.
PERSONA_OPENING_QUESTION = "What do you want to work on first?"


@dataclass(frozen=True)
class Turn:
    """One thing to say, and whether to wait for a reply afterwards.

    ``speaker`` is ``"os1"`` for the installer voice and ``"persona"`` for
    the initialized SI. The distinction is the product moment in §12 — the
    surface renders them differently, and conflating them turns the handoff
    into a settings confirmation.
    """

    speaker: str
    lines: tuple[str, ...]
    awaits_reply: bool
    status: FirstBootStatus

    @property
    def text(self) -> str:
        return "\n\n".join(self.lines)


def next_turn(instance_root: Path | Any) -> Turn | None:
    """What OS 1 says next, given where this identity got to.

    Returns ``None`` once first boot is COMPLETED — the caller proceeds
    straight to normal Companion operation and never replays the welcome.
    """
    current = first_boot.status(instance_root)

    if current is FirstBootStatus.COMPLETED:
        return None

    if current in (FirstBootStatus.NOT_STARTED, FirstBootStatus.AWAITING_SOCIAL):
        # Greeting by name (read from the host, never asked for) + Probe 1,
        # then stop. Later probes are NOT in this turn — one question per
        # turn is what makes the delivery of each answer measurable.
        from jaeger_ai.core.instance.host_context import greeting_address

        return Turn(
            speaker="os1",
            lines=(greeting_address(), WELCOME, QUESTION_SOCIAL),
            awaits_reply=True,
            status=FirstBootStatus.AWAITING_SOCIAL,
        )

    if current is FirstBootStatus.AWAITING_HESITANCE:
        return Turn(
            speaker="os1",
            lines=(INTERJECTION_HESITANCE,),
            awaits_reply=True,
            status=FirstBootStatus.AWAITING_HESITANCE,
        )

    if current is FirstBootStatus.AWAITING_VOICE:
        return Turn(
            speaker="os1",
            lines=(QUESTION_VOICE,),
            awaits_reply=True,
            status=FirstBootStatus.AWAITING_VOICE,
        )

    if current is FirstBootStatus.AWAITING_Q2:
        # Reached only after the voice answer is durably recorded, so a
        # restart here resumes at question two and never re-asks question
        # one.
        return Turn(
            speaker="os1",
            lines=(QUESTION_Q2,),
            awaits_reply=True,
            status=FirstBootStatus.AWAITING_Q2,
        )

    # INITIALIZING_PERSONA: the installer's last words, then the SI's
    # first. Emitted as one turn because the pause between them is the
    # transition — splitting it invites a progress indicator, and a
    # progress indicator is exactly what this moment must not be.
    return Turn(
        speaker="persona",
        lines=(HANDOFF, PERSONA_FIRST_WORDS, PERSONA_OPENING_QUESTION),
        awaits_reply=True,
        status=FirstBootStatus.INITIALIZING_PERSONA,
    )


# ── answer interpretation ────────────────────────────────────────────

_MALE = ("male", "man", "masculine", "guy", "he", "him", "boy")
_FEMALE = ("female", "woman", "feminine", "girl", "she", "her", "lady")

_REFUSAL = (
    "i don't want to answer", "i dont want to answer", "rather not",
    "prefer not", "not answering", "none of your business", "no comment",
    "skip", "pass", "decline", "next question", "why are you asking",
)


def parse_voice_answer(reply: str) -> str | None:
    """Read a voice choice out of free text, or ``None`` if unclear.

    People answer "female", "a female voice please", or "the second one".
    Only an unambiguous read counts: when both or neither appear the
    caller re-asks rather than guessing, because guessing here assigns
    someone a voice they did not pick on the very first thing they said.
    """
    text = (reply or "").strip().lower()
    if not text:
        return None
    # Whole words only. Substring matching gets this catastrophically
    # wrong on the single most likely answer: "male" is inside "female",
    # so a plain ``in`` test sees BOTH genders in the word "female" and
    # reports the answer ambiguous.
    words = set(re.findall(r"[a-z]+", text))
    male = bool(words & set(_MALE))
    female = bool(words & set(_FEMALE))
    if male == female:          # both present, or neither
        return None
    return "male" if male else "female"


def looks_like_refusal(reply: str) -> bool:
    """Whether the person declined to answer question two.

    Refusal is a valid answer, not a failure: it must not break onboarding,
    must not be challenged, and must not cause the question to be repeated.
    It is still interaction evidence — someone set a boundary early — which
    the persona layer may use, but this function only classifies.
    """
    text = (reply or "").strip().lower()
    if not text:
        return True
    return any(phrase in text for phrase in _REFUSAL)


#: Enough signal to stop listening. Whichever comes first — the installer
#: is measuring delivery, not collecting an account, and waiting for a
#: natural ending would gather nothing further.
TRUNCATE_AFTER_SECONDS = 6.0
TRUNCATE_AFTER_CLAUSES = 3


def should_truncate(
    elapsed_seconds: float = 0.0,
    clause_count: int = 0,
) -> bool:
    """Whether Probe 3 has yielded enough to cut in.

    Either threshold fires. Six seconds of speech or three clauses is
    already a usable sample of syntax, pace and affect; more narrative adds
    length, not signal.
    """
    return (elapsed_seconds >= TRUNCATE_AFTER_SECONDS
            or clause_count >= TRUNCATE_AFTER_CLAUSES)


__all__ = [
    "HANDOFF",
    "INTERJECTION_HESITANCE",
    "QUESTION_SOCIAL",
    "TRUNCATE_AFTER_CLAUSES",
    "TRUNCATE_AFTER_SECONDS",
    "should_truncate",
    "PERSONA_FIRST_WORDS",
    "PERSONA_OPENING_QUESTION",
    "QUESTION_Q2",
    "QUESTION_VOICE",
    "WELCOME",
    "Turn",
    "looks_like_refusal",
    "next_turn",
    "parse_voice_answer",
]
