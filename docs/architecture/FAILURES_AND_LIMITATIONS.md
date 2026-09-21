# FAILURES_AND_LIMITATIONS.md — Operational Limits & Engineering Truth

**Review Date:** 2026-09-20  
**Doctrine:** AGENTS.md — Root-Cause Repair & Proof Over Assumptions  

---

## 1. Incidents & Test Failures Encountered and Resolved

### 1. Missing `import time` in `packages/jaeger-agent/jaeger_agent/tool_executor.py`
* **Symptom:** During initial test execution of `dev/scripts/run_tests.sh`, 17 tests in `packages/jaeger-agent/tests/` failed with `NameError: name 'time' is not defined`.
* **Root Cause:** When integrating `tool.started` and `tool.completed` consequence logging inside `HookedToolExecutor.execute`, `time.time()` was invoked without importing `time` at the top of the module.
* **Resolution:** Directly imported `time` into `packages/jaeger-agent/jaeger_agent/tool_executor.py`. Verified all tests pass.

### 2. Circular Import in `skills/promotion.py` on `EntityRuntime`
* **Symptom:** `ImportError: cannot import name 'EntityRuntime' from partially initialized module 'jaeger_ai.core.entity.runtime'`.
* **Root Cause:** `SkillPromotionPipeline` imported `from jaeger_ai.core.entity.runtime import EntityRuntime` at module top-level, while `runtime.py` imported `CognitionRouter` -> `SleepTimeProcessor` -> `SkillPromotionPipeline`.
* **Resolution:** Lazily resolved `EntityRuntime.get_singleton()` inside `extract_candidate` and `promote` methods. Eliminated module-level circular dependency at root.

### 3. Missing `verify_filesystem_write` in `VerificationContract`
* **Symptom:** `AttributeError: 'VerificationContract' object has no attribute 'verify_filesystem_write'`.
* **Root Cause:** `EntityRuntime.execute_turn` expected a convenient filesystem write verification wrapper, but `VerificationContract` only exposed generic `verify_disk_state`.
* **Resolution:** Added `verify_filesystem_write` to `VerificationContract` in `jaeger_ai/core/entity/verification.py` checking existence and content predicates.

### 4. `CandidatePlan.strategy` attribute mismatch in Deliberate Planner
* **Symptom:** `AttributeError: 'CandidatePlan' object has no attribute 'strategy'`.
* **Root Cause:** `CandidatePlan` named its strategy summary field `strategy_summary` while tests queried `plan.strategy`.
* **Resolution:** Added `@property def strategy(self) -> str` aliasing `strategy_summary`.

---

## 2. Architectural Boundaries & Operational Limits

### 1. Desktop Sensing Platform Permissions (macOS)
* **Limitation:** On macOS, querying active window titles and frontmost applications via `NSWorkspace` requires Accessibility permissions.
* **Degradation Mode:** When running headlessly in CI or when Accessibility permissions are declined, `DesktopActivitySensor` safely falls back to environment metadata (`TERM`, process state) and filesystem disk telemetry without crashing.
* **Security Guardrail:** The sensor explicitly redacts sensitive password manager applications (1Password, Bitwarden, Keychain) to prevent credential leakage.

### 2. Single-Node SQLite State Architecture
* **Limitation:** `SqliteEventStore`, `unified_memory.sqlite3`, and `gateway_sessions.sqlite3` are local SQLite databases with WAL mode designed for a single physical machine.
* **Boundary:** It provides local, embodied multi-client access (Mac App, WebUI, CLI, TUI concurrently), but is not a distributed multi-datacenter consensus engine (e.g. Raft/CockroachDB).

### 3. Skill Candidate Sandboxing
* **Limitation:** The Voyager-style `SkillPromotionPipeline` enforces that candidate skills must pass automated programmatic test assertions before being written to `SKILL.md`.
* **Boundary:** Running arbitrary candidate verification code should ideally occur in an isolated execution sandbox or ephemeral subagent worktree to guard against destructive side-effects during candidate test execution.
