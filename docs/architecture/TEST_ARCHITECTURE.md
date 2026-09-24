> **Classification:** CURRENT AUTHORITATIVE.
> **Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../CONTINUE_FROM_HERE.md)

# JaegerAI Test Architecture & Verification Standards (Workstream 21)

**Branch:** `pinocchio`
**Classification:** Engineering Specification & Testing Doctrine
**Status:** Canonical & Enforced

---

## 1. Core Testing Doctrine

```text
UNIT != ACCEPTANCE
MOCK PASS != PRODUCTION VERIFICATION
TOOL RETURNED OK != OBJECTIVE VERIFIED
ONE FACT = ONE AUTHORITATIVE PROBE
```

- **Mocks are strictly limited to Unit Tests.** A mock is permitted only to isolate pure business logic in individual functions.
- **Mocks are not proof for:**
  - Runtime routing and framework selection
  - Provider and model execution truth
  - Persistent identity continuity
  - Authority and PolicyKernel enforcement
  - EffectLedger idempotency
  - Independent disk/state verification
  - Crash recovery and resume
  - Client and WebUI continuity
  - Capability truth

A unit test that instantiates a class successfully is not production evidence.

---

## 2. The 10 Standard Test Tiers

The test suite is organized into 10 structured, reproducible tiers accessible via `dev/scripts/run_tests.sh`. The file lists in that script are the source of truth for what each flag runs.

| Tier | Flag | Target Scope | What passing proves |
| :--- | :--- | :--- | :--- |
| **Smoke** | `--smoke` | Tests marked `smoke` | Basic imports, configuration parsing, and core service instantiation succeed. |
| **Unit** | `--unit` (default) | Fast in-memory tests (`not slow/integration/model/ui/subprocess`) | Component algorithms, state reducers, and parser contracts function deterministically. Default also runs package suites. `--unit` skips package suites. |
| **Integration** | `--integration` | Tests marked `integration` | Stores (SQLite, Event Fabric, Reflection) and pipelines interact without locking or schema mismatches. |
| **Production-Path** | `--production-path` | Lifecycle, control-plane, runtime truth, PolicyKernel, UPAA production runtime, Gateway single terminal result, owner-run recovery, turn memory projection, executor prompt contract, voice ↔ Gateway | Real Gateway / EntityRuntime / run store / effect ledger with only the model scripted. Does **not** prove live WebUI or a live LLM turn. `test_effects_verification.py` and `test_state_ownership.py` test modules no production code imports; they are unit tests (2026-09-21 audit). |
| **Acceptance** | `--acceptance` | `dev/tests/acceptance/` | Live client requests reflect actual runtime execution (`UI == Gateway == Runtime == Multimodal`). Requires a live Gateway/WebUI. |
| **Security** | `--security` | Hardening suite, skills guard, legacy adapter CSRF/auth, `packages/jaeger-agent/tests/security/` | Trust-domain negatives, Zip Slip, path traversal, CSRF, shell-hook veto. |
| **Fault-Injection** | `--fault-injection` | `test_fault_injection_and_resilience.py` | Provider timeout/500, mid-effect crash idempotency, durable-task recovery, soak helper. This harness is **simulated**; it does not SIGKILL the operator Gateway. |
| **External-Eval** | `--external-eval` | `test_external_evaluation.py` | The independent grader **harness** classifies failures. It does not prove that BFCL/SWE-bench/Terminal-Bench were executed against a live Jaeger. |
| **Soak** | `--soak` | `test_fault_injection_and_resilience.py -k soak` | Short multi-turn leak check in the resilience harness. Extended soak is operator-scheduled. |
| **Full** | `--full` | Unfiltered `dev/tests` plus package suites | Broadest automated qualification. Still excludes live acceptance unless those tests are collected. |

Historical flags (`--regression`, `--subprocess`, `--ui`, `--slow`, `--model`, `--all`) remain for existing markers.

---

## 3. Standard Test Commands

