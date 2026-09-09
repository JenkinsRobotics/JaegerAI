# JaegerAI documentation

Start here for the current product and its repository. Existing package and
integration documents stay beside the code they describe; this index links to
them without creating another copy.

## Product and operation

| Document | Purpose |
| --- | --- |
| [Project README](../README.md) | Installation and product overview |
| [Commands](../COMMANDS.md) | Operator CLI reference |
| [Daily-driver foundation](DAILY_DRIVER_FOUNDATION.md) | Standalone ownership, reliability boundaries, and daily checks |
| [Product identity](PRODUCT_IDENTITY.md) | Product scope and ownership |
| [Shared WebUI profiles](HERMES_SHARED_PROFILES.md) | Direct agent profiles and Roundtable; see integration status for current transport limitations |
| [Integration status](../integrations/hermes_webui/RELEASE_PROGRESS.md) | Implemented, verified, and pending integration work |
| [Security](../SECURITY.md) | Security guidance |
| [Changelog](../CHANGELOG.md) | Release history |
| [Repair log](../FIXES.md) | Dated operational repairs |

## Architecture and implementation

| Document | Purpose |
| --- | --- |
| [Architecture decisions](architecture/adr/) | ADRs and ownership boundaries |
| [Architecture status](architecture/master-build-status.md) | Architecture implementation record; check its date |
| [JaegerAgent](../packages/jaeger-agent/README.md) | Reusable agent package |
| [JaegerOS](../packages/jaeger-os/README.md) | Runtime foundation |
| [Generated agent contract](../jaeger_ai/docs/agent_contract.md) | Generator-owned reference shipped as package data |
| [WebUI integration](../integrations/hermes_webui/README.md) | Pinned frontend and Jaeger-owned compatibility layer |
| [Workspace integration](../integrations/agent_workspaces/README.md) | Deployment mounts and container identities |

## Development

- [Developer documentation](../dev/docs/README.md): engineering areas, plans, audits, and history.
- [Operator scripts](../scripts/README.md) and [developer scripts](../dev/scripts/README.md).
- [Pipeline probes](../dev/pipelines/README.md) and [pipeline diagrams](../dev/infographic/README.md).
- [Repository triage](../dev/docs/reality/REPOSITORY_TRIAGE_2026_09_08.md): structure, dependencies, and cleanup decisions.

## Where new documentation belongs

User and architecture guides belong in `docs/`; engineering investigations and
dated audits belong in `dev/docs/`; historical snapshots belong in
`dev/docs/history/`. Package-distributed/generated documents remain in
`jaeger_ai/docs/`, and component-specific contracts remain with their package or
integration. Root entry documents and `docs/index.html` retain their existing
paths. Check dates and implementation evidence before treating a plan or old
verification result as current behavior.
