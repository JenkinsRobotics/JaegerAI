# Developer notes

Only notes that code or tests cite as rationale, plus assets used by tooling.
Product and architecture documentation is in [`docs/`](../../docs/README.md).
The current execution entry point is
[`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md).

| Path | Classification | Why it exists |
| --- | --- | --- |
| [core/SELF_MODIFICATION_BOUNDARIES.md](core/SELF_MODIFICATION_BOUNDARIES.md) | CURRENT REFERENCE | Safety limits on the agent editing its own code |
| [reality/persona_compiler.md](reality/persona_compiler.md) | CURRENT REFERENCE | Measured basis for persona compilation, cited by prompt code and tests |
| [roadmap/PERSONA_PIPELINE_ABC_DESIGN.md](roadmap/PERSONA_PIPELINE_ABC_DESIGN.md) | HISTORICAL | Code-cited Mode C design record; not an active sprint |
| [skills/SKILL_TREE.md](skills/SKILL_TREE.md) | CURRENT REFERENCE | XP-progression contract cited by JaegerOS topics and animation nodes |
| [roadmap/future_backlog.md](roadmap/future_backlog.md) | BACKLOG / DEFERRED | Deferred ideas cited by reflection tooling; not current release scope |
| [library_review/mochi_demo.md](library_review/mochi_demo.md) | HISTORICAL | Animation adapter donor review |
| `skill_template/` | Asset | Scaffolding copied when authoring a skill |

Release history is in [CHANGELOG.md](../../CHANGELOG.md). Decisions belong in
[docs/architecture/adr/](../../docs/architecture/adr/). Dated status reports
and handoff notes do not belong here; they go stale in days and mislead the
next agent.
