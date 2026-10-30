"""Built-in JaegerAI production roadmap — every phase of work, as goals.

These are the phases of turning JaegerAI into a production-grade, public-facing
AI agent platform. They seed as durable goals under a single
``"JaegerAI Production"`` project so the operator can see, track, and assign
work against them. Each phase carries a ``tool_bundle`` cap so an agent
assigned to a phase can only reach the tools that phase needs.

The roadmap is the DEFAULT seed — it captures the phases when the operator has
not declared their own ``[[operator.projects]]`` tables. Operator-declared
projects always win and seed in addition to (never instead of) this roadmap,
because the roadmap IS the product's own backlog.
"""

from __future__ import annotations

from typing import Any

#: The JaegerAI production roadmap as a project with phased goals.
#: Each phase: title, objective, tool_bundle, success_criteria.
ROADMAP_PROJECT: dict[str, Any] = {
    "name": "JaegerAI Production",
    "objective": (
        "Transform JaegerAI from a personal project into a universal, "
        "public-facing, production-grade AI agent platform."
    ),
    "phases": [
        {
            "title": "Phase 1 — Universal/Public-Facing Cleanup",
            "objective": (
                "Remove all hardcoded personal references; make operator "
                "name, channels, NAS paths, and preferences configurable."
            ),
            "tool_bundle": "goals",
            "success_criteria": "0 personal references in runtime code; operator_config.py drives all prompts.",
        },
        {
            "title": "Phase 2 — Feature Deprecation & Migration Docs",
            "objective": (
                "Archive parked/non-stack features (finance, roundtable, "
                "caldav, insta360, oidc, passkeys, etc.) with migration guides."
            ),
            "tool_bundle": "goals",
            "success_criteria": "10 features deprecated; docs/migration/ has guides; no core imports of archived features.",
        },
        {
            "title": "Phase 3 — Scheduler Consolidation",
            "objective": (
                "Unify the legacy CronRunner and DurableTaskManager into one "
                "UnifiedScheduler; migrate existing schedules on first boot."
            ),
            "tool_bundle": "goals",
            "success_criteria": "One scheduler API; migration runs automatically; schedules survive upgrade.",
        },
        {
            "title": "Phase 4 — Modern Testing Architecture",
            "objective": (
                "Replace the 10-tier test system with 4 focused tiers: "
                "contracts, properties, trajectories, acceptance."
            ),
            "tool_bundle": "goals",
            "success_criteria": "4-tier runner; contract + property + trajectory tests green; CI matrix updated.",
        },
        {
            "title": "Phase 5 — Goal-Aligned AI Tools",
            "objective": (
                "Operator-declared goals/projects with tool-bundle caps; "
                "robotics build/deploy, NAS backup, content pipeline, "
                "morning briefing tools; operator.toml reaches the prompt."
            ),
            "tool_bundle": "goals",
            "success_criteria": "GoalService + goal_* tools shipped; bundles enforced at turn admission; prompt fragment wired.",
        },
        {
            "title": "Phase 6 — Apple-Native UI (V3)",
            "objective": (
                "Empty-default roster for new customers; one concept per word "
                "(Active/Lead/Pinned/Persona/Status); dashboard as operator HQ "
                "with Active Projects and real progress."
            ),
            "tool_bundle": "goals",
            "success_criteria": "No fabricated agents; lead/star/pin distinction correct; dashboard shows real project progress.",
        },
        {
            "title": "Phase 7 — Living Avatar Scenes",
            "objective": (
                "Shared character-scene component: layered 2D scenes driven by "
                "Gateway presence + real TTS; status actions override ambient; "
                "per-character scene packs; sidebar icon stays simple."
            ),
            "tool_bundle": "goals",
            "success_criteria": "One desk scene + one robot workbench on the same controller; verified in the real Mac shell.",
        },
        {
            "title": "Phase 8 — Robotics Project Tooling",
            "objective": (
                "robotics_build / robotics_deploy / nas_backup tools scoped to "
                "a project workspace, with approval gates on deploy."
            ),
            "tool_bundle": "robotics.build",
            "success_criteria": "Build runs scoped + structured pass/fail; deploy gated by approval; backup verifies checksum.",
        },
        {
            "title": "Phase 9 — Content Pipeline (YouTube Studio)",
            "objective": (
                "content_pipeline tool: script → roughcut → publish checklist, "
                "reusing the configurable channel config."
            ),
            "tool_bundle": "content",
            "success_criteria": "One pipeline step runs end-to-end against a configured channel.",
        },
        {
            "title": "Phase 10 — Release 0.13.0 & CI",
            "objective": (
                "Bump version, changelog, README badge; CI matrix on the 4 "
                "test tiers; verify.sh green end-to-end."
            ),
            "tool_bundle": "goals",
            "success_criteria": "v0.13.0 tagged; CI green on contracts/properties/trajectories; verify.sh passes.",
        },
    ],
}


def roadmap_projects() -> tuple[dict[str, Any], ...]:
    """Return the built-in roadmap as a tuple of project tables, suitable
    for :meth:`GoalService.seed_from_config`."""
    return (ROADMAP_PROJECT,)


__all__ = ["ROADMAP_PROJECT", "roadmap_projects"]
