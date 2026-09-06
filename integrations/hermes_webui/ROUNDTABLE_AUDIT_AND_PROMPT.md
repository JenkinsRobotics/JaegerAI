# JaegerAI / Roundtable audit and implementation prompt

Date: 2026-09-06. Audited baseline: `737935d`.

## Scope and confidence

Source review of the profile adapters, native Runs bridge, WebUI overlay,
A2A executor, workspace deployment, recovery supervisor, and CI. Read selected
live launch configuration and the managed-workspace manifest. Ran isolated,
mocked reproductions; no model requests, service restarts, pairing, application
edits, or permission changes were made for this audit.

This is an integration audit, not certification of the entire repository.
The prior implementation recorded 3,594 passing root tests and 104 selected
WebUI tests. Those suites were not rerun in this audit and do not establish
complete feature parity or current end-to-end health.

## Findings in implementation order

### 1. High: cancellation is not consistently scoped to native work

- `jaeger_ai/interfaces/a2a_server.py:148`: cancellation calls
  `control("cancel")` without task/session/turn identity. A mocked bridge
  reproduced exactly `('cancel',) {}`. This can target unrelated active work
  despite the new bridge's support for scoped cancellation.
- `jaeger_ai/interfaces/hermes_profile_adapters/roundtable.py:446`: cancel only
  changes the in-memory Roundtable status; it does not stop native member work.
  It also reports cancellation for nonexistent IDs.
- Roundtable calls Hermes through a captured-output subprocess and Jaeger /
  OpenClaw through legacy completions (`roundtable.py:192`, `:252`). It does not
  use the new native Runs tool, approval, or cancellation interface.

Required: task/member/run ownership, native acknowledgement, truthful unknown
execution states, and fail-closed approval forwarding across every entry point.

### 2. High: a failed partial answer can enter consensus as successful

`roundtable.py:269` consumes only `choices[].delta.content`. Structured error
frames are ignored; EOF does not require a successful terminal frame. A mocked
stream containing a text delta, an upstream error, and `[DONE]` returned
`'Partial answer'`; `_is_failed_answer` returned `False`.

The OpenClaw adapter actually emits structured `error` frames on transport
failure (`openclaw.py:195`). This is a concrete producer/consumer mismatch,
not only a hypothetical malformed-server case.

Required: typed terminal outcomes separate from partial display text. Failed or
unknown members cannot count as completed evidence, votes, or agreement.

### 3. High: long-running work still has a total Roundtable deadline

`roundtable.py:328` joins all member threads against one fixed phase deadline;
Hermes also uses `subprocess.run(timeout=MEMBER_TIMEOUT)` at line 216. The live
launch plist sets `ROUNDTABLE_MEMBER_TIMEOUT=90`. OpenClaw's separate socket
timeout is also configured to 90 seconds; these are different timeout layers.
Heartbeats do not extend Roundtable's phase deadline. Adapter timeouts can leave
native work running while the outer thread clears its in-flight tracking.

Required: separate connect, upstream-idle, queue, tool, approval, and optional
explicit total budgets. Do not solve this by making every wait infinite.
Distinguish transport keepalives from actual native progress, preserve ownership
when execution is unknown, and provide observable wait/cancel/recovery controls.

### 4. High: restart recovery is receipts, not durable execution ownership

- `native_runs.py:139`: same-session exclusion checks only in-memory runs.
  `get()` reports saved active receipts as interrupted but does not reconcile
  native execution before a new `start()` can accept the same session.
- `integrations/hermes_webui/jaeger_gateway_routes.py:5`: accepted-run routing is
  an in-memory dictionary. Restart loses the pinned origin; gateway control code
  can fall back to ambient configuration. Routes also have no retention limit.
- Roundtable runs and in-flight ownership are in-memory; its event reader starts
  at offset zero and has no durable replay cursor (`roundtable.py:422`, `:562`).
- A2A uses `InMemoryTaskStore` and maps sessions to task IDs, not a durable
  conversation mapping (`a2a_server.py:121`, `:160`).
- Missing Roundtable session IDs share the `anonymous` member-session namespace
  (`roundtable.py:186`). Reject missing identity or create an explicit isolated
  table session; do not silently share memory across anonymous requests.

Required: durable identity and reconciliation, not blind replay. A disconnected
or restarted adapter is not evidence that a tool action never happened.

### 5. High: legacy authorization does not match native Runs protection