```bash
# Fast local development cycle (default unit tests + package suites)
dev/scripts/run_tests.sh

# Fast unit tests only (no package suites)
dev/scripts/run_tests.sh --unit

# 30-second quick check
dev/scripts/run_tests.sh --smoke

# Kernel contracts without live WebUI
dev/scripts/run_tests.sh --production-path

# Pre-commit security verification
dev/scripts/run_tests.sh --security

# Resilience harness
dev/scripts/run_tests.sh --fault-injection

# Live WebUI and client runtime truth (requires Gateway + WebUI)
dev/scripts/run_tests.sh --acceptance

# External evaluation harness
dev/scripts/run_tests.sh --external-eval

# Short soak
dev/scripts/run_tests.sh --soak

# Full unfiltered dev/tests + packages
dev/scripts/run_tests.sh --full
```

Environment:

```text
PYTHONDONTWRITEBYTECODE=1
PYTHONPYCACHEPREFIX=$HOME/.cache/jaeger/pycache
JAEGER_NO_ATTACH=1
JAEGER_TEST_HEADLESS=1
PYTHONHASHSEED=0
TZ=UTC
```

The runner unsets credential-shaped environment variables so a unit test cannot silently hit a paid endpoint. Live acceptance tests that need a running stack must be launched with `--acceptance` against an already-configured isolated or operator instance.

---

## 4. Classification of Existing Suites

| Location | Typical class | Notes |
| :--- | :--- | :--- |
| `dev/tests/jaeger_ai/**` unmarked | UNIT | Majority of the tree. Fast, isolated via `JAEGER_STATE_DIR`. |
| `dev/tests/jaeger_ai/core/test_*` for WS 2–20 modules | UNIT / INTEGRATION | New kernel modules. Many construct classes in tmp dirs; they do not prove Gateway production wiring unless listed under `--production-path`. |
| `dev/tests/test_upaa_production_runtime.py` | PRODUCTION-PATH | Isolated UPAA loop. Not a live operator-stack test. |
| `dev/tests/acceptance/` | ACCEPTANCE | Live WebUI runtime truth. Requires Gateway `:8810` and WebUI `:8790`. |
| `packages/jaeger-agent/tests/` | UNIT / INTEGRATION | Separate pytest process. |
| `packages/jaeger-os/dev/tests/` | UNIT / INTEGRATION | Separate pytest process (process singletons). |
| `packages/jaeger-agent/tests/security/` | SECURITY | Shell-hook veto and related negatives. |

### Known hazards this audit records

- **Mocks used as architecture proof.** Several Workstream 10–18 tests construct in-memory registries/harnesses. They prove the module exists and its unit contracts hold. They do not prove the production Gateway path uses that module.
- **Operator-machine-dependent tests.** `--acceptance` talks to the live stack. `conftest.py` skips live-tree isolation for paths under `/acceptance/`. Do not treat a skip as a pass.
- **Global registries.** Tool registration tests must not `clear_registry()` (see `test_tier_gating.py`). New tests must restore process state.
- **Production state.** Tests must set `JAEGER_STATE_DIR` / `JAEGER_NO_ATTACH`. The runner sets `JAEGER_NO_ATTACH=1`.
- **Sleep/timing.** Prefer deterministic fakes over wall-clock sleeps. Soak tests that sleep must stay in `--soak`.
- **Order dependence.** Acceptance tests that inspect `/api/models` groups must match by provider id, not list index.

---

## 5. What each gate actually proves

| Gate | Automated evidence | Not proven by that evidence |
| :--- | :--- | :--- |
| A | WebUI runtime-truth acceptance + baseline snapshot | Physical iPhone Face ID / PWA / photo picker |
| B | Lifecycle, control-plane, schemas, ownership, compiler, world, PolicyKernel, effects unit/integration | Every Gateway branch retired; every store migrated |
| C | Capability/device/multi-agent/task **module** tests | Production install/execute of a third-party capability on the operator Gateway |
| D | Trace/eval/fault **harness** tests | Live SIGKILL of operator Gateway; published SWE-bench score |
| E | Security negatives + this runner + boundary-purity AST | Exhaustive dead-code deletion |
| F | Documentation, platform CLI, isolated-state install, contributor files | A second human cloning onto a wiped Mac with no `~/.jaeger` |

---

## 6. Contributor rule

If you add a test, pick the closest tier. If you add a flag to `run_tests.sh`, update this document and `dev/tests/jaeger_ai/core/test_test_architecture.py` in the same commit.
