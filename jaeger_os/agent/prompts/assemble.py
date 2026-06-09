"""The single assembly entry point for every prompt-building path.

Before consolidation, FIVE codepaths built the agent's system prompt:
the main turn, sub-agent delegation, Deep Think, the idle-board
worker, and cron. Each had its own assembly logic; rules drifted
between them. This module is the single source of truth: every
codepath now calls :func:`assemble_prompt` with a ``mode``.

Modes:

  * ``"agent"``      — the live TUI turn. Full prompt: identity +
    runs-on-Jaeger + soul + rules + skill index + (optional v2
    contract) + runtime tail + board digest + tool catalog.
  * ``"subagent"``   — a delegated child. Same scaffold MINUS the
    board digest and v2 contract (the child is task-scoped; the
    parent owns the standing TODO list). Caller supplies ``goal``
    and optional ``context`` which become the child's task brief.
  * ``"deep_think"`` — autonomous skill development. Full agent
    prompt; the task brief is the synthetic user-role message, not
    part of the system prompt.
  * ``"idle_board"`` — the idle worker. Identical to ``"agent"``;
    listed as a mode so the call site is self-documenting (the
    diff vs. agent is in the user-role message, not the system
    prompt).
  * ``"cron"``       — a scheduled fire. Same as ``"agent"``; ditto.

All modes get the Three Laws wrap at the end. The wrap is
idempotent so a caller that already wrapped its own prompt (a
nested sub-agent, say) doesn't double the block.
"""

from __future__ import annotations

from typing import Literal

from jaeger_os.core.instance.instance import InstanceLayout

from .context_blocks import (
    build_board_block,
    build_runtime_tail,
    build_skill_index_block,
    build_toolset_catalog,
    load_identity,
    load_soul,
    load_v2_self_improvement,
)
from .rules import (
    JAEGER_OS_CONTEXT,
    MANDATORY_TOOL_RULES,
    OPERATING_DISCIPLINE,
    TOOL_USAGE_RULES,
)


PromptMode = Literal["agent", "subagent", "deep_think", "idle_board", "cron"]


# Subagent-specific opener. Mirrors the hermes upstream pattern but
# uses the same rules/identity scaffold the parent uses, so the child
# isn't a different agent — it's the same agent running on a focused
# brief.
_SUBAGENT_PREAMBLE = (
    "You are a focused sub-agent spawned by the parent Jaeger to "
    "complete a single task. Work the task end-to-end with real tool "
    "calls, then summarise the result so the parent can use it. "
    "Be terse; the parent reads your final message, not your "
    "intermediate thinking."
)