Roundtable binds `0.0.0.0` (`roundtable.py:605`) and its HTTP handlers have no
credential checks. They accept execution/cancel requests and wildcard CORS.
Network exposure depends on the host firewall and routes; this audit did not
test reachability from another machine. New native Runs authentication does not
secure these older routes. Legacy body parsing also lacks native Runs' bounds.

Required: explicitly define the trusted ingress, authenticate applicable legacy
routes, restrict origins, bound input/concurrency, and test run ownership. Do not
break authorized container access or silently broaden device/tool grants.

### 6. Medium: selection can violate the user's requested members

Reproduced:

```text
/quick @Hermes @Jaeger check ollama
Selected: OpenClaw
```

`_best_member()` searches all members; line 99 does not constrain it to the
selected participant set. `@all` is a substring match rather than a complete
mention token. No persistent mute/add/remove membership controls exist here.

Required: typed selection, explicit mention boundaries, eligible-member routing,
persisted table membership, and a visible explanation of automatic selection.

### 7. Medium: coordination, evidence, and consensus are mostly prompt policies

`roundtable.py:117` changes instructions per mode, but every non-quick mode uses
the same answer/discussion/synthesis flow. There is no enforced task assignment,
proposal ownership, ballot parser/tally, evidence registry, or consensus
validator. The chair is hash-selected (`:182`), not explicitly rotated, selected
as least involved, or user-selectable. “Strict consensus” at line 344 describes
the prompt, not a deterministic guarantee.

Required: orchestrator-owned structured records. Verified evidence must reference
a real tool receipt with owner, timestamp, scope, and outcome. Record explicit
support, opposition, abstention, and missing responses against proposal IDs;
compute unanimity/majority before asking an LLM to explain the result.

### 8. Medium: presentation is not yet live group chat

`roundtable.py:281` buffers member deltas and `:318` emits whole answers inside
one Markdown response. There are no structured per-member partial streams,
reply relationships, live tool cards, or individual retry controls in this path.
The WebUI patch lists six slash modes and fixes command wrapping, but has no
equivalent Roundtable mode/member picker added by this integration. Some command
descriptions promise actual work division that the backend does not enforce.

Required: stable member message IDs, interleavable partial events, honest typing /
waiting / tool / approval status, accessible selectors, and discoverable help
generated from the same capability registry as the backend.

### 9. Medium: context limits exist, but shared project memory is incomplete

Native member session IDs are stable; this is worth preserving. Peer text is
capped by characters (`roundtable.py:163`), and the user request is abbreviated
for discussion. There is no Roundtable-owned structured decisions/actions/open
questions ledger or compact, evidence-linked shared summary. Jaeger's native
work ledger is not a substitute for a table-wide ledger.

Required: bounded relevant context with explicit truncation and retained dissent,
durable decisions/tasks/evidence, and session-preserving retry. Do not add whole
historical transcripts back into each member prompt.

### 10. Medium: adapter capability and provider parity remains incomplete

`NATIVE_RUNS.md` and `README.md` correctly disclose that OpenClaw native controls
are permission-gated, Jaeger/OpenClaw per-chat model overrides are not connected,
and arbitrary multimodal inputs are unsupported. Native Jaeger clarification is
currently redirected to its native session (`native_runs.py:310`). The reviewed
native translators do not emit normalized token/usage accounting.

Required: truthful capability negotiation and disabled/unsupported UI states;
session-local provider/host/model routing where supported; supported thinking
settings and measured usage, distinguishing unknown billing from zero cost.
Pairing still requires explicit user authorization, never automatic approval.
Research current official Ollama/runtime documentation before implementation.

### 11. Medium: health and repair can miss the failing reasoning layer

`fabric_supervisor.py:103` mostly probes HTTP status/TCP availability. Jaeger
recovery restarts its adapter/MCP server but not the native bridge; a live socket
does not prove the bridge or provider can complete work. Roundtable's own health
always returns ready. `Supervisor.tick()` treats a successful repair command as
success without an immediate readiness recheck. Container listing before restart
has no subprocess timeout (`:71`).

Required: layered liveness/readiness/dependency status; bounded checks and repairs;
post-repair verification; active-run-aware maintenance; and operator-visible
reasons. Keep the non-LLM supervisor independent. Do not run expensive model
canaries every 20 seconds or restart on mere model slowness.

### 12. Medium: workspace and repo ownership work is not finished

