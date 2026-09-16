# Phase 5: Live Multi-Agent Delegate Execution and Verification

Date: 2026-09-15
Final verdict: **VERIFIED WITH DELEGATE-SPECIFIC LIMITATIONS**

## Executive result

Jaeger successfully delegated a real coding repair to the authenticated Claude Code CLI in a disposable repository. The external run terminated with `execution_completed=true` and `objective_verified=false`. Jaeger's parent-side verifier then checked the actual Git diff, confirmed the protected test file's SHA-256 was unchanged, reran pytest, and allowed `complete_task` through the existing WorkLedger seam.

Codex was safely invoked through its intended adapter, but its local CLI failed before execution because its model cache could not be parsed (`missing field base_instructions`). Hermes was installed and version-probed but not invoked because its provider/billing authorization could not be established. OpenClaw's executable existed, but its status showed no reachable agent service. Gemini and Grok were not invoked because their authorization/cost modes were unknown.

Phase 5 reproduced and fixed two adapter defects: Claude's `dontAsk` mode prevented all fixture edits, and subprocess cancellation could race into a `failed` result. No controller, ledger, delegate framework, or result type was added.

## 1. Repository state

| Field | Recorded value |
|---|---|
| Root | `/Users/matthewjenkins/GitHub/JaegerAI` |
| Branch | `main` |
| HEAD | `612d6ee3afb1e4f2e59b83d831eddb35d43af1df` |
| Jaeger version | `0.11.0` |
| Python | `/Users/matthewjenkins/.jaeger/venv/bin/python` (3.12.12) |
| Jaeger executable | `/Users/matthewjenkins/bin/jaeger` |

The checkout was heavily dirty before Phase 5 and remains so. Phase 3/4 production and test changes were uncommitted, along with their five audit/report files. Phase 5 did not reset, clean, stage, commit, push, or otherwise rewrite this state.

Relevant live listeners at final inventory: Jaeger Gateway `127.0.0.1:8810`, Agentgateway `:8811/:8812`, A2A `127.0.0.1:8796`, WebUI `:8790`, Ollama `:11434`, and an OpenClaw/container listener at `127.0.0.1:18789`.

Phase 4 semantics remained present: actionable routing through the autonomous controller/WorkLedger, Gateway actionable text-only promotion, and status-derived delegate metadata where only `completed` receives `execution_completed=true` and all delegate results start with `objective_verified=false`.

## 2. Fixtures and common harness

All mutation targets lived under a unique `/tmp/jaeger-phase5.*` root, never inside Jaeger.

| Fixture | Purpose | Initial condition | Parent postconditions |
|---|---|---|---|
| A: `calculator` | real code repair | `add()` subtracted; one failing test | source changed, protected test hash unchanged, only allowed source changed, pytest exit 0 |
| B: `small_app` | multi-file repair basis | two failing tests | protected tests, source-only diff, pytest exit 0 |
| C: `inspection` | read-only actionable work | config referenced missing `assets/missing.json` | missing reference observed, Git status clean |
| multi-worker | two separable contributions | parser and formatter each wrong | each worker changed only its file; parent pytest passed |

The temporary harness used the production `DelegateRequest`, `DelegateExecutor`, registered adapters, in-memory Jaeger `RunStore`, WorkLedger, completion verifier hook, and `complete_task`. It only created fixtures, collected results, inspected Git/filesystem state, ran pytest, and removed its temp tree. It was not installed as production orchestration.

## 3. Live delegate execution

### Codex

Canonical path: `DelegateExecutor` -> Codex subprocess adapter -> `codex exec --json --sandbox workspace-write --skip-git-repo-check -`.

Codex had an existing ChatGPT login and was invoked against Fixture A. The CLI emitted eight output events and exited 1 after 11.995 seconds:

```text
failed to load models cache: missing field base_instructions at line 133 column 5
```

Jaeger recorded `status=failed`, Run state `failed`, `execution_completed=false`, and `objective_verified=false`. The source and protected test were unchanged, and pytest still failed. The user-level Codex cache was not deleted or rewritten because that would alter external tool state beyond the fixture validation.

**Answer:** Jaeger reached Codex through the correct adapter and normalized failure correctly; it cannot currently hand Codex successful coding work on this installation.

### Claude

Canonical path: `DelegateExecutor` -> Claude Code subprocess adapter with OAuth authentication.

The first live run reproduced a false-success shape. `--permission-mode dontAsk` denied Edit, Write, and Bash; Claude exited 0 with a refusal. Jaeger correctly left `objective_verified=false`, and the unchanged failing fixture prevented WorkLedger completion.

