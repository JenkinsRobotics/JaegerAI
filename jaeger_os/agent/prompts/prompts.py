"""``build_system_prompt`` — the live-agent entry over ``assemble_prompt``.

Prompt assembly is the fragment registry in :mod:`.assemble`. Framework rule
text lives in ``framework_agent.md`` / ``three_laws.md``. This module exposes
the zero-mode convenience entry the main turn calls, plus a few dynamic-block
re-exports kept for callers that still import them from here.
"""

from __future__ import annotations

from jaeger_os.core.instance.instance import InstanceLayout

from .assemble import assemble_prompt as _assemble  # noqa: F401
from .context_blocks import (  # noqa: F401
    build_runtime_tail as _runtime_tail,
    build_skill_index_block,
    build_toolset_catalog as _build_toolset_catalog,
    load_soul as _load_soul,
)
from .rules import RUNTIME_TOOLSET_SCOPED, RUNTIME_TOOLSET_UNSCOPED  # noqa: F401


def build_system_prompt(layout: InstanceLayout) -> str:
    """Assemble the live-agent system prompt (``mode="agent"``). New code
    should call :func:`jaeger_os.agent.prompts.assemble_prompt` directly with
    an explicit mode."""
    return _assemble(layout, mode="agent")


__all__ = [
    "RUNTIME_TOOLSET_SCOPED",
    "RUNTIME_TOOLSET_UNSCOPED",
    "build_skill_index_block",
    "build_system_prompt",
]
