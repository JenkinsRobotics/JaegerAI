# ADR 0001 — Ports around working implementations, not a new agent framework

Status: accepted
Date: 2026-08-23

## Decision

JaegerAI already has the swap points the platform needs:

- `ProviderAdapter` (model backends)
- `MemoryStore` protocol (persistence)
- `KnowledgeStore` protocol (epistemic claims / beliefs — ADR 0003)
- `CommitmentStore` protocol (durable intentions)
- `ToolExecutor` protocol (how a declared tool is run — ADR 0004)
- NDJSON AF_UNIX bridge (client boundary)

New work implements **contract tests** against those ports and a
durable commitment table in SQLite. It does not introduce LangGraph,
LangChain, CrewAI, or a second cognitive runtime in ARES.

ARES remains the experience/governance layer and talks to JaegerAI
only over the bridge protocol (`test_ares_does_not_import_jaeger_runtime_internals`).

## Consequences

- A new model backend subclasses `ProviderAdapter` and passes
  `tests/contract/test_provider_adapter_contract.py`.
- A new memory backend implements `MemoryStore` and passes
  `tests/contract/test_memory_store_contract.py`.
- Unfinished SI work is a row in `commitments`, not an LLM memory.
