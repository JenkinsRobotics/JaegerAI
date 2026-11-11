# JaegerAI documentation

The current product definition is [`PRODUCT.md`](PRODUCT.md). Read it before
starting release-path work or writing another plan. The stack is in
[`STACK.md`](STACK.md), on-device trust in [`TRUST.md`](TRUST.md), and the
proactive / world-model paper library in `research/README.md`.

Operator instructions live in the root [README](../README.md); contributor workflow lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Current documents

| Document | Classification | Purpose |
| --- | --- | --- |
| [PRODUCT.md](PRODUCT.md) | CURRENT AUTHORITATIVE | Product definition: standalone intelligence, companion + operator |
| [STACK.md](STACK.md) | CURRENT REFERENCE | Stack layers and dependencies |
| [TRUST.md](TRUST.md) | CURRENT REFERENCE | On-device trust boundaries |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | CURRENT AUTHORITATIVE | Public capability / provider contracts |
| [getting-started.md](getting-started.md) | CURRENT REFERENCE | First-run path |
| [CLEANUP.md](CLEANUP.md) | RECORD | 2026-10-22 cleanup ledger |
| [REBUILD.md](REBUILD.md) | RECORD | 2026-10-22 rebuild notes |
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Topology and ownership |
| [architecture/MAIN_LOOP.md](architecture/MAIN_LOOP.md) | CURRENT AUTHORITATIVE | One Gateway turn path |
| [architecture/STRUCTURE.md](architecture/STRUCTURE.md) | CURRENT REFERENCE | Directory map |
| [architecture/TEST_ARCHITECTURE.md](architecture/TEST_ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Test tiers |
| [architecture/THREAT_MODEL.md](architecture/THREAT_MODEL.md) | CURRENT AUTHORITATIVE | Threat model |

## Removed as unnecessary (2026-11-09, 2026-11-11)

Stale plans, comparison essays, and dated status handoffs were deleted from the
active tree so they stop competing with PRODUCT.md. Git history still has them.

Removed examples: `AGENT_*_PLAN*.md`, `MASTER_IMPLEMENTATION_PLAN.md`,
`STATUS-2026-11-01.md`, `RELEASE_AUDIT_2026-11-01.md`, UI comparison essays,
`WEBUI_PRODUCTION_PLAN.md`, `IDE_AGENT_PROMPT.md`, and similar dated ledgers.

Component docs stay with their code: [JaegerAgent](../packages/jaeger-agent/README.md),
[JaegerOS](../packages/jaeger-os/README.md),
[WebUI](../jaeger_ai/features/webui/README.md),
[IDE client](../jaeger_ai/interfaces/ide/README.md),
and [jaeger_ai/modules/MODULES.md](../jaeger_ai/modules/MODULES.md).

On 2026-11-11 every remaining document that no code, build, install step or
test relies on (release records, ADRs, migration notes, integration catalogs,
folder READMEs, dated reports) was copied out to
`~/Desktop/JaegerAI-repo-cleanup-2026-11-11/` and removed from the tree.

Before adding a file here, prefer a docstring, ADR, test, or commit message.
Status reports go stale in days and then mislead.
