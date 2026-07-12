"""Agent-callable diagnostics — the agent's own doctor.

``self_check()`` runs the SAME doctor as the user-facing ``jaeger doctor``
(see :func:`jaeger_os.core.diagnostics.run_doctor`): dependency + config
checks AND the runtime substrate probe (memory round-trip, sandbox, tool
registry, skills, drift parser), with ``deep=True`` adding live-agent
turns. One engine, two surfaces — this is the agent-facing one, the CLI
is the user-facing one.

This pairs with ``run_benchmark`` (the agent's self-benchmark): the agent
can verify *both* that its substrate is healthy (``self_check``) and that
its answers are still good (``run_benchmark``).

Tier: READ_ONLY. The probe writes a tiny throwaway file under ``skills/``
and a throwaway memory key, both immediately cleaned up. No external
effects — safe anytime, including from cron.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function


def self_check(deep: bool = False) -> dict[str, Any]:
    """Run the agent's doctor on the live instance.

    ``deep=False`` (default) — dependency/config checks + the fast
    substrate probes (layout, sandbox, memory round-trip, time,
    calculate, tool registry, skills, drift parser). Under a few
    seconds; does not call the LLM.

    ``deep=True`` — also drives three live-agent turns (free-text
    answer, a read-only tool call, a sandbox write+read) so the result
    reflects "the agent can actually answer", not just "the substrate
    is healthy". Slower — each turn pays the model's per-turn cost.

    Returns ``{ok, passed, total, deep, checks: [...], failures: [...]}``.
    ``ok`` is True only when every check passed.
    """
    from jaeger_ai.core import context as _tcommon
    from jaeger_ai.core.diagnostics import doctor_summary
    layout = getattr(_tcommon, "_layout", None)
    return doctor_summary(layout, deep=bool(deep))


__all__ = ["self_check"]


@register_tool_from_function(name="self_check")
def _t_self_check(deep: bool = False) -> dict:
    """Run the agent's doctor — the SAME engine as ``jaeger doctor``:
    deps + config + the runtime substrate (memory round-trip, tool
    registry, skills, drift parser). ``deep=True`` also drives a few
    live-agent turns to confirm the agent can actually answer, not
    just that the substrate is healthy. Pairs with ``run_benchmark``
    (substrate health vs. answer quality). See
    ``describe_tool("self_check")`` for the full contract."""
    return self_check(deep=deep)
