"""Dynamic prompt blocks — read live state and return a string.

These are the parts of the system prompt that depend on what's
ACTUALLY in the instance right now (which skills exist, what's on
the board, which toolsets are scoped on, what soul.md says). Each
function returns ``""`` when there's nothing to surface, so a quiet
instance pays no prompt-token cost.

Co-located with ``rules.py`` so the entire Core bucket lives in
one folder. The assembly entry point in ``assemble.py`` is the only
place these are called from.
"""

from __future__ import annotations

from pathlib import Path

from jaeger_os.core.instance.instance import InstanceLayout

from .rules import RUNTIME_TAIL_BASE, RUNTIME_TOOLSET_SCOPED, RUNTIME_TOOLSET_UNSCOPED


# ── soul.md ─────────────────────────────────────────────────────────


# Cap soul.md so a long doc can't crowd out the routing imperatives —
# the model attends most to the start of the prompt, and a 10K-char
# soul.md pushed MANDATORY_TOOL_RULES into low-attention territory in
# benchmarks.
_SOUL_MAX_CHARS = 4_000


def load_soul(layout: InstanceLayout) -> str:
    """Read the optional per-instance ``soul.md`` — a free-form voice
    document the user hand-writes. Empty string when absent."""
    try:
        path = layout.root / "soul.md"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — soul.md must never break boot
        return ""
    if len(text) > _SOUL_MAX_CHARS:
        text = text[:_SOUL_MAX_CHARS].rstrip() + "\n…(soul.md truncated)"
    return text


# ── identity blurb ──────────────────────────────────────────────────


def load_identity(layout: InstanceLayout) -> str:
    """The structured identity blurb from ``identity.yaml``. Empty
    string when the memory store can't load it (e.g. fresh instance
    before the wizard ran)."""
    try:
        from jaeger_os.core.memory import memory as mem
        return mem.load_identity_string(layout) or ""
    except Exception:  # noqa: BLE001
        return ""


# ── playbook skill index ────────────────────────────────────────────


def build_skill_index_block() -> str:
    """The compact index of playbook skills the model sees, so it
    knows what specialized procedures exist without a discovery
    round-trip. Empty string when no skills are discovered."""
    try:
        from jaeger_os.core.skills.playbook_skills import build_skill_index
        return build_skill_index() or ""
    except Exception:  # noqa: BLE001 — skill discovery must never break boot
        return ""


# ── toolset catalog (lean-surface only) ─────────────────────────────


def build_toolset_catalog() -> str:
    """A compact tool catalog: every loadable toolset → one-line
    summary. Built-in classes appear first; runtime-registered skill
    toolsets follow. Empty string when scoping is off (the full
    surface is visible and the catalog would just duplicate what the
    adapter already sends)."""
    try:
        from jaeger_os.core.skills.toolsets import (
            _scoping_enabled, all_toolsets, TOOLSET_SUMMARY,
        )
    except Exception:  # noqa: BLE001
        return ""
    if not _scoping_enabled():
        return ""
    rows = all_toolsets()
    if not rows:
        return ""
    builtin = [(k, rows[k]) for k in TOOLSET_SUMMARY if k in rows]
    skills = [(k, v) for k, v in rows.items() if k not in TOOLSET_SUMMARY]
    lines = ["TOOL CATALOG — categories you can describe_tool / load_toolset:"]
    for name, summary in builtin + skills:
        lines.append(f"  • {name:<14} — {summary}")
    return "\n".join(lines)


# ── kanban board digest ─────────────────────────────────────────────


def build_board_block(layout: InstanceLayout) -> str:
    """The standing-TODO digest. Pairs with the KANBAN EXCEPTION rule
    in OPERATING_DISCIPLINE: the rule tells the agent what to do, this
    block tells it what's available to do. Empty when nothing's
    actionable so quiet instances stay quiet."""
    try:
        from jaeger_os.core.background.board import board_digest
        return board_digest(layout) or ""
    except Exception:  # noqa: BLE001
        return ""


# ── runtime tail (with toolset note spliced in) ─────────────────────


def build_runtime_tail() -> str:
    """The file-access + behavior block that closes the static prompt.
    Splices the right toolset note (scoped vs. unscoped) into the
    Behavior section based on the live ``JAEGER_TOOLSET_SCOPING``
    flag — one block instead of two parallel ones, so a rule edit
    in the base block doesn't have to be duplicated."""
    try:
        from jaeger_os.core.skills.toolsets import _scoping_enabled
        scoped = _scoping_enabled()
    except Exception:  # noqa: BLE001
        scoped = False
    note = RUNTIME_TOOLSET_SCOPED if scoped else RUNTIME_TOOLSET_UNSCOPED
    return RUNTIME_TAIL_BASE.strip().replace(
        "Behavior:\n",
        "Behavior:\n" + note.strip() + "\n",
        1,
    )


# ── v2 self-improvement contract (config-gated) ─────────────────────


# The 115-line self-improvement contract used to load every turn.
# It's load-bearing when the agent is authoring skills (versioning,
# rollback, smoke tests) but adds ~900 words otherwise and was
# costing 3/23 on the routing bench. Config-gated via
# ``skills.include_self_improvement_contract``.
_V2_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts" / "agent_system_prompt.md"
)


def load_v2_self_improvement(layout: InstanceLayout) -> str:
    """The opt-in skill-authoring contract. Empty string when the
    config flag is off or the file is missing."""
    try:
        from jaeger_os.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(layout.config_path, Config)
        if not cfg.skills.include_self_improvement_contract:
            return ""
    except Exception:  # noqa: BLE001
        return ""
    if not _V2_CONTRACT_PATH.exists():
        return ""
    try:
        return _V2_CONTRACT_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "build_board_block",
    "build_runtime_tail",
    "build_skill_index_block",
    "build_toolset_catalog",
    "load_identity",
    "load_soul",
    "load_v2_self_improvement",
]
