> **Classification:** CURRENT AUTHORITATIVE.
> **Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../CONTINUE_FROM_HERE.md)

# JaegerAI Formal State Ownership Map

**Doctrine:** One Fact = One Authoritative Owner.  
No subsystem may directly modify another subsystem's private persistence.

---

## 1. State Ownership Directory

| State Domain | Authoritative Owner | Authoritative Module / Class | Storage Location | Writers | Readers | Projected? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **IDENTITY** | `EntityIdentity` | `jaeger_ai.core.entity.identity:EntityIdentity` | `<instance>/memory/entity_identity.json` | `EntityRuntime`, setup wizard | All | No (Immutable Anchor) |
| **EXPERIENCE HISTORY** | `SqliteEventStore` | `jaeger_ai.core.entity.event_store:SqliteEventStore` | `<instance>/memory/entity_events.sqlite3` | `EntityRuntime` | `EntityRuntime`, `IndexCoordinator`, `LearningPipeline` | No (Append-Only Event Fabric) |
| **CURRENT SELF STATE** | `SelfState` | `jaeger_ai.core.entity.self_state:SelfState` | Deterministic in-memory projection | `SelfState.apply_event` | `ExecutiveSelector`, `CognitionRouter` | **Yes** (Replayed from Event Fabric) |
| **ACTIVE EXECUTION** | `SqliteRunStore` | `jaeger_agent.cognition.sqlite_runs:SqliteRunStore` | `<instance>/data/runs.sqlite3` | `SqliteRunStore`, `RunLifecycleCoordinator` | `EntityRuntime`, `TurnExecutive`, `GatewaySessionStore` | No |
| **SIDE EFFECTS** | `EffectLedger` | `jaeger_agent.cognition.sqlite_runs:SqliteRunStore` | `<instance>/data/runs.sqlite3 [effects]` | `SqliteRunStore` (claim & resolve) | `VerificationRegistry`, `TurnExecutive` | No (Idempotent Ledger) |
| **CONVERSATIONS** | `GatewaySessionStore` | `jaeger_ai.core.gateway.session_store:GatewaySessionStore` | `~/.jaeger/gateway_sessions.sqlite3` | `GatewaySessionStore` | `GatewayApp`, WebUI, Mac Swift, TUI | No (Client Session Projection) |
| **SEMANTIC KNOWLEDGE** | `SemanticMemory` | `jaeger_agent.memory.sqlite_store:SemanticMemory` | `<instance>/data/memory.sqlite3 [claims]` | `SemanticMemory.record_claim` | `EntityRuntime`, `TurnExecutive`, Planner | No |
| **REFLECTIONS** | `ReflexionStore` | `jaeger_ai.core.entity.reflexion_store:ReflexionStore` | `<instance>/memory/structured_reflections.json` | `ReflexionStore.append` | `CognitionRouter`, `DeliberatePlanner` | No |
| **SKILLS & PROCEDURES** | `SkillPipeline` | `jaeger_agent.skills.skills_core:SkillPipeline` | `<instance>/skills/` | `SkillPipeline.promote`, Operator CLI | `EntityRuntime`, `CognitionRouter` | No |
| **ATTACHMENTS** | `AttachmentStore` | `jaeger_ai.core.gateway.session_store:GatewaySessionStore` | `<instance>/workspace/uploads/` & SQLite | `GatewayApp.handle_upload` | `EntityRuntime`, Multimodal Vision | No |
| **PROVIDER CERTIFICATIONS** | `CertificationRegistry` | `jaeger_ai.features.webui.adapter.profile_catalog` | Live Runtime Probe & Certifications | Certification Harness | WebUI, Gateway, Runtime | No |

---

## 2. Invariant Boundary Rules

1. **No In-Repo State:** Persistent stores resolve strictly via `operator_state_root()`, never in the repository tree.
2. **WebUI Isolation:** WebUI must never open or mutate Gateway SQLite directly. All session and attachment actions occur via the Gateway REST API (`/v1/...`).
3. **Agent Isolation:** `jaeger-agent` must never mutate Gateway sessions. It operates on its bound `runs.sqlite3` and `commitments.sqlite3`.
4. **Identity Invariance:** The Agent's entity identity (`entity_identity.json`) is persistent and immutable across LLM model swaps, provider switches, conversation resets, and process restarts.
5. **No Blind Writes:** Every side-effect is prefaced by an `EffectIntent` with an idempotency key in `EffectLedger` before execution, guaranteeing at-most-once semantics across process crashes.
