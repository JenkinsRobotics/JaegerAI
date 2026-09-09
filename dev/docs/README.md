# Developer documentation

The [main documentation index](../../docs/README.md) covers product operation,
architecture, and package references. This directory holds engineering notes,
plans, audits, and history. Dated records are evidence from that date, not a
claim that every described feature is currently deployed.

## Current reference and audits

| Document | Purpose |
| --- | --- |
| [Repository triage](reality/REPOSITORY_TRIAGE_2026_09_08.md) | Complete top-level inventory, dependency mapping, cleanup decisions |
| [Stability cleanup](reality/STABILITY_CLEANUP_2026_09_08.md) | Lifecycle/recovery fixes and live verification |
| [Upstream integration audit](reality/UPSTREAM_INTEGRATION_AUDIT_2026_09_08.md) | Shared WebUI and external-runtime boundaries |
| [Runtime/state boundary](reality/system_runtime_user.md) | Source versus operator state |
| [Status history](reality/STATUS.md) | Accumulated implementation and verification records |
| [Pipeline reference](pipelines/README.md) | Agent, memory, skills, voice, transport, and permissions |
| [Packaged agent contract](../../jaeger_ai/docs/agent_contract.md) | Generator-owned reference; kept in the package for distribution |

## Engineering areas

| Directory | Contents |
| --- | --- |
| [core/](core/) | Agent loop, tools, context, memory, and execution notes |
| [audio/](audio/) | Voice pipeline designs and reviews |
| [avatar/](avatar/) | Animation and UI plans |
| [skills/](skills/) | Skill formats, sharing, and evolution |
| [roadmap/](roadmap/) | Proposed and unfinished work |
| [reality/](reality/) | Runtime reference, status, and audits |
| [revision_summaries/](revision_summaries/README.md) | Release-by-release summaries |
| [library_review/](library_review/) | Upstream/library research and reference code |
| [skill_template/](skill_template/SKILL.md) | Skill authoring template |
| [history/](history/) | Preserved historical snapshots; not current specifications |

## Related developer resources

- [Developer scripts](../scripts/README.md) and [automated tests](../tests/).
- [Manual pipeline probes](../pipelines/README.md) and [diagrams](../infographic/README.md).
- [Benchmarks](../benchmark/) and [evaluation samples](../evals/).
- [Audio smoke probes](../tools/audio_smoke/README.md).
- [Design reference images](../reference_ui/): retained reference assets; current runtime use was not established.
- [JaegerOS ecosystem vision](../../packages/jaeger-os/dev/docs/vision/README.md).

The previous index described absent history, hardware, infra, and archive trees.
Its original content is preserved in the Desktop structural-cleanup archive;
this index lists the directories present in this checkout. Existing engineering
files were not deleted because an older index failed to mention them.
