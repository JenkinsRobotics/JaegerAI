# ADR-0012: Absorb ARES orchestration into JaegerAI

**Status:** Accepted
**Date:** 2026-09-03

## Context

JaegerAI already owns the agent loop, identity, memory, tools, durable runs,
effect ledger, interfaces, and local inference. ARES separately implements
useful external-worker adapters, routing, controller APIs, and evaluation, but
also duplicates parts of its own Python packages between the repository root
and `services/controller`.

Running both products as authorities would leave two task ledgers, two memory
admission paths, and ambiguous ownership of user-visible completion.

## Decision

JaegerAI is the sole product and canonical authority. ARES behavior is ported
in bounded slices. Claude, Codex, Grok, Hermes, OpenClaw, and custom runtimes
are permission-scoped delegates behind `jaeger_agent.delegates`.

ARES is not modified during feature absorption. It remains the behavioral
reference and rollback source until the retirement gates below pass.

Delegate output is untrusted evidence. A delegate cannot directly mutate
Jaeger identity, canonical memory, permissions, commitments, or completion
state. Memory suggestions enter a separate admission path with provenance.

Jaeger's existing SQLite store remains the default local persistence layer.
PostgreSQL/pgvector and a distributed event transport may be added as optional
ports for multi-host deployments; they are not dependencies of a local macOS
installation.

## Porting order

1. Stable delegate contracts, registry, durable lifecycle, and tests.
2. Custom JSON-RPC-over-stdio runtime and process safety boundary.
3. Claude Code, Codex, and Grok adapters.
4. Hermes and OpenClaw gateway adapters.
5. Policy routing, effectiveness scoring, and shadow decisions.
6. Controller endpoints and UI projections over Jaeger's protocol.
7. Read-only ARES state importer and rollback rehearsal.

New product capabilities live under `jaeger_ai/features/<feature>/`. Delegate
runtimes live under `jaeger_agent/delegates/<runtime>/`; only the hardened
process transport, lifecycle contracts, registry, health, and routing are
shared. This prevents a repeat of ARES's divergent root/controller copies.

## Retirement gates

ARES may be frozen read-only only after all of these are true:

- Every enabled ARES worker has a passing Jaeger adapter contract suite.
- Recorded routing fixtures produce equivalent or explicitly approved Jaeger
  decisions in shadow mode.
- Active plans, worker sessions, artifacts, and required memory have a tested,
  idempotent migration path.
- Jaeger passes restart, cancellation, timeout, duplicate-effect, permission,
  secret-redaction, and memory-poisoning tests for external delegates.
- A release has run with Jaeger authoritative and ARES available for rollback.
- Restore from the pre-migration backup has been rehearsed successfully.

Deletion from ARES is a separate, explicit repository-retirement change after
the freeze. Feature-port commits must never delete their ARES source.

## Consequences

- Jaeger gains external agent specialization without surrendering identity or
  memory authority.
- Existing Jaeger subagents continue to be the zero-configuration default.
- ARES remains temporarily duplicated, but that duplication is intentional
  rollback insurance rather than a second live authority.
- Adapters must implement lifecycle and trust contracts instead of importing
  another product's internal modules.
