> **Classification:** CURRENT AUTHORITATIVE.
> **Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../CONTINUE_FROM_HERE.md)

# Jaeger Architecture (surviving design)

**Branch:** `pinocchio`
**Status:** Canonical contributor-facing architecture after the Master Architecture Completion program
**Evidence rule:** `IMPLEMENTED` means code is on the production path. `EXPERIMENTAL` means a module and unit tests exist. `PLANNED` is not shipped. `DEPRECATED` must not be used. `VERIFIED` requires a named test command or live request id.

This document describes what actually survived.

---

## 1. What Jaeger is

Jaeger is a **persistent entity runtime** with a **control plane** and **clients**.

```text
MODEL != AGENT
SESSION != AGENT
CLIENT != AGENT
DEVICE != AGENT

PROPOSED ACTION != AUTHORIZED ACTION
TOOL SUCCESS != VERIFIED SUCCESS

MEMORY != CONTEXT WINDOW
SUPPORTED != AVAILABLE
AVAILABLE != AUTHORIZED

ONE FACT = ONE AUTHORITATIVE OWNER
```

Jaeger remains the same entity across model, provider, conversation, interface, device, and restart. Identity for the operator instance is stored as `EntityIdentity` under the instance memory directory (operator entity `jaeger-entity-7615957f0fa6` on this machine; tests use isolated ids).

---

## 2. Primary topology

```text
CLIENTS
  Mac (SwiftUI) | WebUI | CLI | TUI | Phone PWA | future Vision / robot
        │
        ▼
CONTROL PLANE / GATEWAY     127.0.0.1:8810
  auth, sessions, SSE, run control, approvals,
  attachment HTTP, capability/model inventory projection
        │
        ▼
PERSISTENT ENTITY RUNTIME   EntityRuntime (OWNER, resident=true)
  Event Fabric → SelfState → Salience → Executive
  → ContextCompiler → CognitionRouter → JaegerAgent (subordinate ReAct)
  → PolicyKernel / AuthorityLayer → EffectLedger → Verification → Learning
```

| Role | Owner | Bind | Status |
| :--- | :--- | :--- | :--- |
| Control plane | `jaeger_ai.core.gateway.server` | `127.0.0.1:8810` | **IMPLEMENTED** |
| Entity execution | `jaeger_ai.core.entity.runtime.EntityRuntime` | in Gateway process | **IMPLEMENTED** |
| Subordinate ReAct | `packages/jaeger-agent` `JaegerAgent` | injected | **IMPLEMENTED** |
| WebUI client | `jaeger_ai.features.webui` | `127.0.0.1:8790` | **IMPLEMENTED** |
| Bridge client | `jaeger_ai.interfaces.bridge` | AF_UNIX | **IMPLEMENTED** |
| CLI client | `jaeger` / `jaeger_ai.cli` | process | **IMPLEMENTED** |
| Remote WebUI | Tailscale Serve `:8443` → loopback WebUI | tailnet | **IMPLEMENTED** (software). Physical iPhone **PLANNED** for Face ID/PWA/photo picker |
| External Agentgateway | MCP `:8811` A2A `:8812` | `jaeger gateway` (not `daemon`) | **IMPLEMENTED**, separate process |

---

## 3. Capability status

