# FAILURES_AND_LIMITATIONS.md — Operational Limits & Engineering Truth

**Review Date:** 2026-09-20  
**Doctrine:** AGENTS.md — Root-Cause Repair & Proof Over Assumptions  

---

## 1. Incidents & Test Failures Encountered and Resolved (Closure Pass)

### 1. `run_for_voice` Direct Indexing of Optional Keys
* **Symptom:** `KeyError: 'spoke_via_tool'` when invoking `run_for_voice` via Bridge integration test.
* **Root Cause:** `run_for_voice` constructed its return dictionary using direct bracket indexing (`out["spoke_via_tool"]`, `out["elapsed_s"]`) on the dictionary returned by `EntityRuntime.execute_turn()`.
* **Resolution:** Replaced bracket indexing with `.get("spoke_via_tool", False)` and `.get("elapsed_s", 0.0)` with safe defaults.

### 2. Live Instance Modification in Test Isolation Guard
* **Symptom:** `TEST ISOLATION FAILURE: the suite modified a LIVE instance tree. modified: ~/.jaeger/instances/jaeger/run/native-turns.sqlite3`.
* **Root Cause:** `_execute_turn` and `run_for_voice` accessed default instance paths because test fixtures did not explicitly set `JAEGER_STATE_DIR`, `JAEGER_HOME`, and `JAEGER_INSTANCE_DIR` in the environment.
* **Resolution:** Updated `clean_entity_env` and `clean_upaa_env` test fixtures to isolate instance directories under `tmp_path`, and updated `SkillPromotionPipeline` default path resolution to respect `operator_state_root()`.

### 3. Missing `import logging` in `_run_turn` Degraded Mode Exception Handler
* **Symptom:** `NameError: name 'logging' is not defined` when injecting runtime failure in `_run_turn`.
* **Root Cause:** `logging` was not imported in the local scope of the newly refactored `except Exception as exc:` block.
* **Resolution:** Added `import logging` within the handler block.

### 4. Bounded Replanning Candidate Filtering
* **Symptom:** `replan_on_failure` selected the same plan that had just failed execution because critic scores re-elevated the plan.
* **Root Cause:** Lowering `safety_score` was overwritten by the dynamic critic response during replanning.
* **Resolution:** Refactored `replan_on_failure` to filter out candidates matching `failed_plan.name` or `failed_plan.strategy_summary` from the candidate pool before passing to critic evaluation.

---

## 2. Architectural Boundaries & Operational Limits

### 1. Single Process Runtime Singleton
* **Limitation:** `EntityRuntime.get_singleton()` manages local process state. While threads and coroutines share this singleton safely, multiple separate operating system processes must coordinate via the Gateway (`:8810`) or Bridge socket (`run/bridge.sock`) rather than instantiating conflicting local SQLite writers.
* **Boundary:** All out-of-process clients (macOS app, WebUI, CLI) connect to the daemon rather than opening the state SQLite files directly.

### 2. Desktop Sensing Platform Permissions (macOS)
* **Limitation:** Querying active window titles and frontmost applications via `NSWorkspace` requires Accessibility permissions.
* **Degradation Mode:** When running headlessly in CI or when Accessibility permissions are declined, `DesktopActivitySensor` safely falls back to environment metadata (`TERM`, process state) and filesystem disk telemetry without crashing.
* **Security Guardrail:** `redact_privacy_signals` explicitly scrubs passwords, bearer tokens, API keys, email addresses, and password managers (1Password, Bitwarden, Keychain).

### 3. DeliberativeSearch Depth
* **Limitation:** The current deliberate planning implementation is bounded multi-candidate search with critic and feedback (`DeliberativeSearch`), not an unbounded Monte Carlo Tree Search exploring arbitrary branch depths.
* **Boundary:** It generates $\ge 3$ distinct candidates, evaluates safety/reversibility/reflection penalties, and supports bounded replanning on failure. Unbounded tree exploration is intentionally bounded to prevent runaway LLM latency on interactive turns.