The live manifest lists only `/mnt/host/GitHub` among added managed workspaces.
Desktop/Documents/NAS direct mounts remain opt-in and unverified here. Existing
artifact/config mounts are separate and preserved. Prior GitHub cross-write
tests are documented, but they do not prove private-share access.

`scripts/setup-agent-workspaces.py:78` still updates `.ares/gateway/config.yaml`;
OpenClaw credentials/state retain `.ares` defaults. Documentation also records
OpenClaw's legacy Hermes grant identity. Distinguish custom-source ownership from
legitimate external runtime state. Do not rename/delete working state blindly.

Required: one capability/workspace manifest used by every profile, actual-user
scoped access probes, clear Mac/Linux path mapping, explicit private-share
permission handling, distinct agent grants, and an inventoried reversible
migration of remaining custom ARES dependencies. Concurrent repo changes need
task ownership/worktree or locking rules and an external deployment handoff.

### 13. Medium: storage and CI need long-running integration coverage

`native_runs.py:57` rewrites all accumulated events/output on every event. This
causes growing write amplification; runs/routes remain in memory without pruning.
Add bounded retention and efficient durable event storage without losing active
approvals or replay guarantees.

`.github/workflows/ci.yml` runs root/package/Swift/artifact jobs but has no explicit
job staging the patched WebUI and testing the resulting overlay. Prior selected
WebUI testing excluded four broader fixtures; it was not upstream certification.
Add adapter contract, overlay-build, fault-injection, and browser integration
coverage. Isolate tests from live runtime state instead of routinely pausing the
production supervisor to satisfy test guards.

## Original twelve Roundtable requests: status

| Request | Audited status |
| --- | --- |
| Speaker coordination | Prompt-only volunteering; enforced assignment missing |
| Six turn modes | Parsing exists; distinct workflows mostly missing |
| Evidence-aware claims | Prompt labels; tool-backed validation missing |
| Tool delegation | Members have native tools; unified bounded task/result protocol missing |
| Strict consensus | Synthesis instructions; deterministic agreement checks missing |
| Context budgeting | Stable native sessions and character caps; shared summary/ledger missing |
| Independent synthesis | Hash-selected chair; rotation/user choice/neutrality policy missing |
| Natural group chat | Whole-member Markdown chunks, not per-member token/event UI |
| Selective participation | Mentions exist; quick-selection bug; persistent membership missing |
| Failure isolation/retry | Some isolation exists; native stop/recovery/individual retry incomplete |
| Decision/task ledger | No Roundtable-owned durable structured ledger in reviewed path |
| Security boundaries | Partial grants/workspace tools; unified verified access display incomplete |

## Copy-ready implementation prompt

