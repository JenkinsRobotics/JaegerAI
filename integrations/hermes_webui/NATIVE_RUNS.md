# Native profile hardening — September 6, 2026

Hermes WebUI remains the common browser interface. JaegerAI owns the profile
adapters and overlay; no donor checkout was edited. Agents continue owning their
native sessions, inference, tools, and permission decisions.

Release gate: **not ready**. For the current deployment/verification matrix,
see [RELEASE_PROGRESS.md](RELEASE_PROGRESS.md). Source implementation and
historical live tests below do not establish complete native feature parity.

## Implemented

- Jaeger `/v1/runs` translates native bridge deltas, reasoning, tool start/end,
  approval requests/responses, and targeted cancellation into the existing
  Hermes gateway protocol. `/v1/chat/completions` remains for legacy clients.
- Run events have stable sequence IDs and reconnect cursors. Receipts live in
  `.jaeger_ai/shared/webui-runs/<profile>` with private file permissions. Adapter
  restart reports interrupted/unknown execution, never automatically replays a
  potentially mutating request. Native conversation history is untouched.
- Approval IDs are unguessable and scoped to the owning run. Unknown, expired,
  repeated, cross-run, and unoffered choices are rejected. Cancellation unblocks
  pending approval with denial. The configurable approval wait defaults to 110
  seconds, below the native bridge's existing 120-second fail-closed deadline.
- New native-run endpoints require per-profile bearer credentials. Run URLs
  alone do not permit observation, cancellation, or approval. WebUI pins the
  gateway URL and credential that accepted a run so another profile tab cannot
  redirect its controls while that routing process remains alive. Durable route
  recovery after WebUI restart is not implemented yet.
- Cancellation addresses a native turn ID, including queued work. It does not
  cancel whichever unrelated conversation happens to be running. The adapter
  distinguishes cancellation intent from native confirmation. A native completion
  winning the race remains a completion. The bridge correction and native
  receipts are deployed; final live control/restart verification is still pending.
  Durable admission keeps uncertain sessions locked across adapter restart.
  Staged Jaeger adapter reconciliation queries a native durable
  receipt instead of replaying work; Hermes/OpenClaw reconciliation remains
  pending. Unknown native outcomes still retain their locks.
- Native tool progress is routed to its originating session. Text, reasoning,
  and interaction callbacks are execution-context-local, preventing background
  board/cron output from appearing in a foreground WebUI conversation.
  Native model and parallel-tool workers explicitly inherit a fresh context copy;
  the live native Roundtable test verified Jaeger partials before completion.
- The reused Jaeger bridge thread selects a session-specific ledger. Unfinished
  ledger pointers survive restart; completed tasks do not become another user's
  acceptance contract. Existing ledger files are retained.
- WebUI workspace paths are translated to explicitly published Mac roots before
  native Jaeger file work. Path traversal outside those mounts is rejected.
- OpenClaw's existing HTTP fallback now relays actual upstream token deltas,
  sends waiting heartbeats, and reports structured stream failures. Only the new
  user message is sent into its existing native session; historical turns are
  not repeatedly embedded in new prompts.

## Capability boundaries — do not claim full parity

| Profile/path | Native session | Live tool cards | WebUI approvals | Native Stop |
|---|---|---|---|---|
| Hermes default WebUI | Existing Hermes runtime | Existing Hermes runtime | Existing Hermes runtime | Existing Hermes runtime |
| Jaeger WebUI Runs API | Preserved | Implemented and live-tested | Implemented; automated relay/deny tests | Bridge race correction loaded; final end-to-end verification pending |
| OpenClaw HTTP fallback | Preserved | Not exposed by this transport | Not supported | Not advertised as reliable |
| OpenClaw native WS adapter | Same REST session-key mapping | Implemented behind opt-in | Implemented behind opt-in | Implemented behind opt-in |
| Roundtable | Existing member sessions; Hermes now native Runs | Existing member-level presentation | Legacy caller denies unpresentable requests | Legacy cancel reports unsupported; never invents native confirmation |

An opt-in native Roundtable backend now relays individual member events and
coordinates durable native Runs, workflows, ballots and ledgers. Live native
streaming and second-turn recall passed for all three members. It is NOT enabled
in the WebUI; browser controls, restart recovery, bounded storage and live
permission tests remain gates. See [ROUNDTABLE_NATIVE.md](ROUNDTABLE_NATIVE.md).

OpenClaw protocol-4 authentication was tested against the running gateway. A
token-only connection receives no operator scopes. The existing local device
identity was subsequently paired with the user's explicit approval, limited to
read, write/chat and approval scopes. `OPENCLAW_ADAPTER_NATIVE_RUNS` remains
disabled pending complete approval verification. The opt-in adapter signs the
native challenge, correlates session/run/approval IDs, and never auto-pairs or
replays `chat.send`. Real native streaming, a README tool call and acknowledged
abort passed. Tightening an isolated verification session to Guarded requires
`operator.admin`; permission for a separate temporary verification identity is
still pending. No administrator scope was added to the normal adapter, and no
tool auto-approval policy changed. HTTP chat continues working.