def assemble_prompt(
    layout: InstanceLayout,
    *,
    mode: PromptMode = "agent",
    goal: str = "",
    context: str = "",
) -> str:
    """Build a system prompt for ``mode``. Returns the assembled
    string, wrapped with the Three Laws block.

    See module docstring for what each mode includes / excludes.
    ``goal`` and ``context`` are only consulted in ``"subagent"``
    mode; ignored otherwise.
    """
    parts: list[str] = []

    if mode == "subagent":
        # Child gets a focused brief at the very top so the model
        # treats the rest as backdrop, not the primary instruction.
        parts.append(_SUBAGENT_PREAMBLE)
        if goal:
            parts.append(f"Task:\n{goal.strip()}")
        if context:
            parts.append(f"Context:\n{context.strip()}")

    # Identity — every mode gets it. A sub-agent is still THIS agent;
    # the brief shape, not the identity, differs.
    ident = load_identity(layout)
    if ident:
        parts.append(ident)

    parts.append(JAEGER_OS_CONTEXT.strip())

    # soul.md right after the structured identity so it reads as
    # "...and here is how I speak". Skipped for sub-agents — their
    # task is scoped and the voice doc would just dilute the brief.
    if mode != "subagent":
        soul = load_soul(layout)
        if soul:
            parts.append(soul)

        # 0.5: structured personality block, when present.  Per
        # operator's prior work in Lilith-AI, persisted at
        # <instance>/personality.json with HEXACO + SPECIAL +
        # Expression sliders + knowledge domain weights + speech
        # patterns.  ``compose_block`` turns those structured
        # 0..1 values into language ("very high directness",
        # "moderate sarcasm", etc.).
        try:
            from pathlib import Path
            personality_path = Path(layout.root) / "personality.json"
            if personality_path.exists():
                from jaeger_os.personality import (
                    compose_block,
                    load_personality,
                )
                personality = load_personality(personality_path)
                block = compose_block(personality)
                if block:
                    parts.append(block)
        except Exception:  # noqa: BLE001
            # A broken personality file must NEVER take down the
            # boot — operator gets the legacy identity prompt; they
            # can fix the file at leisure.
            pass

    parts.append(MANDATORY_TOOL_RULES.strip())
    parts.append(OPERATING_DISCIPLINE.strip())
    parts.append(TOOL_USAGE_RULES.strip())

    # Voice-mode LLM gate (opt-in via ``config.voice.llm_gate``).
    # ``voice_loop.py`` exports JAEGER_VOICE_GATE=1 at boot when the
    # config flag is on; we read the env var here so the prompt
    # assembler doesn't have to depend on the voice config schema.
    # Sub-agents skip — they speak through the agent surface, not the
    # mic.
    # Voice-mode LLM gate (opt-in via ``config.voice.llm_gate``).
    #
    # Why this rides the BRAIN's system prompt — not a separate
    # gate call (2026-06-07 perf regression discovered live + bench-
    # confirmed in dev_benchmark/voice_gate_latency.py):
    #
    # We briefly tried a node-owned gate where AudioSession would
    # make a separate ``client.chat()`` call with its own gate prompt
    # to classify phrases before publishing /sense/transcript.  That
    # is architecturally cleaner (node owns its full domain), but
    # llama-cpp uses a SINGLE KV-cache slot — switching between two
    # different system prompts (gate ~800 tokens, brain ~14K tokens)
    # invalidated the prefill each time.  Result: 50× slowdown on
    # voice turns (0.39s warm brain → 19.79s after-gate brain) per
    # `dev_benchmark/voice_gate_latency.py`.
    #
    # The fix matches VoiceLLM's actual approach — single-pass:
    #   * Brain's system prompt carries the gate rule from boot
    #     (this block, when JAEGER_VOICE_GATE=1 at prewarm time)
    #   * Brain's response begins with <ignore> or <reply>
    #   * Voice consumer (TUI / voice_loop) parses the leading tag
    #     and suppresses speech on <ignore>
    #   * Deterministic filters in AudioSession still own their
    #     domain (non-speech markers, self-speech, etc.) — they
    #     reject obvious junk BEFORE it reaches the brain so the
    #     gate only has to decide on borderline cases
    #
    # JAEGER_VOICE_GATE=1 must be set BEFORE build_system_prompt so
    # the rule is baked into the cached prompt at boot — both
    # boot paths in main.py do this; see beee2f6 for the regression
    # this prevents.  voice_loop/voice_session also set it
    # defensively at construction time as a safety net.
    import os as _os
    if mode != "subagent" and _os.environ.get("JAEGER_VOICE_GATE") == "1":
        from .rules import VOICE_LLM_GATE_RULE
        parts.append(VOICE_LLM_GATE_RULE.strip())
        # Active follow-up addressed_hint — strict default-ignore
        # when idle, permissive default-reply when we're inside the
        # follow-up window after a recent reply.  voice_loop /
        # voice_session toggle JAEGER_VOICE_ACTIVE_FOLLOWUP per turn.
        if _os.environ.get("JAEGER_VOICE_ACTIVE_FOLLOWUP") == "1":
            from .rules import VOICE_FOLLOWUP_HINT_RULE
            parts.append(VOICE_FOLLOWUP_HINT_RULE.strip())

    # Skill index — sub-agents don't need it (they were given a
    # specific task; ranging across the skill library would expand
    # scope). Every other mode benefits from knowing what playbooks
    # exist.
    if mode != "subagent":
        skill_block = build_skill_index_block()
        if skill_block:
            parts.append(skill_block)

    # v2 self-improvement contract — opt-in, only the main agent
    # path. Sub-agents and Deep Think have their own narrower
    # contracts (the sub-agent brief; the DT directive).
    if mode == "agent":
        v2 = load_v2_self_improvement(layout)
        if v2:
            parts.append(v2)

    parts.append(build_runtime_tail())

    # Board digest — the standing TODO list. Sub-agents skip it
    # (they have one task); every other mode sees what's actionable.
    if mode != "subagent":
        board = build_board_block(layout)
        if board:
            parts.append(board)

    # Tool catalog only appears under lean-surface scoping. Same
    # filter for every mode — the catalog tells the model what it
    # CAN load, regardless of why it's running.
    catalog = build_toolset_catalog()
    if catalog:
        parts.append(catalog)

    assembled = "\n\n".join(parts)

    # Three Laws — prepended LAST so they're the first thing the
    # model sees. ``with_three_laws`` is idempotent; a nested call
    # that already wrapped its own prompt won't double the block.
    try:
        from jaeger_os.core.safety.safety_rules import with_three_laws
        assembled = with_three_laws(assembled)
    except Exception:  # noqa: BLE001 — never break boot over a safety wrap
        pass
    return assembled


__all__ = ["assemble_prompt", "PromptMode"]
