"""Who the agent says it is — one identity per turn, owned here.

The rule (operator, 2026-08-19; see
:func:`jaeger_ai.personality.character.persona_display_name`): while a
character sheet is selected, the agent IS that character — its name is
the only name in the prompt and on every surface. Only the ``neutral``
sheet (``assistant``) yields, and then the instance's own name
(identity.yaml) comes through instead. No framework brand ever names
itself in a conversational turn; "Jaeger" is what runs the agent, not
who answers.

Two things in the **jaeger-agent** dependency contradicted that rule, and
both are re-pointed from here rather than forked downstream — the same
seam and the same reasoning as :mod:`jaeger_ai.core.prompt_documents`
(an *instance* and its persona are JaegerAI's concepts; the dependency
stays untouched and unpinned-to-a-fork):

``identity_name``
    A declared prompt fragment that read identity.yaml and emitted "Your
    name is Ted." unconditionally, by design ("the character NEVER
    supplies the name"). That is the design being reversed.
    :func:`register_agent_identity` swaps its builder for one that asks
    :func:`persona_display_name` instead. The registry is an ordered
    list of frozen dataclasses, so this replaces the entry in place —
    position, kind, and inspector metadata are preserved, only ``build``
    changes.

``persona_lane._SELF_MODEL_HEADER``
    The Mode-C lane appends a capability digest to the character's own
    block, and its first line opened "You are a Jaeger agent running
    locally on this machine." A second identity, stated in the second
    person, three paragraphs under "You are Clanker" — this is the line
    that put "Jaeger" in the model's mouth when nothing else did. It is
    a private module constant with no injection point, so it is
    rewritten in place (and the per-boot cache that holds the assembled
    digest is dropped, since a cached copy would outlive the patch).
    Ask upstream to parameterise the header if this seam ever bites.

Both patches are idempotent and fail-open: a dependency that renamed
either target leaves the prompt exactly as the dependency built it,
never a crash and never a half-applied identity.
"""

from __future__ import annotations

from typing import Any

IDENTITY_FRAGMENT = "identity_name"

# The replacement first line for the Mode-C self-model digest. Says what
# the old line said that was TRUE (local, one tool, the capability list
# is not a tool list) and drops the part that named a second self.
SELF_MODEL_HEADER = (
    "You are running locally on this machine. Capability areas below are "
    "NOT tool names — you reach ALL of them through your one tool, "
    "perform_task:"
)


def agent_display_name(layout: Any) -> str:
    """The one name this agent answers to right now.

    The active character's, unless it is the neutral ``assistant`` sheet,
    in which case the instance's own (identity.yaml). ``""`` when neither
    is readable — the fragment then emits nothing, exactly as it did
    before this module existed, rather than inventing a name.
    """
    name = ""
    try:
        from jaeger_ai.core.instance.schemas import Identity, load_yaml
        name = (load_yaml(layout.identity_path, Identity).name or "").strip()
    except Exception:  # noqa: BLE001 — a broken identity never breaks the prompt
        name = ""
    try:
        from jaeger_ai.personality.character import (
            active_character, persona_display_name,
        )
        return persona_display_name(name, active_character(layout.root))
    except Exception:  # noqa: BLE001 — no readable character → the instance's own
        return name


def _identity_name(ctx: Any) -> str:
    """The ``identity_name`` fragment, JaegerAI's version."""
    name = agent_display_name(ctx.layout)
    return f"Your name is {name}." if name else ""


def register_agent_identity() -> bool:
    """Point the dependency's identity surfaces at
    :func:`agent_display_name`. Idempotent; returns True when the prompt
    fragment now carries JaegerAI's builder.

    Called at boot from ``build_system_prompt``, before the first prompt
    assembly, alongside
    :func:`jaeger_ai.core.prompt_documents.register_context_documents`.
    """
    _patch_self_model_header()
    try:
        import dataclasses

        from jaeger_agent.prompts import assemble
    except Exception:  # noqa: BLE001 — no assembler, nothing to re-point
        return False

    fragments = assemble.PROMPT_FRAGMENTS
    for index, fragment in enumerate(fragments):
        if fragment.name != IDENTITY_FRAGMENT:
            continue
        if fragment.build is _identity_name:
            return True
        fragments[index] = dataclasses.replace(
            fragment,
            build=_identity_name,
            source="(generated: active character, else identity.yaml)",
            note="the name the agent answers to — the active character's, "
                 "or the instance's own while the neutral sheet is selected",
        )
        return True
    return False


def _patch_self_model_header() -> None:
    """Rewrite the Mode-C self-model digest's opening line so it stops
    naming a second identity. See the module docstring."""
    try:
        from jaeger_agent.prompts import persona_lane

        if getattr(persona_lane, "_SELF_MODEL_HEADER", None) == SELF_MODEL_HEADER:
            return
        persona_lane._SELF_MODEL_HEADER = SELF_MODEL_HEADER  # noqa: SLF001
        # The digest is assembled once per boot and cached; a copy built
        # before this patch would keep serving the old first line.
        persona_lane.reset_self_model_cache()
    except Exception:  # noqa: BLE001 — the lane is optional, the turn is not
        pass


__all__ = [
    "IDENTITY_FRAGMENT", "SELF_MODEL_HEADER", "agent_display_name",
    "register_agent_identity",
]
