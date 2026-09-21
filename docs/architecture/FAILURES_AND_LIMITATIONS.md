# FAILURES_AND_LIMITATIONS.md — Operational Limits & Engineering Truth

**Review Date:** 2026-09-20  
**Doctrine:** AGENTS.md — Root-Cause Repair & Proof Over Assumptions  

---

## 1. Incidents & Test Failures Encountered During Implementation

### 1. Missing `import time` in `packages/jaeger-agent/jaeger_agent/tool_executor.py`
* **Symptom:** During initial test execution of `dev/scripts/run_tests.sh`, 17 tests in `packages/jaeger-agent/tests/` failed with `NameError: name 'time' is not defined`.
* **Root Cause:** When integrating `tool.started` and `tool.completed` consequence logging inside `HookedToolExecutor.execute`, `time.time()` was invoked without importing `time` at the top of the module.
* **Resolution:** Directly imported `time` into `packages/jaeger-agent/jaeger_agent/tool_executor.py`. Re-running the test suite verified all 23 `test_run_turn.py` tests and related suites pass cleanly.

---

## 2. Architectural Boundaries & Current Limitations

### 1. Desktop Sensing Platform Permissions (macOS)
* **Limitation:** On macOS, querying the active window title and frontmost application requires Accessibility permissions.
* **Degradation Mode:** When running headlessly in CI or when Accessibility permissions are declined, `DesktopActivitySensor` safely falls back to environment metadata (`TERM`, process state) and filesystem disk telemetry without crashing.
* **Security Guardrail:** The sensor explicitly redacts sensitive password manager applications (1Password, Bitwarden, Keychain) to prevent credential leakage.

### 2. World Model Natural Language Extraction
* **Limitation:** The rule-based declarative relation extractor (`packages/jaeger-agent/jaeger_agent/cognition/world.py`) handles explicit assertions ("Alice manages Project Titan", "my role is engineer"). It does not parse complex conversational implicature, sarcasm, or ambiguous pronoun chains.
* **Mitigation:** The offline `MemoryConsolidator` ("Dreaming") mechanism can be extended with model-assisted extraction to summarize and assert relationships during idle consolidation passes.

### 3. Single-Node SQLite State Architecture
* **Limitation:** `SqliteEventStore` and `gateway_sessions.sqlite3` are local SQLite databases with WAL mode designed for a single physical machine.
* **Boundary:** It provides local, embodied multi-client access (Mac App, WebUI, CLI, TUI concurrently), but is not a distributed multi-datacenter consensus engine (e.g. Raft/CockroachDB).

### 4. Skill Promotion Sandboxing
* **Limitation:** The Voyager-style `SkillPromotionPipeline` enforces that candidate skills must pass automated programmatic test assertions before being promoted to the permanent skill catalog.
* **Boundary:** However, running arbitrary candidate verification tests should ideally occur in an isolated execution sandbox or subagent worktree to guard against destructive side-effects during candidate test execution.
