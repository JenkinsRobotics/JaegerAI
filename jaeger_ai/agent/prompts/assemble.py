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

from jaeger_ai.core.instance.instance import InstanceLayout

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
    from jaeger_ai.agent.safety import THREE_LAWS_PROMPT_BLOCK

    return THREE_LAWS_PROMPT_BLOCK


# NOTE: there is deliberately NO character/persona fragment here. The persona is
# applied by the two-pass OUTPUT FILTER (re-voicing the final reply), not injected
# into the worker prompt — a 4B's execution degrades ~7% with a character in
# context (measured: dev/docs/reality/persona_compiler.md). Workers run vanilla; the
# character's compiled View (Character.character_block()) feeds the filter, which
# lives in the response path, not prompt assembly.
#
# The one exception is the NAME (below): a name is a fact, not a persona, and
# the output filter's "preserve facts verbatim" rule means it faithfully keeps
# a WRONG name — so the name has to be right at the source. Before this
# fragment the prompt carried no name at all; framework_agent.md's "the
# name/persona above are who you are" pointed at nothing, and "what's your
# name" answered with the framework line ("Jaeger OS") no matter which
# character was active.


def _identity_name(ctx: FragmentContext) -> str:
    """The agent's NAME — identity.yaml's ``name``, ALWAYS.

    The active character NEVER supplies the name: a character is a persona
    (voice + mannerisms, applied by the output filter), while identity.yaml
    is the unique robot the operator named at instance creation — "I might
    want a robot like Jarvis but I will name him Ted; the character prompt
    gives the personality but the unique instance info isn't overwritten"
    (operator, 2026-07-05). The character prompt must never overwrite it.

    Name ONLY: soul/traits/voice stay out of the worker prompt (station 3,
    dev/docs/reality/agentic_runners.md — the measured ~7-point execution tax); the
    persona output filter supplies the voice.

    ``JAEGER_BENCH_NEUTRAL_IDENTITY`` is now a NO-OP kept for bench-runner
    compatibility: it used to force exactly this identity.yaml-only
    behaviour (a character name in the prompt tinted free-text answers —
    the 2026-07-05 free_text_story A/B), which is simply the behaviour
    everywhere now."""
    try:
        from jaeger_ai.core.instance.schemas import Identity, load_yaml
        name = (load_yaml(ctx.layout.identity_path, Identity).name or "").strip()
    except Exception:  # noqa: BLE001 — a broken identity never breaks the prompt
        name = ""
    return f"Your name is {name}." if name else ""


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
        "identity_name", "instance", "(generated: identity.yaml)",
        _identity_name, _non_subagent,
        "the agent's NAME only (never the character's) — persona stays in the output filter",
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