Native Jaeger/OpenClaw per-chat model-picker overrides and arbitrary multimodal
inputs are not implemented by these adapters. Existing runtime model defaults
were not changed. Roundtable's existing phase budgets and full interactive
member-control integration still need a separate integration pass. A transport
health check is not proof of a successful model turn or completed tool action.

Credential checks cover native Runs and the deployed legacy Roundtable ingress;
they are not a
claim that every historical/local gateway endpoint is authenticated. Do not
publish the host adapter ports directly to untrusted networks.

## Verification and operation

Latest root-suite result: **3,651 passed, 11 skipped** (seed `20260906`).
The staged WebUI passed 104 selected gateway/approval/idle-read tests; four
broader fixtures were excluded from that selection, and the complete upstream
suite was not certified. One broader test still mocks the pre-overlay global
configuration reader rather than the session-scoped loader.

Historical initial-deployment receipts (latest four-profile retest is recorded
in RELEASE_PROGRESS.md):

- Hermes `4a59f055e1a1`, Jaeger `a8fce8aacb70`, OpenClaw `92ea0929224e`:
  simultaneous two-turn checks, all with correct session recall.
- Roundtable `e6eaa5371398`: all three actual member answers verified, no member
  error entries; group response 38.6 seconds, follow-up recall 2.8 seconds.
  The smoke test now rejects merely echoing the check word in the question.
- Jaeger `c160fb67e031`: native `read_file` card and completion in the WebUI;
  correct Mac README line returned in 5.68 seconds.
- Jaeger `41033b7039a1`: WebUI Stop acknowledged, native journal ended with
  `run.cancelled`. The focused suite additionally covers cancelling a queued
  turn and selecting its session agent over a background global pointer.
- An unauthenticated native run POST returned HTTP 401 without dispatch.
- Both containers reached host MCP and the Jaeger A2A card. The existing
  Jaeger/OpenClaw provider configuration matched its backup exactly after
  excluding only the new private gateway credential.

Automated tests cover real HTTP/SSE response framing and EOF, replay cursors,
credential rejection, approval ownership/expiry/denial, cancellation races,
queued cancellation, session-busy handling, native OpenClaw event translation
and challenge signatures, ledger resumption/isolation, and cross-thread sink
isolation. See `dev/tests/jaeger_ai/interfaces/test_native_runs.py` and the bridge
tests. Full-suite runs no longer require pausing the fabric supervisor: tests
use isolated state, and the guard excludes only its exact background health
snapshot while continuing to protect other live state.

Live probes use clearly labeled sessions and consume model tokens:

```sh
.venv/bin/python scripts/verify-agent-webui.py --url http://100.74.2.15:8787
.venv/bin/python scripts/verify-native-webui.py --url http://100.74.2.15:8787
```

The latter performs a read-only repository tool check and denies any approval it
receives. It never enables YOLO or creates permanent grants. A live harmless
`terminal` printf ran without a prompt under the existing native policy; absence
of an approval card in that case is not evidence of a broken relay.

Provision credentials with `scripts/setup-native-runs.py`. This preserves model
settings and creates private `config.before-native-runs.yaml` backups. Never put
generated credentials in Git. Deploy the WebUI overlay before restarting an
approval-capable adapter. Use `scripts/prepare-hermes-webui.py` to stage upstream
plus the overlay, then build `hermes-webui:jaeger-native-runs-20260906`.

The initial deployment preserved the existing running container and copied the
generated API files into `/apptoo`; init copies them into `/app`. Recreation must
use the verified image or reapply the overlay. Image digest:
`sha256:372c9d8c360663fea97c57ee59e25a56f269cdb1101c1f8985ef517117d7e5be`.
The expanded-workspace replacement was rolled back after NAS filesystem checks
failed; that replacement remains stopped. Do not infer its image is now live.

## Rollback

Before any restart, ensure no wanted chat is active and pause the fabric
supervisor; restore it afterward. The immediate Jaeger rollback switch is
`JAEGERS_ADAPTER_NATIVE_RUNS=false` in its generated service environment, followed
by an adapter restart and gateway-capability cache expiry. This restores the
legacy MCP completion path without deleting native sessions or receipts.

The pre-change API files and host-code archives are saved at
`/tmp/jaeger-native-rollback.YmRcJ4` for this deployment. These are temporary
recovery artifacts; Git history is the durable source. Restore only reviewed
files, not an entire dirty worktree. Revert if profile routing breaks, native
Stop interrupts another session, or a non-owning run can resolve an approval.

All retained original containers, models, profile names, native histories, and
workspace mounts remain unchanged.
