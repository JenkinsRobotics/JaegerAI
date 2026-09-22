# Developer notes

Only notes that code or tests cite as rationale, plus assets used by tooling.
Product and architecture documentation is in [`docs/`](../../docs/README.md).

| Path | Why it exists |
| --- | --- |
| [reality/persona_compiler.md](reality/persona_compiler.md) | Measured basis for persona compilation; cited by `jaeger_agent/prompts/assemble.py` and three prompt tests |
| [roadmap/PERSONA_PIPELINE_ABC_DESIGN.md](roadmap/PERSONA_PIPELINE_ABC_DESIGN.md) | Design behind Persona Mode C; cited by `jaeger_agent/prompts/persona_lane.py` |
| [skills/SKILL_TREE.md](skills/SKILL_TREE.md) | XP-progression contract; cited by `jaeger_os/contract/topics.py` and the animation nodes |
| [core/SELF_MODIFICATION_BOUNDARIES.md](core/SELF_MODIFICATION_BOUNDARIES.md) | Safety limits on the agent editing its own code |
| [roadmap/future_backlog.md](roadmap/future_backlog.md) | Backlog referenced from `jaeger_agent/tools/reflect.py` |
| [library_review/mochi_demo.md](library_review/mochi_demo.md) | Animation adapter reference, cited from the adapter docstrings |
| `skill_template/` | Scaffolding copied when authoring a skill — an asset, not a document |

Release history is in [CHANGELOG.md](../../CHANGELOG.md). Decisions belong in
[docs/architecture/adr/](../../docs/architecture/adr/). Dated status reports,
phase plans, and handoff notes do not belong here; they stop being true within
days and then mislead whoever reads them next.
