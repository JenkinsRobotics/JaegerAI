"""The single assembly entry point for every prompt-building path.

Before consolidation, FIVE codepaths built the agent's system prompt; each
had its own logic and rules drifted between them. This module is the single
source of truth: every codepath calls :func:`assemble_prompt` with a ``mode``.

The assembly is a **declared registry** — :data:`PROMPT_FRAGMENTS`. Each
fragment names itself, its kind, and its source, and declares which modes
include it. Nothing reaches the model that isn't a fragment in that list, so
``jaeger prompt show`` (and :func:`iter_fragments`) can enumerate every rule
the LLM receives and where it came from. This is what makes a hidden,
conditional injection (like the old voice gate) structurally impossible.

Fragment kinds:
  * ``safety``    — the Three Laws contract (``agent/prompts/three_laws.md``)
  * ``framework`` — framework-owned standing instructions
    (``agent/prompts/framework_agent.md``)
  * ``instance``  — per-instance identity / soul / personality / contracts
  * ``dynamic``   — generated each turn (skill index, board, tool catalog,
    toolset note)

Modes:
  * ``"agent"``      — the live TUI turn. Full prompt.
  * ``"subagent"``   — a delegated child: framework scaffold + a focused brief,
    MINUS soul/personality/skill-index/board/v2 (the parent owns those).
  * ``"deep_think"`` — autonomous skill development. Full agent prompt.
  * ``"idle_board"`` / ``"cron"`` — same as ``"agent"`` (the diff is in the
    user-role message, not the system prompt).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from jaeger_os.core.instance.instance import InstanceLayout

from .context_blocks import (
    build_board_block,
    build_runtime_tail,
    build_skill_index_block,
    build_toolset_catalog,
    load_framework_prompt,
    load_v2_self_improvement,
)

PromptMode = Literal["agent", "subagent", "deep_think", "idle_board", "cron"]


# Subagent-specific opener. Same rules/identity scaffold the parent uses, so
# the child isn't a different agent — it's the same agent on a focused brief.
_SUBAGENT_PREAMBLE = (
    "You are a focused sub-agent spawned by the parent Jaeger to complete a "
    "single task. Work the task end-to-end with real tool calls, then "
    "summarise the result so the parent can use it. Be terse; the parent "
    "reads your final message, not your intermediate thinking."
)


# ── mode predicates ───────────────────────────────────────────────────
def _all(_mode: PromptMode) -> bool:
    return True


def _non_subagent(mode: PromptMode) -> bool:
    return mode != "subagent"


def _agent_only(mode: PromptMode) -> bool:
    return mode == "agent"


def _subagent_only(mode: PromptMode) -> bool:
    return mode == "subagent"


@dataclass(frozen=True)
class FragmentContext:
    """Everything a fragment builder needs to render its text."""

    layout: InstanceLayout
    mode: PromptMode
    goal: str = ""
    context: str = ""


@dataclass(frozen=True)
class PromptFragment:
    """One declared piece of the system prompt.

    ``source`` and ``note`` exist for the inspector — they let
    ``jaeger prompt show`` cite where each fragment comes from and why it did
    or didn't fire this turn.
    """

    name: str
    kind: str  # "safety" | "framework" | "instance" | "dynamic"
    source: str
    build: Callable[[FragmentContext], str]
    include: Callable[[PromptMode], bool] = field(default=_all)
    note: str = ""


# ── fragment builders that need more than a one-liner ─────────────────
def _three_laws(_ctx: FragmentContext) -> str:
    # Imported lazily so a prompt build never hard-depends on the safety
    # module at import time.
    from jaeger_os.agent.safety import THREE_LAWS_PROMPT_BLOCK

    return THREE_LAWS_PROMPT_BLOCK


def _personality_block(ctx: FragmentContext) -> str:
    # A broken personality file must NEVER take down the boot — the operator
    # just gets the prompt without it and can fix the file at leisure.
    try:
        from pathlib import Path
        from jaeger_os.personality import compose_block
        from jaeger_os.personality.character import active_character
        # Trait-driven: the active character's HEXACO/SPECIAL/Expression/Domains
        # sliders, rendered into prose ("medium-high sarcasm", ...).
        ch = active_character(Path(ctx.layout.root))
        return (compose_block(ch.personality) or "") if ch is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def _active_char(ctx: "FragmentContext") -> "Any":
    try:
        from pathlib import Path
        from jaeger_os.personality.character import active_character
        return active_character(Path(ctx.layout.root))
    except Exception:  # noqa: BLE001
        return None


def _identity_fragment(ctx: "FragmentContext") -> str:
    ch = _active_char(ctx)
    return ch.identity_block() if ch is not None else ""


def _soul_fragment(ctx: "FragmentContext") -> str:
    ch = _active_char(ctx)
    return ch.soul_block() if ch is not None else ""


# ── the registry: order here IS the prompt order ──────────────────────
PROMPT_FRAGMENTS: list[PromptFragment] = [
    PromptFragment(
        "three_laws", "safety", "agent/prompts/three_laws.md",
        _three_laws, _all,
        "inviolable safety contract — first thing the model sees, every mode",
    ),
    PromptFragment(
        "subagent_preamble", "framework", "(generated)",
        lambda c: _SUBAGENT_PREAMBLE, _subagent_only, "sub-agents only",
    ),
    PromptFragment(
        "subagent_task", "instance", "(caller-supplied goal)",
        lambda c: f"Task:\n{c.goal.strip()}" if c.goal else "",
        _subagent_only, "sub-agents, when a goal is supplied",
    ),
    PromptFragment(
        "subagent_context", "instance", "(caller-supplied context)",
        lambda c: f"Context:\n{c.context.strip()}" if c.context else "",
        _subagent_only, "sub-agents, when context is supplied",
    ),
    PromptFragment(
        "identity", "instance", "<active character>",
        _identity_fragment, _all,
        "who this agent is — every mode",
    ),
    PromptFragment(
        "soul", "instance", "<active character>",
        _soul_fragment, _non_subagent,
        "voice / persona — skipped for sub-agents",
    ),
    PromptFragment(
        "personality", "instance", "<active character>",
        _personality_block, _non_subagent,
        "trait-driven persona block from the active character",
    ),
    PromptFragment(
        "framework", "framework", "agent/prompts/framework_agent.md",
        lambda c: load_framework_prompt(), _all,
        "standing framework instructions — every mode",
    ),
    PromptFragment(
        "skill_index", "dynamic", "(generated: skill library)",
        lambda c: build_skill_index_block(), _non_subagent,
        "available playbooks — skipped for sub-agents",
    ),
    PromptFragment(
        "v2_contract", "instance", "agent/prompts/agent_system_prompt.md",
        lambda c: load_v2_self_improvement(c.layout), _agent_only,
        "self-improvement contract — main agent only, config-gated",
    ),
    PromptFragment(
        "runtime_tail", "dynamic", "(generated: toolset scoping)",
        lambda c: build_runtime_tail(), _all,
        "scoped vs. unscoped tool-surface note — every mode",
    ),
    PromptFragment(
        "board_digest", "dynamic", "(generated: kanban board)",
        lambda c: build_board_block(c.layout), _non_subagent,
        "actionable cards — skipped for sub-agents",
    ),
    PromptFragment(
        "tool_catalog", "dynamic", "(generated: toolset catalog)",
        lambda c: build_toolset_catalog(), _all,
        "loadable toolsets, under lean-surface scoping",
    ),
]


def iter_fragments(
    layout: InstanceLayout,
    *,
    mode: PromptMode = "agent",
    goal: str = "",
    context: str = "",
) -> list[tuple[PromptFragment, str]]:
    """Render every applicable fragment. Returns ``(fragment, text)`` pairs
    for fragments that apply to ``mode`` and produced non-empty text.

    The single source of truth for what the model receives — used by both
    :func:`assemble_prompt` and the ``jaeger prompt show`` inspector.
    """
    ctx = FragmentContext(layout=layout, mode=mode, goal=goal, context=context)
    rendered: list[tuple[PromptFragment, str]] = []
    for frag in PROMPT_FRAGMENTS:
        if not frag.include(mode):
            continue
        try:
            text = (frag.build(ctx) or "").strip()
        except Exception:  # noqa: BLE001 — a broken fragment must never crash boot
            text = ""
        if text:
            rendered.append((frag, text))
    return rendered


def assemble_prompt(
    layout: InstanceLayout,
    *,
    mode: PromptMode = "agent",
    goal: str = "",
    context: str = "",
) -> str:
    """Build a system prompt for ``mode`` from the fragment registry.

    The Three Laws is fragment #1, so it leads every assembled prompt. See the
    module docstring for what each mode includes / excludes. ``goal`` and
    ``context`` are only consulted in ``"subagent"`` mode.
    """
    return "\n\n".join(
        text for _, text in iter_fragments(
            layout, mode=mode, goal=goal, context=context,
        )
    )


__all__ = [
    "assemble_prompt",
    "iter_fragments",
    "PromptFragment",
    "FragmentContext",
    "PromptMode",
    "PROMPT_FRAGMENTS",
]