| Subsystem | Status | Evidence | Notes |
| :--- | :--- | :--- | :--- |
| Persistent identity | **IMPLEMENTED** | `EntityIdentity` + isolated UPAA tests | Survives provider swap |
| Event Fabric | **IMPLEMENTED** | `SqliteEventStore` | Append-only experience |
| Gateway sessions / SSE | **IMPLEMENTED** | Gateway daemon + WebUI proxy | Conversation projection, not identity |
| Product-default runtime = Jaeger | **IMPLEMENTED / VERIFIED** | `dev/tests/jaeger_ai/core/test_runtime_truth.py`; live WebUI acceptance | Hermes remains explicit |
| Attachments upload → cognition | **IMPLEMENTED / VERIFIED** | Gateway schema 5 + `inline_webui_text_attachments`; isolated document token `ATTACHMENT-TOKEN-9981` | WebUI does not write Gateway SQLite |
| Canonical WorkState lifecycle | **IMPLEMENTED** (module) | `jaeger_ai.core.runtime.lifecycle` + `test_execution_lifecycle.py` | jaeger-agent RunStore mapped; residual Gateway helpers remain |
| Control-plane vs runtime split | **IMPLEMENTED** (partial) | `run_subordinate_react` + `test_control_plane_consolidation.py` | Historical `_native_lead_turn` / `_sync_react` still in `server.py` |
| Typed contracts | **IMPLEMENTED** (schemas) | `jaeger_ai.contract.schemas` | Not every wire frame validates yet |
| State ownership map | **IMPLEMENTED** (doc + coordinator) | [STATE_OWNERSHIP_MAP.md](STATE_OWNERSHIP_MAP.md) | Duplicate files may still exist; owner is the map |
| ContextCompiler | **IMPLEMENTED** (EntityRuntime) | `execute_turn` constructs compiler | Budget/provenance unit-tested |
| World-state / semantic knowledge | **IMPLEMENTED** (partial) | `jaeger_ai.core.world` + SemanticMemory | Observation ≠ claim ≠ fact in the new store; older WorldModel code still exists |
| PolicyKernel | **IMPLEMENTED** | AuthorityLayer → kernel first | Fail-closed on kernel exception; some legacy policies still fail-open on import error |
| Typed effects + verification | **IMPLEMENTED** (pipeline module) | `jaeger_ai.core.effects` + EffectLedger | `tool ok` is not objective verified |
| Programmable capabilities | **EXPERIMENTAL** | `jaeger_ai.core.capabilities` unit tests | Not required by Gateway to run a turn |
| Capability self-improvement | **EXPERIMENTAL** | lifecycle module | Must not write the kernel |
| Multi-agent RuntimeHost | **EXPERIMENTAL** | `jaeger_ai.core.multi_agent` | Production topology is still one OWNER EntityRuntime |
| Generic devices | **EXPERIMENTAL** | in-memory `DeviceRegistry` | Mac/Web/phone are clients today, not Device records |
| Cognition profiles | **IMPLEMENTED** (inventory + profiles) | `canonical_runtime_inventory` is what WebUI `/api/models` uses | 8-state assessments are a library; live inventory is discovery |
| Durable background tasks | **EXPERIMENTAL** (new) + **IMPLEMENTED** (legacy scheduler/board) | `jaeger_ai.core.tasks` vs existing scheduler | Two schedulers coexist; new store is not the production cron |
| Unified trace | **IMPLEMENTED** (EntityRuntime) | `SqliteTraceStore` on `execute_turn` | Operator inspection CLI is thin |
| External evaluation | **EXPERIMENTAL** | harness + adapters | No invented benchmark scores |
| Fault injection / soak | **EXPERIMENTAL** | simulated harness | Does not SIGKILL operator Gateway |
| Security hardening | **IMPLEMENTED** (library + tests) | `dev/scripts/run_tests.sh --security` | Threat model: [THREAT_MODEL.md](THREAT_MODEL.md) |
| Test tiers | **IMPLEMENTED** | [TEST_ARCHITECTURE.md](TEST_ARCHITECTURE.md) | |
| Platform extension CLI | **IMPLEMENTED** | `jaeger capability validate`, `jaeger provider doctor`, `jaeger device inspect` | Validate/inspect public contracts; device registry is experimental |
| Clean-machine install | **EXPERIMENTAL** | isolated `JAEGER_STATE_DIR` test | Not a wiped macOS VM |
| Physical iPhone | **PLANNED** | checklist in MASTER_PROGRAM_STATUS | Software remote path exists |

---

## 4. Execution lifecycle

Canonical WorkState (`jaeger_ai.core.runtime.lifecycle`):

```text
CREATED → QUEUED → RUNNING → WAITING_FOR_APPROVAL → RUNNING → VERIFYING → COMPLETED
                              WAITING_FOR_EVENT
         FAILED | CANCELLED | INTERRUPTED | RECOVERABLE
```

One client request should map to one durable run. Approval is a persisted suspended run with a wake key, not a thread blocked on an Event. Crash of a PID that owned a RUNNING run maps to INTERRUPTED.

---

## 5. Authority, effect, verification

