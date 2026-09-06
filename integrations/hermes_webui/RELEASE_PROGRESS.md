# Integration release goal — execution record

Goal started 2026-09-06 against `737935d`. Release status: **NOT READY**.
Scope: execute `ROUNDTABLE_AUDIT_AND_PROMPT.md`; preserve native runtime ownership.

## Authority

The user explicitly approved pairing the existing local OpenClaw adapter with
operator.read, operator.write, operator.approvals, and configuring/testing direct
Desktop, Documents, Jenkins_Robotics and Personal-Drive mounts. Tool actions are
not automatically approved. macOS privacy prompts still require the user.
Local logical commits are authorized; no push or public release requested.

## Acceptance matrix

| Area | Implementation | Automated | Live | Remaining |
| --- | --- | --- | --- | --- |
| Quick/mention eligibility | Fixed | Reproduced before fix, passing after | Pending | Browser checks |
| Partial/error and EOF classification | Fixed for Roundtable legacy SSE | Reproduced before fix, passing after | Pending fault injection | Native transport migration |
| Anonymous member-session collision | Reject missing member ID; isolated anonymous table for direct callers | Passing | Pending | Durable table contract |
| A2A scoped cancel | Task-owned IDs; cancellation confirmation in bridge reply; context-scoped sessions | Concurrent A/B cancellation test passing | Pending deploy | Durable task store/restart tests |
| Test isolation | Supervisor honors isolated JAEGER_HOME; guard excludes exact background health snapshot | Full root suite passing with live supervisor | Supervisor left running | Continue isolated integration coverage |
| OpenClaw pairing | Approved existing identity with requested scopes only | Existing signature/translation tests | Authorized native connection and streamed chat passed | Native WebUI tool/approval/abort tests, then enable |
| Roundtable lifecycle/control/auth | Not complete | Pending | Legacy remains live | Shared durable Runs, native stop/approval/retry |
| Timeout layers | Not complete | Pending | Existing 90-second setting remains | Separate progress/idle/queue/tool/approval/total policy |
| Coordination/evidence/consensus/ledger | Not complete | Pending | Prompt-based legacy remains live | Typed workflows, deterministic validation, durable ledger |
| Group-chat UI/controls | Not complete | Pending | Existing Markdown presentation | Partial member events, selectors, browser tests |
| Provider/thinking/usage | Not complete | Pending | Existing defaults preserved | Native session-local overrides, current-doc verification |
| Workspace/private NAS access | Authorized; directories exist | Existing GitHub tests only | Extra mounts not yet changed | Managed-container update with rollback and real-user probes |
| Honcho per-agent verification | Not complete | Pending | Not retested | Isolated LAN write/retrieve receipts |
| Recovery/deployment/CI | Not complete | Pending | Supervisor active | Layered readiness, verified repairs, overlay CI/build/rollback |

## Evidence so far

- Six audit regressions failed before their fixes (selection, mention token,
  partial+error, premature EOF, anonymous identity, unknown A2A cancellation).
- Focused affected/neighbor suites: 128 passed in 6.92 seconds.
- Full root suite after first repair phase: **3,601 passed, 11 skipped**, one
  `audioop` deprecation warning, 107.45 seconds, seed `20260906`. No supervisor
  pause was required. Later phase changes require their own verification.
- A bridge queue test exposed a sleep-based scheduling flake; replaced sleeps
  with explicit worker-entry and queue-acknowledgement synchronization.
- Existing bridge reply shape is preserved for clients without scoped turn IDs.
- OpenClaw device approval used the exact inspected request ID and requested
  scopes. No permanent tool grant or automatic approval was enabled.
- Direct native OpenClaw probe returned and streamed `OPENCLAW-NATIVE-READY`
  in 2.78 seconds. This is a chat transport test, not a tool/approval test.

## Deployment boundary

Application source fixes above are not deployed yet. The OpenClaw pairing state
is live, but its native WebUI feature flag remains unchanged. Do not claim the
current WebUI has received the staged fixes until restart/deploy tests pass.
No private workspace mounts or existing sessions were changed in this phase.

Before deployment: record the active commit/image/config backups; verify no
wanted run is active; use explicit service targets; preserve rollback containers;
restore any paused monitoring; test all four profiles and native controls.
Do not mark the goal complete while required matrix cells remain unverified.