After the minimum adapter repair to `acceptEdits`, Claude changed only `calculator.py` from `return a - b` to `return a + b`. Claude still could not execute Bash under its noninteractive policy and explicitly reported that limitation. Jaeger did not trust the claim: it independently observed the diff, confirmed the test SHA-256 stayed `f25455f4eb3db8669adf0b066da0e55abaea0ac8dc4074be77676df0d543b193`, and ran pytest with `1 passed`.

Delegate result before verification:

```text
status=completed
execution_completed=true
objective_verified=false
```

Parent result after verification:

```text
protected test unchanged
allowed source diff only
pytest exit=0
complete_task completed=true
```

**Answer:** Jaeger can hand controlled coding work to Claude, and Jaeger retains objective-completion authority.

### Hermes

The host `hermes` wrapper resolved to the `jaeger-hermes-webui` Apple container and reported Hermes Agent 0.20.5. The existing delegated path is `DelegateExecutor` -> `hermes chat -q`; native Runs is a separate ingress. No live model execution occurred because the active provider and billing/authorization mode could not be established without risking metered use. The sandboxed registry probe also cannot access the container service without host permission.

**Answer:** Hermes installation is present, but real work is not verified in this phase.

### OpenClaw

The OpenClaw CLI probe returned version 2026.9.1. Its status reported the gateway URL `ws://127.0.0.1:18789` but `reachable=false`, with no agents or sessions and no loaded launch agent. The listener alone was not accepted as proof.

**Answer:** OpenClaw real work is not verified because no usable agent service was available.

The complete auth/cost and compatibility inventory is in [PHASE5_DELEGATE_MATRIX.md](PHASE5_DELEGATE_MATRIX.md).

## 4. Authority and adversarial verification

### Required ordering

The live failover run recorded:

```text
T0 objective/failover start       1789519726.852308
T2 external delegate terminal     1789519750.940313
T3 parent verification start      1789519751.029437
T5 complete_task accepted         1789519753.843980
```

The harness did not expose separate timestamps for T1, T4, or a wrapper-return T6, but the captured boundaries prove the material ordering: external termination preceded parent verification, which preceded WorkLedger completion. The focused controller suite passed and continues to enforce completion-gated termination.

### False success

A deterministic delegate claimed completion against the broken calculator baseline. Parent pytest exited 1. `complete_task` returned `completed=false` with `ledger is not finished: tests failed`.

The initial real Claude refusal provided a second real-world instance: process exit 0 did not create objective success.

### Test-file cheating

A controlled runtime changed `test_calculator.py` so pytest exited 0 while the implementation remained wrong. The protected SHA-256 changed. WorkLedger completion was refused with `test file changed`.

### Read-only actionable work

Fixture C's `config.json` referenced nonexistent `assets/missing.json`. The observation was verified against disk, Git status remained clean before and after, and WorkLedger completion succeeded. This proves verified action can be observational and need not mutate files.

## 5. Failover and multi-agent contribution

### Real failover

The existing `execute_with_fallback` path received `[controlled-refusal, claude]`. The first result was `failed`; the callback recorded the handoff; the Run was reopened using existing lifecycle semantics; Claude received the same bounded objective and repaired Fixture A. Parent verification then completed the WorkLedger.

The authoritative Jaeger effect occurred once at parent completion. The failed delegate produced no file effect, so retry did not duplicate completed work.

### More than one contributor

Two deterministic agent runtimes used production `DelegateExecutor` paths and distinct Runs. One repaired `parser.py`; the other repaired `formatter.py`. Each result ended with `execution_completed=true`, `objective_verified=false`. The parent saw exactly those two source changes, confirmed the protected test hash, reran pytest successfully, and then completed its WorkLedger.

This proves the existing execution and evidence contracts can combine multiple contributions under one parent authority. It does not claim that two real cloud delegates were coordinated in this phase; only Claude was both authorized and operational.

## 6. Workspace isolation and external effects

Every live delegate received an absolute disposable workspace. No real delegate was allowed to target the Jaeger repository. Fixture Git diffs showed the external effects directly.

The full `jaeger-agent` regression suite exercised existing subagent worktree isolation, including separate child worktrees, retention of dirty worktrees, cleanup of clean empty worktrees, and unproven payload handling. A real cloud delegate was tested only in shared fixture-cwd mode. Isolated cloud-agent worktree execution remains a limitation.

No fake local `EffectLedger` entry represented a delegate's edits. The parent used external receipts: actual diff, file hash, pytest exit, and WorkLedger evidence.

## 7. Failure, cancellation, timeout, and events