```text
Work in /Users/matthewjenkins/GitHub/JaegerAI. Harden the Hermes WebUI integration
and Roundtable without regressing the working individual agents. Read AGENTS.md,
integrations/hermes_webui/ROUNDTABLE_AUDIT_AND_PROMPT.md, NATIVE_RUNS.md, and the
workspace integration notes. Recheck the current commit and dirty worktree; the
audit baseline was 737935d. Reproduce findings before fixing them.

Architecture and safety constraints:
- Hermes WebUI is the common framework-agnostic interface. Hermes, Jaeger, and
  OpenClaw retain their own native sessions, execution, tools, and permissions.
- All custom implementation/build/overlay/test code belongs in JaegerAI. Keep
  pinned donor repositories clean. Inventory external runtime state separately;
  migrate it only with backups, compatibility, and verified rollback.
- Preserve existing profiles, sessions, provider defaults, credentials, grants,
  and working mounts. Never make unsupported controls appear functional.
- Do not pair OpenClaw or expand access without explicit approval. Do not bypass
  macOS privacy prompts. Report blocked items and continue safe independent work.
- Never automatically replay a possibly executed tool turn. Timeout, disconnect,
  partial text, and successful cancellation are different outcomes.

Implement in small independently tested phases:

1. Correctness/security first: fix unscoped A2A cancellation; Roundtable's false
   cancellation, ignored SSE errors/premature EOF, anonymous session collision,
   and /quick selection outside explicitly chosen members. Authenticate legacy
   execution/control routes, restrict origins and bound request/concurrency load.

2. Unify adapter run contracts: durable table/member/native-session/run/task IDs;
   structured deltas, tool/evidence events, approvals, errors, usage, and terminal
   states; native targeted Stop and per-member retry. Preserve native sessions.
   Persist control-route ownership securely across WebUI restarts. Reconcile
   unknown execution before same-session resubmission. Add retention/backpressure.
   Complete OpenClaw native pairing-dependent controls only after permission.

3. Replace the 90-second Roundtable phase cutoff with distinct configurable
   connect/idle/queue/tool/approval budgets and an optional explicit total limit.
   Heartbeats are not proof of native progress. Provide visible stalled/unknown
   states, bounded recovery and real cancel; do not make every wait unbounded.

4. Implement real coordination. Default ask: independent parallel answers, one
   discussion, then evidence-based decision. Make collaborate assign bounded work
   and owners; quick choose only eligible members; review assign proposer and
   reviewers; vote record structured ballots; incident separate diagnostics,
   evidence, and authorized remediation. Support membership/muting and a visible
   chair policy. Do not equate model instructions with implemented controls.

5. Enforce evidence and consensus in code. Tool receipts establish Verified;
   peer claims are Reported; inference/unknown remain explicit. Track proposal IDs
   and each member's support/opposition/abstention/failure. Derive unanimity and
   majority deterministically. Retain objections. Persist decisions, assigned
   tasks, open questions, evidence, status, and a compact shared project summary.

6. Render a real group chat in the Jaeger-owned WebUI overlay: individual member
   messages with live partials, avatars, tool cards, approval prompts, waiting and
   failure status, reply relationships, and per-member cancel/retry. Provide
   mode/member selectors plus slash commands and @ autocomplete from one shared
   capability registry. Use accessible vertical scrolling and honest help text.

7. Finish capability consistency: actual session-local Ollama provider/host/model
   selection across supported adapters, separate Mac/Rack inventories, supported
   thinking controls, normalized token/latency/usage records, and explicit unknown
   costs. Verify current official provider/runtime docs. Do not silently change
   global defaults or route an unavailable host to another host. Verify Honcho
   independently for each native runtime over LAN, with isolated test data and
   no mixing of sessions or users. Do not infer memory works from /health.

8. Use one truthful workspace/access manifest for all profiles. Verify GitHub and
   authorized Desktop/Documents/Jenkins_Robotics/Personal-Drive access using each
   actual container user and scoped temporary probes. Show configured vs mounted
   vs verified read/write access, Mac/Linux paths, grants, latency, and failures.
   Keep missing NAS volumes unavailable rather than creating empty substitutes.
   Add safe concurrent code-edit ownership and an external test/deployment handoff.

9. Harden the independent supervisor and deployment: layered readiness checks,
   bounded operations, correct component repair, post-repair validation, no
   restart storms, active-run-aware maintenance, and reproducible overlay/image
   builds with version/hash reporting and rollback. Add an overlay CI job and
   isolate tests from production runtime files.

Acceptance gates:
- Regression tests reproduce every confirmed audit bug before its fix.
- All four profiles pass simultaneous multi-turn tests, correct identity/model/
  host routing, and session recall without cross-session output or control leaks.
- Roundtable streams each member before that member finishes; default ask has
  exactly one discussion; selection/muting/chair/modes match displayed controls.
- Partial+error, premature EOF, HTTP errors, provider throttling, slow progress,
  genuine idle stalls, queue delays and pending approval remain distinct.
- Cancel A leaves B running; cancelled queued work never executes; retries target
  only the failed member and preserve its native session. Restart/disconnect
  recovery cannot duplicate a test side effect.
- Approval once/deny/expiry/cross-run rejection are tested through the actual UI
  and native runtime, using harmless actions without enabling permanent grants.
- Dissent/abstention/failure cannot yield false unanimity; no model-generated
  label alone can elevate a claim to Verified.
- Real bounded MCP calls and A2A send/status/cancel/session tests pass, not just
  discovery-card checks. Honcho retrieval and workspace access have separate
  attributable receipts. Do not write to personal data as a test.
- Long-session/replay/retention tests show bounded storage/memory and no lost
  events, tasks or approvals. Browser tests cover selectors and reconnect.
- Run root tests, applicable package tests, staged WebUI gateway/approval/profile/
  model/workspace tests, overlay build checks, and a controlled restart/rollback
  smoke test. Report every skip/exclusion and permission-blocked live test.

Keep an implemented / automated-tested / live-verified / blocked matrix. Do not
declare parity based only on test counts or health endpoints. Commit only reviewed
task changes in small logical commits; do not push unless asked. Finish with the
actual findings/fixes, test evidence, commit IDs, remaining blockers, rollback
steps, and a short user guide showing how to use the Roundtable controls.
```
