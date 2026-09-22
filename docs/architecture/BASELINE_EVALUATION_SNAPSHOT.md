# Baseline Evaluation Snapshot (Immutable Reference)

**Timestamp:** 2026-09-21T18:05:00-07:00  
**Baseline Git Commit:** `675fb3e7` (pinocchio)  
**Cognition Baseline:** Ollama local + Ollama Cloud (`kimi-k2.7-code:cloud`)  
**Instance Isolation:** `JAEGER_STATE_DIR=/tmp/gw-iso` / pytest isolated tmp_path roots  
**Python Environment:** `~/.jaeger/venv/bin/python` (Python 3.12.12, pytest 9.1.1)  

---

## 1. Executive Summary

This snapshot records the validated operational baseline of JaegerAI before the major architectural consolidations of Workstreams 2 through 9. All tests recorded below were executed against the live system and isolated scratch instances, providing an empirical reference for all subsequent architectural transitions.

---

## 2. Test Suites & Empirical Results

### Tier 1: WebUI Runtime Truth & Acceptance Suite
- **File:** `dev/tests/acceptance/test_webui_runtime_truth.py`
- **Command:** `pytest dev/tests/acceptance/test_webui_runtime_truth.py -p no:randomly -v -s`
- **Result:** **9 / 9 PASSED** (38.24s)
- **Matrix:**

| Test | UI Layer | Gateway SQLite | Runtime / Cognition Layer | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Default Framework** | `#profileChipLabel` is `jaeger ai` | Active session framework: `jaeger` | Sovereign Jaeger entity resident | **PASS** |
| **Model Inventory** | Live certified menu (`REACT ✓`, `CHAT ✓`) | Canonical runtime inventory API | Unconfigured providers (Anthropic, OpenAI) 0 models | **PASS** |
| **Deterministic Turn** | `kimi-k2.7-code:cloud` selected | Session model: `kimi-k2.7-code:cloud` | Backend: Ollama Cloud; Model: `kimi-k2.7-code:cloud` | **PASS** |
| **Image Attachment (Vision)** | Visible `/api/upload` form post | Recorded in `attachments` SQLite table | Multimodal Ollama extracts `VISION-TOKEN-7421` | **PASS** |
| **File Attachment** | Text file upload (`doc-7421.txt`) | Attachment row in SQLite with size & mime | Gateway session attachment metadata coherent | **PASS** |
| **Capabilities Query** | "What capabilities are available?" | Gateway injects live `capability_inventory` | LLM details actual tools (finance, bridge, chat, etc.) | **PASS** |
| **Framework Switch** | Jaeger → Hermes → OpenClaw → Jaeger | Profile switch API updates active profile | Entity remains resident and aligned | **PASS** |
| **Restart Coherence** | Sessions kept across kickstart | Sessions reloaded from SQLite | Default profile & session binding coherent | **PASS** |

### Tier 2: Core Persistent Entity Suite (Pinocchio Acceptance A–L)
- **File:** `dev/tests/test_pinocchio_entity.py`
- **Command:** `pytest dev/tests/test_pinocchio_entity.py -v`
- **Result:** **12 / 12 PASSED** (4.62s)
- **Criteria Verified:**
  - `A`: Identity continuity (persists across cold reboots, independent of session ID) — **PASS**
  - `B`: Provider independence (model/provider swaps preserve entity identity and memory) — **PASS**
  - `C`: Interface independence (Gateway, Bridge, and CLI share underlying entity state) — **PASS**
  - `D`: Heartbeat truth (system event, no fake human message, quiet beat with 0 model calls) — **PASS**
  - `E`: Tool consequence loop (tool.started -> tool.completed/failed -> durable consequence event) — **PASS**
  - `F`: Background continuity (background tasks return to same persistent history with provenance) — **PASS**
  - `G`: Self-state reconstruction (cold boot rebuilds SelfState from persisted event log) — **PASS**
  - `H`: Passive event without LLM (routine observations update state with zero model invocations) — **PASS**
  - `I`: Salient event wakeup (high-salience anomaly wakes cognition) — **PASS**
  - `J`: Memory consolidation (episodic events consolidate into WorldModel with provenance) — **PASS**
  - `K`: Skill acquisition (attempt -> verification test -> promotion to library -> retrieval) — **PASS**
  - `L`: Multi-runtime convergence (all runtime routes converge on EntityRuntime) — **PASS**

### Tier 3: Universal Persistent Agent Architecture (UPAA) Suite
- **Files:** `dev/tests/test_upaa_production_runtime.py`, `dev/tests/test_upaa_closure_pass.py`
- **Command:** `pytest dev/tests/test_upaa_production_runtime.py dev/tests/test_upaa_closure_pass.py -v`
- **Result:** **17 / 17 PASSED** (5.60s)
- **Highlights:**
  - Real Executable Trace (`human -> attention -> executive -> router -> authority -> consequence -> learning`) — **PASS**
  - Passive Observation Path (0 LLM invocations) — **PASS**
  - Active Salience Cognition Wake — **PASS**
  - Deliberative Planning Mode (Tree search / LATS) — **PASS**
  - Tiered Perception Sensors (Tier 0 deterministic -> Tier 1 heuristic -> Tier 2 multimodal) — **PASS**
  - Skill Promotion to Production Registry — **PASS**
  - Model Critic & Self-Refine Reviser — **PASS**

### Tier 4: Frameworks & Ports Contract Suite
- **Files:** `dev/tests/jaeger_ai/contract/`
- **Command:** `pytest dev/tests/jaeger_ai/contract/ -v`
- **Result:** **63 / 63 PASSED** (8.27s)

---

## 3. Representative Task Baselines

1. **Tool-Use Task:**
   - Test: `test_1_real_executable_trace` and `test_acceptance_e_tool_consequence_loop`
   - Flow: Tool proposal checked by AuthorityLayer, dispatched to ToolExecutor, consequence event emitted to event store, memory updated.
2. **Persistence Task:**
   - Test: `test_acceptance_a_identity_continuity`
   - Cold reboot loads `EntityIdentity` from disk with matching `entity_id` and genesis timestamp.
3. **Crash/Recovery Task:**
   - Test: `test_keepalive_resilience_and_restart`
   - Gateway daemon and WebUI restarted via `launchctl kickstart -k`; session ID and SQLite records remain intact and recoverable.
4. **Model-Routing Task:**
   - Test: `test_deterministic_turn_multi_layer_agreement` and `test_closure_provider_routing_swap`
   - Selected model propagates from WebUI request to SQLite turn record to Ollama chat payload.
5. **Attachment Task:**
   - Test: `test_vision_token_acceptance`
   - Fixture PNG uploaded through real WebUI multipart endpoint; model perceives and outputs token `VISION-TOKEN-7421`.

---

## 4. Invariant Preservation Commitments

All subsequent workstreams (2 through 25) must preserve or improve upon the numbers in this baseline snapshot. No architectural consolidation may degrade tool consequence loops, session recovery, or multimodal perception.