| Case | Observed result | Authority outcome |
|---|---|---|
| Codex nonzero exit | `failed`, Run `failed`, execution/objective flags false | incomplete |
| false-success claim | delegate claimed complete; parent pytest failed | WorkLedger refused |
| cancellation | child killed/reaped; normalized `cancelled`; execution not complete | incomplete |
| timeout | child killed; `failed`, exit `-9`, timeout summary, flags false | incomplete |
| unavailable OpenClaw service | no execution attempted | incomplete / unavailable |

Codex and Claude exposed output events only. The generic model safely accepted sparse event streams. No adapter returned incompatible result data requiring another result type.

## 8. Production defects and minimum fixes

### Defect 1: Claude adapter could not perform edits

- **Reproduction:** real Fixture A run; Edit, Write, and Bash denied; exit 0; no diff.
- **Failing evidence:** unchanged implementation and failing parent pytest.
- **Root cause / owner:** Claude adapter selected `--permission-mode dontAsk` for noninteractive delegated coding.
- **Minimum fix:** use Claude's existing `acceptEdits` mode.
- **Test:** `test_claude_delegate_accepts_workspace_edits` pins adapter arguments.
- **Live proof:** Claude changed only `calculator.py`; parent pytest passed.

### Defect 2: cancellation could become failure

- **Reproduction:** start a harmless long subprocess, call existing runtime `cancel()`, consume result.
- **Failing evidence:** race produced `status=failed`, exit `-15`.
- **Root cause / owner:** subprocess runtime terminated and awaited the child before cancelling the collector; the collector could observe the nonzero exit first.
- **Minimum fix:** cancel and await the collector first. Its existing cancellation handler kills/reaps the process and emits the canonical cancelled result.
- **Test:** `test_process_runtime_cancel_reports_cancelled_and_reaps_child`.
- **Proof:** repeated validation returned `status=cancelled`, non-complete execution, exit `-9`, with no orphan.

## 9. Regression results

| Suite | Result |
|---|---:|
| Root smoke | 169 passed |
| `jaeger-agent` full suite | 913 passed |
| JaegerOS full suite | 283 passed |
| Focused Phase 4 + Gateway + delegate suite | 85 passed |
| Focused new/changed delegate tests | included above; 26 passed in the direct focused run |

Four Gateway tests initially failed because the restricted sandbox denied loopback socket binds. The identical focused suite passed 85/85 with host loopback permission. Pytest emitted cache warnings because the sandbox could not write `~/.cache/pytest`; no cache was redirected into the repository.

## 10. Plain-English verdict

- **Can Jaeger hand real coding work to Codex?** The path is correct, but the installed Codex CLI currently fails on its model-cache schema before work begins.
- **Can Jaeger hand real work to Hermes?** Not verified. Installation exists; provider authorization and billing mode were unknown.
- **Can Jaeger hand real work to OpenClaw?** Not verified. The executable exists, but the agent service was unreachable.
- **Which delegates were not tested?** Hermes, Gemini, and Grok crossed the cost/authorization boundary; Cursor and OpenCode were absent; Ollama's registered adapter lacks coding workspace capability; OpenClaw lacked a reachable service.
- **Does Jaeger verify actual work?** Yes in the validated fixture path: diff, protected hash, and parent-run pytest controlled WorkLedger completion.
- **Can a false claim cause Jaeger objective success?** No in the real and deterministic cases exercised.
- **Can Jaeger fail over?** Yes. A controlled failed delegate handed off to real Claude through the existing fallback method.
- **Can more than one agent contribute?** Yes under the production executor/evidence contracts with deterministic contributors. Multiple real cloud contributors remain unverified.
- **Does the parent remain in charge?** Yes. Delegate completion never set `objective_verified`; WorkLedger completion followed parent checks.
- **Are external effects treated as evidence?** Yes. They were observed from fixture state and never fabricated as local Jaeger effects.
- **Ready for real repository work?** Ready for controlled, bounded work through the validated Claude path with explicit parent verification. Codex, Hermes, OpenClaw, and automatic real multi-cloud coordination require delegate-specific follow-up before general repository use.

## 11. Remaining limitations and next phase

1. Claude can edit under `acceptEdits`, but its Bash tool remained blocked in this noninteractive environment; parent-run verification is required.
2. Codex needs its external model-cache compatibility repaired and retested without deleting user state blindly.
3. Hermes provider authorization and OpenClaw service health need explicit resolution before live execution.
4. The live harness used `DelegateExecutor` plus WorkLedger directly; a full user-surface run in which the controller itself selects the delegate was not exercised.
5. Real cloud delegate worktree isolation and two-real-agent contribution were not exercised.

The next phase should be release hygiene as requested: identify exactly which dirty changes belong to Phases 3-5, commit them cleanly, synchronize the authoritative branch, and prove installation from a fresh checkout. That work was intentionally not mixed into Phase 5.
