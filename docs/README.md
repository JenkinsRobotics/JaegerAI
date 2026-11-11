# JaegerAI documentation

The current product definition is [`PRODUCT.md`](PRODUCT.md). Read it before
starting release-path work or writing another plan. The stack is in
[`STACK.md`](STACK.md), on-device trust in [`TRUST.md`](TRUST.md), and the
proactive / world-model paper library in [`research/README.md`](research/README.md).

Operator instructions live in the root [README](../README.md) and
[COMMANDS.md](COMMANDS.md); contributor workflow lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Current documents

| Document | Classification | Purpose |
| --- | --- | --- |
| [PRODUCT.md](PRODUCT.md) | CURRENT AUTHORITATIVE | Product definition: standalone intelligence, companion + operator |
| [STACK.md](STACK.md) | CURRENT REFERENCE | Stack layers and dependencies |
| [TRUST.md](TRUST.md) | CURRENT REFERENCE | On-device trust boundaries |
| [STANDALONE_FOUNDATIONS.md](STANDALONE_FOUNDATIONS.md) | CURRENT REFERENCE | Standalone app, model passport, IDE host LM bridge |
| [COMMANDS.md](COMMANDS.md) | CURRENT REFERENCE | Operator CLI |
| [OPERATIONS.md](OPERATIONS.md) | CURRENT REFERENCE | State roots, upgrades, health |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | CURRENT AUTHORITATIVE | Public capability / provider contracts |
| [getting-started.md](getting-started.md) | CURRENT REFERENCE | First-run path |
| [CHAT_ORGANIZATION.md](CHAT_ORGANIZATION.md) | CURRENT REFERENCE | Projects and conversation organization |
| [CHAT_STREAM_PARITY.md](CHAT_STREAM_PARITY.md) | CURRENT REFERENCE | Stream / stop parity across clients |
| [gateway-task-ownership.md](gateway-task-ownership.md) | CURRENT REFERENCE | Gateway-owned durable background work |
| [BRANCH_RETIREMENT_2026-11-08.md](BRANCH_RETIREMENT_2026-11-08.md) | RECORD | Retired branch archive map |
| [RELEASE_0.13.md](RELEASE_0.13.md) | RELEASE RECORD | 0.13.0 qualification |
| [RELEASE_NOTES_v0.13.0.md](RELEASE_NOTES_v0.13.0.md) | RELEASE RECORD | 0.13.0 notes |
| [CLEANUP.md](CLEANUP.md) | RECORD | 2026-10-22 cleanup ledger |
| [REBUILD.md](REBUILD.md) | RECORD | 2026-10-22 rebuild notes |
| [research/README.md](research/README.md) | CURRENT REFERENCE | Proactive / world-model paper library |
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Topology and ownership |
| [architecture/MAIN_LOOP.md](architecture/MAIN_LOOP.md) | CURRENT AUTHORITATIVE | One Gateway turn path |
| [architecture/PRODUCTION_PATHS.md](architecture/PRODUCTION_PATHS.md) | CURRENT AUTHORITATIVE | Production runtime path |
| [architecture/STATE_OWNERSHIP_MAP.md](architecture/STATE_OWNERSHIP_MAP.md) | CURRENT AUTHORITATIVE | One owner per fact |
| [architecture/STRUCTURE.md](architecture/STRUCTURE.md) | CURRENT REFERENCE | Directory map |
| [architecture/TEST_ARCHITECTURE.md](architecture/TEST_ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Test tiers |
| [architecture/THREAT_MODEL.md](architecture/THREAT_MODEL.md) | CURRENT AUTHORITATIVE | Threat model |
| [architecture/DONOR_PROVENANCE.md](architecture/DONOR_PROVENANCE.md) | CURRENT REFERENCE | Donor licenses |
| [architecture/MODEL_REQUEST_STABILIZATION.md](architecture/MODEL_REQUEST_STABILIZATION.md) | CURRENT REFERENCE | Model request policy |
| [architecture/adr/](architecture/adr/) | CURRENT REFERENCE | Accepted ADRs |
| [integration/TOOL_DISCOVERY.md](integration/TOOL_DISCOVERY.md) | CURRENT REFERENCE | Tool discovery |
| [integration/CHAT_ACTIVITY_CATALOG.md](integration/CHAT_ACTIVITY_CATALOG.md) | CURRENT REFERENCE | Chat activity catalog |
| [migration/](migration/) | CURRENT REFERENCE | Operator migration notes |

## Removed as unnecessary (2026-11-09)

Stale plans, comparison essays, and dated status handoffs were deleted from the
active tree so they stop competing with PRODUCT.md. Git history still has them.

Removed examples: `AGENT_*_PLAN*.md`, `MASTER_IMPLEMENTATION_PLAN.md`,
`STATUS-2026-11-01.md`, `RELEASE_AUDIT_2026-11-01.md`, UI comparison essays,
`WEBUI_PRODUCTION_PLAN.md`, `IDE_AGENT_PROMPT.md`, and similar dated ledgers.

Component docs stay with their code: [JaegerAgent](../packages/jaeger-agent/README.md),
[JaegerOS](../packages/jaeger-os/README.md),
[WebUI](../jaeger_ai/features/webui/README.md),
[Mac menu bar shell](../jaeger_ai/interfaces/macos-shell/REUSE.md),
[IDE client](../jaeger_ai/interfaces/ide/README.md),
and [jaeger_ai/modules/MODULES.md](../jaeger_ai/modules/MODULES.md).

Before adding a file here, prefer a docstring, ADR, test, or commit message.
Status reports go stale in days and then mislead.