```text
ProposedAction
    → PolicyKernel (identity, grants, protected targets, shell hooks, commissioning, tier)
    → AuthorityLayer extra policies (allowlist, permissions, commissioning)
    → ALLOW | DENY | MODIFY | REQUIRE_APPROVAL
    → EffectIntent → EffectLedger → Execution → EffectResult
    → VerificationRequest → VerificationResult (disk/git/process probe)
```

`pre_tool_call` is owned by PolicyKernel. HookedToolExecutor evaluates AuthorityLayer once and only fires shell hooks if authority was not evaluated.

---

## 6. Memory and context

```text
Durable memory (Event Fabric, SemanticMemory, ReflexionStore, skills)
        │
        ▼
ContextCompiler
  SELECT → RANK → BUDGET → PROVENANCE → FORMAT
        │
        ▼
Model context window  (throwaway)
```

Prompt context is not the persistence layer. Provider swap must not rewrite identity.

---

## 7. State ownership (summary)

See [STATE_OWNERSHIP_MAP.md](STATE_OWNERSHIP_MAP.md).

| Fact | Authoritative owner |
| :--- | :--- |
| Identity | EntityIdentity JSON under instance memory |
| Experience | SqliteEventStore |
| Self state | projection from Event Fabric |
| Execution / effects | Run store / EffectLedger |
| Conversations | GatewaySessionStore |
| Semantic knowledge | SemanticMemory (+ WorldStore for the new epistemic layer) |
| Attachments | Gateway attachments table + workspace uploads |
| Provider certification | certification matrix + live discovery overlay |

WebUI must not open Gateway SQLite. Clients must not own entity identity.

---

## 8. Providers

Live certified baseline on this program:

- Ollama local
- Ollama Cloud
- `kimi-k2.7-code:cloud` (REACT / VISION pass in the certification matrix)

Code may mention OpenAI, Anthropic, Gemini, xAI, OpenRouter, Groq, DeepSeek, LM Studio, vLLM, Together, llama.cpp, MLX. Those are **SUPPORTED BY CODE** until discovery reports credentials, reachability, and certification. Missing credentials are `SUPPORTED — NOT LIVE TESTED`, not a test failure.

---

## 9. Multi-agent and devices

Production: **one** resident EntityRuntime OWNER in the Gateway process. CLI/WebUI/Bridge/MCP are ATTACHED_CLIENT.

`RuntimeHost` can construct multiple EntityRuntime objects in tests (**EXPERIMENTAL**). Independent second agents are not a production operator feature.

Devices: Mac, Web, and phone are **clients of the control plane**. `DeviceRegistry` is the generic contract for future sensors/robots (**EXPERIMENTAL**, in-memory).

---

## 10. Answers that must not depend on which path you took

1. **What is Jaeger?** Persistent entity runtime + control plane. Not the LLM, not the WebUI session.
2. **Where is identity?** `EntityIdentity` in instance memory.
3. **Who owns execution?** EntityRuntime in the Gateway OWNER process.
4. **Who owns conversation state?** GatewaySessionStore.
5. **Who owns execution state?** Run store / WorkState coordinator.
6. **Who owns effects?** EffectLedger.
7. **Who owns knowledge?** SemanticMemory / WorldStore (epistemic layer).
8. **How is model context built?** ContextCompiler over durable state.
9. **How do models change without changing identity?** Provider/model fields change; entity_id does not.
10. **How does a client connect?** Authenticated Gateway/WebUI/Bridge/CLI as ATTACHED_CLIENT.
11. **How does a device connect?** Today: as a client. Generic Device pairing is experimental.
12. **Second agent?** RuntimeHost tests only; production is one OWNER.
13. **Proposed → authorized?** PolicyKernel then AuthorityLayer.
14. **How do we know success?** Independent verification probes, not tool return strings.
15. **Crash resume?** Interrupted/recoverable WorkState + EffectLedger idempotency keys.
16. **Learn a capability?** Experimental lifecycle; kernel paths stay protected.
17. **Contributor extension?** Public contracts + `jaeger capability validate`.
18. **Evaluate?** Isolated eval harness; no fabricated scores.
19. **Clean install?** Isolated state dir proven; full wiped Mac not run here.
20. **What is experimental?** Capabilities, RuntimeHost, DeviceRegistry, new DurableTaskManager, external eval/fault harnesses, physical iPhone.
