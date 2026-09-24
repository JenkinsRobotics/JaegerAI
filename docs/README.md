# JaegerAI documentation

The current execution entry point is
[`CONTINUE_FROM_HERE.md`](CONTINUE_FROM_HERE.md). Read it before starting
release-path work or writing another plan.

Operator instructions live in the root [README](../README.md) and
[COMMANDS.md](../COMMANDS.md); contributor workflow lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

| Document | Classification | Purpose |
| --- | --- | --- |
| [CONTINUE_FROM_HERE.md](CONTINUE_FROM_HERE.md) | CURRENT AUTHORITATIVE | Current baseline, proven state, remaining work, continuation rules, and document classification |
| [OPERATIONS.md](OPERATIONS.md) | CURRENT REFERENCE | State roots, upgrades, backups, cancellation, retry, and health |
| [gateway-task-ownership.md](gateway-task-ownership.md) | CURRENT REFERENCE | Gateway-owned durable background work |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | CURRENT AUTHORITATIVE | Public capability, provider, and device contracts |
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Topology and ownership, with IMPLEMENTED / EXPERIMENTAL / PLANNED status |
| [architecture/MAIN_LOOP.md](architecture/MAIN_LOOP.md) | CURRENT AUTHORITATIVE | One Gateway turn path |
| [architecture/STATE_OWNERSHIP_MAP.md](architecture/STATE_OWNERSHIP_MAP.md) | CURRENT AUTHORITATIVE | One authoritative owner per fact |
| [architecture/TEST_ARCHITECTURE.md](architecture/TEST_ARCHITECTURE.md) | CURRENT AUTHORITATIVE | What each test tier proves |
| [architecture/THREAT_MODEL.md](architecture/THREAT_MODEL.md) | CURRENT AUTHORITATIVE | Trust domains and mitigations |
| [architecture/DONOR_PROVENANCE.md](architecture/DONOR_PROVENANCE.md) | CURRENT REFERENCE | Donor sources, licenses, and decision records |
| [architecture/adr/](architecture/adr/) | CURRENT REFERENCE | Accepted architectural decisions |
| [architecture/IDE_FIRST_PRODUCT_DIRECTION.md](architecture/IDE_FIRST_PRODUCT_DIRECTION.md) | HISTORICAL | Old IDE product direction and worker requirements |
| [architecture/CAPABILITY_EQUIVALENCE_AUDIT.md](architecture/CAPABILITY_EQUIVALENCE_AUDIT.md) | HISTORICAL | Old capability-equivalence audit |
| [architecture/CODEX_PARITY_BACKLOG.md](architecture/CODEX_PARITY_BACKLOG.md) | BACKLOG / DEFERRED | Selective Codex parity ideas |
| [benchmarks/chronicler-trial.md](benchmarks/chronicler-trial.md) | HISTORICAL | Dated benchmark evidence |

Historical files remain as evidence only. They may reference old dates, branches,
HEADs, dirty worktrees, or acceptance schedules; none of that describes the current
checkout or authorizes skipping current source inspection.

The following stale execution/audit ledgers were removed from the active tree on
2026-09-24; Git history preserves them:

- `docs/architecture/CURRENT_PRODUCT_AUDIT.md`
- `docs/architecture/MASTER_PROGRAM_STATUS.md`
- `docs/architecture/GROK_PERSONAL_RELEASE_PROMPT.md`
- `docs/architecture/RELEASE_AGENT_PROMPT.md`
- `docs/architecture/CONVERGENCE.md`
- `docs/architecture/RELEASE_AUDIT.md`
- `docs/architecture/UI_EXPLORATORY_AGENT_PROMPT.md`

Component docs stay with their code: [JaegerAgent](../packages/jaeger-agent/README.md),
[JaegerOS](../packages/jaeger-os/README.md),
[WebUI](../jaeger_ai/features/webui/README.md), and
[Swift app](../jaeger_ai/interfaces/swift/README.md).

Before adding a file here, check whether it belongs in a docstring, an ADR,
a test, or a commit message instead. Status reports and dated handoffs go
stale in days and then actively mislead.
