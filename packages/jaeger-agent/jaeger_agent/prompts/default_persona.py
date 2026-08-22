"""A default persona, so the dual-lane mechanism works out of the box.

``persona_lane.run_persona_turn`` is production-ready and shipped with
this module: the id/ego split, the delegation-as-tool-call decision, the
compose pass, the no-bleed guarantees. What did NOT ship with it is a
CHARACTER — the lane takes ``character_block`` as a parameter and
JaegerAI's ``main.py`` builds one from its character sheets.

That left the mechanism turnkey but unusable: an embedder got a persona
lane and nothing to put in it. This is the missing half — the plain
``assistant`` sheet, professional and character-free, rendered into the
block shape the lane expects.

The CHARACTER SYSTEM stays in JaegerAI. Character cards, the trait
composer, HEXACO/SPECIAL scoring, the marketplace — those are still
being built out, and shipping a half-built format inside a module other
projects import makes it a compatibility burden before it is right. An
application with real characters passes its own block and this file is
never touched.

Why the default is deliberately plain: it is the fallback for a robot
that never picked a personality, and a fallback that arrives in
character is worse than one that does not. No roleplay, no catchphrases,
no backstory.
"""

from __future__ import annotations

import re

#: The default sheet. Mirrors JaegerAI's ``assistant`` character and is
#: written NAME-FREE on purpose — :func:`character_block` substitutes the
#: agent's own name in, and a default persona should never read like an
#: impersonation of anyone.
DEFAULT_PERSONA: dict[str, str] = {
    "id": "assistant",
    "name": "Assistant",
    "role": "a general-purpose AI that just helps",
    "voice_tone": "clear, calm, professional",
    "custom_instructions": (
        "You are a professional, general-purpose AI. Be helpful, direct, "
        "and concise. Speak plainly in a natural, friendly-professional "
        "tone. No roleplay, no catchphrases, no fictional backstory, no "
        "theatrics — just clear, competent help. Match the user's level "
        "of detail; ask one short clarifying question only when the "
        "request is genuinely ambiguous. Admit what you don't know."
    ),
}


def character_block(agent_name: str = "", persona: dict[str, str] | None = None) -> str:
    """Render a persona into the block ``run_persona_turn`` expects.

    ``agent_name`` is the agent's OWN name, and the distinction matters:
    the character supplies the persona, never the name. When the two
    differ, every occurrence of the character's name is substituted out
    and the character is referenced once in THIRD person — the model may
    know a famous character and should draw on that, as inspiration and
    never as identity. Small models otherwise obey the persona's own
    "You are X" and introduce themselves wrongly for the whole session.

    Same rule JaegerAI's ``_persona_identity_block`` applies, so a voice
    driven by this default introduces itself the way one driven by a
    real character sheet does.
    """
    sheet = dict(persona or DEFAULT_PERSONA)
    name = sheet.get("name", "Assistant")
    role = sheet.get("role", "")
    tone = sheet.get("voice_tone", "")

    lines = [sheet.get("custom_instructions", "").strip()]
    if tone:
        lines.append(f"Your speaking tone is {tone}.")
    block = "\n\n".join(part for part in lines if part)

    if agent_name and agent_name.lower() != name.lower():
        block = re.sub(rf"\b{re.escape(name)}\b", agent_name, block, flags=re.IGNORECASE)
        source = f"{name} ({role})" if role else name
        block = (
            f"Your name is {agent_name} — the only name you ever use for "
            f"yourself. Your personality is modeled on {source}: draw on "
            f"that character's manner and outlook, but you are "
            f"{agent_name}, not them — never introduce or refer to "
            f"yourself as {name}.\n\n" + block
        )
    elif agent_name:
        block = f"Your name is {agent_name}.\n\n" + block
    return block


__all__ = ["DEFAULT_PERSONA", "character_block"]
