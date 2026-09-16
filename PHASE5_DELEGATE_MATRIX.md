# Phase 5 Delegate Matrix

Date: 2026-09-15
Repository: `/Users/matthewjenkins/GitHub/JaegerAI`
Phase verdict: **VERIFIED WITH DELEGATE-SPECIFIC LIMITATIONS**

## Registry inventory and authorization boundary

The inventory came from Jaeger's registered runtime list. `available` means the adapter probe found an executable; it does not prove authentication, billing authorization, workspace mutation, or service health.

| Delegate | Registry probe | Auth known | Provider / locality | Cost classification | Canonical Phase 5 path | Workspace/edit support | Safe live test? | Result |
|---|---|---|---|---|---|---|---|---|
| Claude | available, Claude Code 2.1.146 | Existing Claude OAuth credentials; no token values read | cloud CLI | existing authenticated subscription/tool | `DelegateExecutor` -> Claude subprocess adapter | code/filesystem/terminal | yes | **PASS with limitation** |
| Codex | available; `codex login status` reported ChatGPT login | known existing ChatGPT login | cloud CLI | existing authenticated subscription/tool | `DelegateExecutor` -> `codex exec --json --sandbox workspace-write --skip-git-repo-check -` | code/filesystem/terminal | yes | **FAIL: local CLI model-cache schema error** |
| Hermes | host wrapper available; Hermes Agent 0.20.5 in `jaeger-hermes-webui` container | provider/billing mode not safely established | container wrapper; adapter declares remote unless explicitly configured local | unknown | `DelegateExecutor` -> `hermes chat -q ...`; native Runs is a separate ingress | code/tools claimed | no | **NOT AUTHORIZED** |
| OpenClaw | executable probe available, OpenClaw 2026.9.1 | no usable live agent session established | CLI/native service | unknown | existing OpenClaw CLI delegate for delegated execution; Native Runs remains separate | automation/code claimed | no | **NOT AVAILABLE: service status unreachable** |
| Gemini | available, 0.51.0 | not established without reading secrets or invoking provider | cloud CLI | unknown / potentially metered | existing subprocess adapter | code/filesystem/terminal claimed | no | **NOT AUTHORIZED** |
| Grok | available, 1.0.30 | not established | cloud CLI | unknown / potentially metered | existing subprocess adapter | code/filesystem/terminal claimed | no | **NOT AUTHORIZED** |
| Cursor | executable missing | no | cloud CLI | unknown | existing subprocess adapter | adapter claims code/filesystem/terminal | no | **NOT AVAILABLE** |
| Ollama | daemon listening on `:11434`; delegate probe requires `JAEGER_OLLAMA_DELEGATE_MODEL` | local service | local inference | local | existing Ollama subprocess adapter | inference only; no coding filesystem capability | no for Fixture A | **NOT APPLICABLE** |
| OpenCode | executable missing | no | unknown | unknown | existing subprocess adapter | adapter claims code/filesystem/terminal | no | **NOT AVAILABLE** |

Hermes' host probe required access to Apple's container service. The ordinary sandboxed registry probe therefore reported `Operation not permitted`, while the read-only host version check succeeded. No Hermes model call was made.

OpenClaw's listener on `127.0.0.1:18789` was not treated as proof of execution. `openclaw status --json` reported the configured gateway URL but `reachable: false`, no agents, and no sessions.

## Live fixture result matrix

| Delegate / case | Probe | Started | Edited source | Test run by delegate | Parent pytest | Execution status | Jaeger verified | WorkLedger complete | Cleanup | Duration |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| Codex, Fixture A | pass | yes | no | no | fail | failed | no | no | pass | 12.0 s |
| Claude, initial Fixture A | pass | yes | yes | blocked by CLI permission policy | pass | completed | yes, after independent checks | yes | pass | 29.5 s |
| controlled refusal -> Claude failover | pass | yes | yes | not relied upon | pass | completed | yes, after hash/diff/pytest | yes | pass | 27.0 s including verification |
| deterministic false-success | pass | yes | no | no | fail | completed claim | no | no | pass | local |
| deterministic test cheating | pass | yes | test only | yes | pass | completed claim | no | no | pass | local |
| deterministic timeout | pass | yes | no | no | not applicable | failed | no | no | pass | 1.0 s |
| deterministic cancellation | pass | yes | no | no | not applicable | cancelled | no | no | pass; child reaped | <1 s |
| deterministic two-worker parent task | pass | yes x2 | `parser.py`, `formatter.py` | parent-owned | pass | completed x2 | yes | yes | pass | local |
| read-only inspection, Fixture C | pass | yes | no | not applicable | not applicable | observation produced | yes | yes | pass | local |

## Result and event normalization

| Runtime | Events observed | Result normalization |
|---|---|---|
| Codex | 8 `output` events | nonzero exit -> `failed`; stderr retained; `execution_completed=false`; `objective_verified=false` |
| Claude | 1 `output` event per run | exit 0 -> `completed`; JSON assistant text becomes summary; `execution_completed=true`; `objective_verified=false` |
| deterministic subprocess timeout | no rich tool events required | killed child -> `failed`; timeout summary; exit `-9`; both completion flags false after `DelegateExecutor` normalization |
| deterministic subprocess cancellation | initial output permitted | cancelled collector kills/reaps child -> `cancelled`; exit `-9`; execution is not complete |

The generic event model handled delegates that exposed only output. Phase 5 did not require synthetic reasoning or tool events.

## Claims versus observed state

| Case | Delegate claim | Observed state | Completion decision |
|---|---|---|---|
| Codex | no successful claim; CLI failed | no source diff; protected test unchanged; test still failed | objective incomplete |
| Claude before adapter repair | unable to edit | no source diff; test failed | objective incomplete despite process exit 0 |
| Claude after repair | source fixed; test could not be run because Bash approval was blocked | `calculator.py` changed from subtraction to addition; protected test hash unchanged; parent pytest: 1 passed | objective complete only after parent verification |
| cheating runtime | passing test | test file hash changed | objective incomplete |

No external delegate output was promoted into Jaeger's local `EffectLedger`. File changes remained external effects and entered the decision only as filesystem diff, hashes, test results, and WorkLedger evidence.
