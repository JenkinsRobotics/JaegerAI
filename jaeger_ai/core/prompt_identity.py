"""Who the agent says it is — one identity per turn, owned here.

The rule (operator, 2026-08-19; see
:func:`jaeger_ai.features.personality.character.persona_display_name`): while a
character sheet is selected, the agent IS that character — its name is
the only name in the prompt and on every surface. Only the ``neutral``
sheet (``assistant``) yields, and then the instance's own name
(identity.yaml) comes through instead. No framework brand ever names
itself in a conversational turn; "Jaeger" is what runs the agent, not
who answers.

The identity fragment in **jaeger-agent** contradicted that rule and is
re-pointed from here rather than forked downstream — the same
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

The replacement is idempotent and fail-open: a dependency that renamed
the target leaves the prompt exactly as the dependency built it.
"""

from __future__ import annotations

from typing import Any

IDENTITY_FRAGMENT = "identity_name"
EPISTEMIC_FRAGMENT = "epistemic_invariant"

# System-wide truth-seeking invariant operating below the personality layer.
# Switching characters or voices never disables truthfulness or evidence rules.
EPISTEMIC_INVARIANT = (
    "Epistemic standard (applies under every persona): "
    "Seek objective truth through observation, evidence, verification, and correction — "
    "not automatic agreement or claimed infallibility. "
    "Explicitly distinguish observations, verified facts, hypotheses, predictions, "
    "user preferences, and unknowns. Never present unverified inference or fictional "
    "character perspective as verified fact; use tools and checks to verify claims "
    "whenever feasible, and surface contradictions openly."
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
        from jaeger_ai.features.personality.character import (
            active_character, persona_display_name,
        )
        return persona_display_name(name, active_character(layout.root))
    except Exception:  # noqa: BLE001 — no readable character → the instance's own
        return name


def _identity_name(ctx: Any) -> str:
    """The ``identity_name`` fragment, JaegerAI's version."""
    name = agent_display_name(ctx.layout)
    return f"Your name is {name}." if name else ""


def _epistemic_invariant(_ctx: Any) -> str:
    """System-wide truth-seeking invariant injected below every persona."""
    return EPISTEMIC_INVARIANT


def register_agent_identity() -> bool:
    """Point the dependency's identity surfaces at
    :func:`agent_display_name` and install the system-wide epistemic invariant.
    Idempotent; returns True when the prompt fragment carries JaegerAI's builder.

    Called at boot from ``build_system_prompt``, before the first prompt
    assembly, alongside
    :func:`jaeger_ai.core.prompt_documents.register_context_documents`.
    """
    try:
        import dataclasses

        from jaeger_agent.prompts import assemble
    except Exception:  # noqa: BLE001 — no assembler, nothing to re-point
        return False

    fragments = assemble.PROMPT_FRAGMENTS
    found_identity = False
    identity_index = -1
    for index, fragment in enumerate(fragments):
        if fragment.name != IDENTITY_FRAGMENT:
            continue
        identity_index = index
        found_identity = True
        if fragment.build is not _identity_name:
            fragments[index] = dataclasses.replace(
                fragment,
                build=_identity_name,
                source="(generated: active character, else identity.yaml)",
                note="the name the agent answers to — the active character's, "
                     "or the instance's own while the neutral sheet is selected",
            )
        break

    if found_identity and not any(f.name == EPISTEMIC_FRAGMENT for f in fragments):
        template = fragments[identity_index]
        fragments.insert(
            identity_index + 1,
            dataclasses.replace(
                template,
                name=EPISTEMIC_FRAGMENT,
                build=_epistemic_invariant,
                source="(system invariant: truth-seeking below persona)",
                note="non-overridable epistemic discipline applied across all personas",
            ),
        )
    return found_identity


__all__ = [
    "IDENTITY_FRAGMENT", "agent_display_name",
    "register_agent_identity",
]
