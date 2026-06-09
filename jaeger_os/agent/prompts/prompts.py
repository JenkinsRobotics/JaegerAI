"""Thin back-compat shim — assembly lives in ``assemble.py``.

Pre-consolidation, this module held the constants, the dynamic
block builders, and the assembly function. It now re-exports those
from their new homes so any external caller that imports from
``jaeger_os.agent.prompts.prompts`` keeps working unchanged:

    from jaeger_os.agent.prompts import build_system_prompt          # preferred
    from jaeger_os.agent.prompts.prompts import build_system_prompt  # legacy ok

The Core / Safety / Instance split is:

    core/prompts/rules.py          — behavioural string constants
    core/prompts/context_blocks.py — dynamic blocks reading live state
    core/prompts/assemble.py       — single assemble_prompt() entry
    core/prompts/synthetic.py      — mid-conversation user-role messages
    core/safety/safety_rules.py    — Three Laws wrap
    instance/<name>/{identity,soul,config} — per-instance overrides

New code should import directly from ``jaeger_os.agent.prompts``
(re-exports the public surface) — this file exists only so a
``from .prompts import …`` somewhere we haven't migrated yet
doesn't break.
"""

from __future__ import annotations

from jaeger_os.core.instance.instance import InstanceLayout

# Re-exports — preserve every public name the old module exposed.
from .assemble import assemble_prompt as _assemble  # noqa: F401
from .context_blocks import (  # noqa: F401
    build_runtime_tail as _runtime_tail,
    build_skill_index_block,
    build_toolset_catalog as _build_toolset_catalog,
    load_soul as _load_soul,
)
from .rules import (  # noqa: F401
    JAEGER_OS_CONTEXT,
    MANDATORY_TOOL_RULES,
    OPERATING_DISCIPLINE,
    RUNTIME_TAIL_BASE,
    RUNTIME_TOOLSET_SCOPED,
    RUNTIME_TOOLSET_UNSCOPED,
)


def build_system_prompt(layout: InstanceLayout) -> str:
    """Assemble the live-agent system prompt. Back-compat shim — new
    code should call :func:`jaeger_os.agent.prompts.assemble_prompt`
    with an explicit ``mode``."""
    return _assemble(layout, mode="agent")


__all__ = [
    "JAEGER_OS_CONTEXT",
    "MANDATORY_TOOL_RULES",
    "OPERATING_DISCIPLINE",
    "RUNTIME_TAIL_BASE",
    "RUNTIME_TOOLSET_SCOPED",
    "RUNTIME_TOOLSET_UNSCOPED",
    "build_system_prompt",
]
