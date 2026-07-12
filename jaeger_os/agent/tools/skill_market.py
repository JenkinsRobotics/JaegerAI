"""Skill-lifecycle tools — beyond authoring.

  • package_skill(name)    — bundle an instance skill into a portable
                             artifact (the marketplace foundation)
  • benchmark_skill(name)  — run a skill's scored benchmark, track the
                             delta vs. its last run

``submit_skill`` / ``search_skill`` / ``install_skill`` are deferred
until the marketplace GitHub repo exists — see docs/marketplace_spec.md
for the full plan + the remaining checklist.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.context import _require_layout
from jaeger_os.agent.skill_registry.skill_benchmark import benchmark_skill as _benchmark_skill
from jaeger_os.agent.skill_registry.skill_package import package_skill as _package_skill


def package_skill(name: str) -> dict[str, Any]:
    """Bundle a skill you built into a portable, shareable artifact.

    Takes a skill folder from ``<instance>/skills/`` and produces a
    ``.zip`` under ``<instance>/packaged_skills/`` with a generated
    ``skill_manifest.json`` (name, version, author, dependencies,
    smoke-test status, integrity hash).

    Use this once a skill is proven and you'd want to share it. The
    bundle is self-contained — it can be installed on any Jaeger-OS
    instance. Publishing it to the marketplace is a later step
    (``submit_skill``, not yet available — the marketplace repo doesn't
    exist yet; see docs/marketplace_spec.md).

    Returns ``{ok, skill, version, package_path, smoke_test, manifest}``
    or ``{ok: False, error: ...}``."""
    layout = _require_layout()
    return _package_skill(layout, name)


def benchmark_skill(name: str) -> dict[str, Any]:
    """Run a skill's scored benchmark and track its improvement.

    A skill can carry ``tests/benchmark.py`` alongside its smoke test —
    a script that prints one JSON object with a ``score`` (0.0-1.0).
    This runs it, appends the result to the skill's benchmark history,
    and reports the ``delta`` vs. the previous run.

    Use this when revising a skill: benchmark the old version, write the
    new one, benchmark again — ``delta > 0`` means the revision actually
    helped. Same principle as the repo's level benchmarks, scoped to one
    skill. See docs/skill_template/tests/benchmark.py for the template.

    Returns ``{ok, skill, score, passed, total, previous_score, delta,
    improved, cases}`` or ``{ok: False, error: ...}``."""
    layout = _require_layout()
    return _benchmark_skill(layout, name)


# ---------------------------------------------------------------------------
# Agent-facing tool wrappers (migrated from main._register_builtins).
# ---------------------------------------------------------------------------
@register_tool_from_function(name="package_skill", beta=True)
def _t_package_skill(name: str) -> dict:
    """Bundle a skill you built into a portable, shareable .zip with
    a generated manifest (name, version, deps, smoke-test status).
    Use this once a skill is proven and worth sharing. The bundle
    installs on any Jaeger-OS instance. Publishing it to the
    marketplace is a later step (the marketplace repo isn't live
    yet — see docs/marketplace_spec.md)."""
    return package_skill(name=name)


@register_tool_from_function(name="benchmark_skill", beta=True)
def _t_benchmark_skill(name: str) -> dict:
    """Run a skill's scored benchmark (tests/benchmark.py) and track
    the delta vs. its last run. Use this when revising a skill:
    benchmark the old version, write the new one, benchmark again —
    `delta > 0` proves the revision helped. Same principle as the
    repo's level benchmarks, scoped to one skill."""
    return benchmark_skill(name=name)
