# ADR 0003 — Epistemic knowledge under MemoryStore

Status: accepted
Date: 2026-08-23
Extends: ADR 0001 — ports, not frameworks

## Context

ADR 0001 put facts and episodic turns behind `MemoryStore`. ADR 0002
recorded what the SI **did**. Neither distinguished how the SI **knows**
a proposition:

- "I observed X" is not "I was told X";
- "I infer X" is not "I believe X";
- "I predict X" is not a system configuration fact.

Flattening those into `facts` makes every later reader treat hearsay as
observation. The model cannot be asked to keep the distinction; a store
that cannot represent it will lose it.

## Decision

A `KnowledgeStore` port extends `MemoryStore` with claims, evidence,
beliefs, entities, and relationships. Provenance is an enum on the claim
(`observed`, `told`, `inferred`, `believed`, `predicted`, `system`), not
a free-text note.

Beliefs are a projection: they can be superseded or retracted without
deleting the claims they came from. Evidence links a claim or belief
back to a turn, tool call, or document. Entities and relationships are
the structured world model, keyed by name.

The in-memory adapter is the contract reference. SQLite is the
production adapter. Both must pass
`tests/contract/test_knowledge_store_contract.py` in one parametrised
pass.

Retrieval (`KnowledgeRetriever`) is a reader over the store: point-in-time
beliefs, contradiction detection, entity profiles, provenance
explainability. It does not write, and it is not a second SI.

## Consequences

- Schema **v5** (`cognitive-knowledge-foundation`). Additive tables only.
  v4 remains the runtime layer (runs / checkpoints / effects). Knowledge
  does not retake v4.
- A new knowledge backend implements `KnowledgeStore` and passes the
  contract tests. The agent loop still talks to `MemoryStore` until a
  later slice wires claims into a turn.
- ARES does not own this data. Claims live in JaegerAI `state.db`.
