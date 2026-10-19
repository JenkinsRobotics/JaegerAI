# Agent bridge — Phase 2

Base: `1ab5e31221fdf93e0447f2e872d227be752ff0c3`. Phase 2 keeps the authenticated
inbox and dedicated `ares`/`grokbot` callers, adds a durable webhook outbox, and
enables a bounded native-file goal toolset through the ordinary Gateway owner,
PolicyKernel, executor and approval cards. It does not enable shared-target REA.

| Scope | Implementation / acceptance |
| --- | --- |
| Authenticated local inbox and MCP/REST | Retained from Phase 1; caller/thread/goal isolation remains enforced. |
| Webhook outbox | Implemented and tested with an isolated fake receiver. Real HTTPS endpoint/Grok acceptance is deferred. |
| Tool-enabled goals | Seven existing native file tools, subject to workspace confinement and existing owner approvals. Full lead catalog and privileged exec are not exposed. |
| Direct REA | No tools supported. All 50 exact allowlisted names remain explicitly unavailable pending private provider/resource confinement. |

## Local interfaces and identity

The existing `jaeger mcp` service exposes `send_message`, `list_messages`,
`get_thread`, `start_goal`, `goal_status`, `goal_result`, and `cancel_goal`.
Loopback REST uses the same implementations:

| Method | Route |
| --- | --- |
| POST / GET | `/v1/agent-messages` |
| GET | `/v1/agent-threads/{thread}` |
| POST | `/v1/agent-goals` |
| GET | `/v1/agent-goals/{id}` |
| POST | `/v1/agent-goals/{id}/cancel` |

Dedicated `ares` and `grokbot` credentials confer only `read` + `turn`, separate
session prefixes, and untrusted `mcp:ares` / `mcp:grokbot` actors. They cannot
approve, administer or impersonate another caller. HTTP relays the authenticated
bearer token. Stdio binds `JAEGER_MCP_TOKEN_FILE` to an existing absolute,
owner-private regular credential file and validates the actual token. A caller
label or filename is not authorization. Generic `mcp` clients continue to share
the generic identity; clients must not reuse another caller's credential.

Message fields are `id`, `thread`, `to`, `kind` (`task`, `status`, `result`,
`question`, `answer`), `title`, `body`, optional `refs` and `status_line`.
The server owns `from` and `created_at`. First delivery fixes two thread
participants. Only they can read/reply; a recipient cannot inspect/cancel the
sender's goals. IDs are caller-unique; thread IDs are globally unique and should
be random. Cursor pagination accepts nonnegative `after` and limit 1–100.
There are no group deliveries or unread markers. Messages are inert data;
storing a `task` message never admits tool execution.

## Durable webhook outbox

Schema migration **14** adds `agent_webhook_outbox` in the session database.
Each new message to `grokbot` inserts one outbox row in the **same transaction**
as its thread/message. Duplicate delivery IDs do not create another row. Oversize
wire bodies roll back the entire message transaction. Migration does not backfill
historical messages or activate delivery by itself.

The explicit JSON projection contains message fields only: no attachments,
credentials, configured URL or downloaded references. Serialized UTF-8 must be
at most **16 KiB**, including the complete envelope; message field limits alone
do not guarantee it fits. The existing redactor masks recognized secret patterns
before persistence. It cannot identify arbitrary, encoded or project secrets.
Never put secrets in messages or identifiers.

Delivery is off unless the bridge is enabled, `JAEGER_AGENT_WEBHOOK_HOST` is a
valid exact lowercase DNS host, and both credential entries exist. The read-only
credential provider uses Keychain service `ai.jaeger.bridge.webhook`, accounts
`grokbot-url` and `grokbot-key`. It creates no entries. The URL and key remain in
memory only and are never stored in the database, logs or exception messages.
No credential provider was invoked against the live Keychain in this task.

Production transport accepts verified HTTPS only, default port 443, exact host
match, no userinfo, fragments, ambiguous host spelling or redirects. It does not
inherit proxies or accept a custom insecure TLS context. The request uses
`Authorization: Bearer <key>`, JSON content type and a stable
`Idempotency-Key` of `<sender>:<message-id>` because IDs are caller-unique.
Tests rewrite to a task-owned loopback receiver only inside an injected test
transport, after the unchanged production URL validator has accepted a fake
HTTPS configuration. No external webhook is contacted by tests.

Rows progress through `pending` → leased `sending` → `delivered` or `failed`.
A 2xx acknowledgement alone marks delivery; enqueue success does not. Each
attempt has a 10-second timeout, a 60-second lease and a unique claim token.
At most five claimed attempts are made with exponential backoff capped at
300 seconds. Expired leases recover after a crash; stale workers cannot
acknowledge a newer lease. Shutdown cancels only this worker and leaves a
recoverable lease. SQLite failures keep queued work durable without logging it.

Semantics are **at least once**, not exactly once: the receiver can accept a
request before the sender loses its response or crashes. The receiver must
apply the stable idempotency key. `delivered` means HTTP acknowledgement, not
proof that Grok executed a task or returned a result. Terminal failure requires
operator review; do not blindly create a new ID, since a prior uncertain
attempt may already have reached the receiver.

`JAEGER_AGENT_BRIDGE=0` blocks new bridge operations and new send attempts.
An already-started HTTP request cannot be retracted; it remains bounded by the
request timeout. The switch does not terminate canonical goals; normal
cancellation/Global Stop owns them. Goal tool path guards also recheck the bridge
switch before dispatch, including after an approval wait.

## Policy-controlled goal tools

`start_goal(goal, workspace_folder, thread, id, rea_tools=[])` still requires a
participant-accessible thread, an existing absolute workspace and a matching
per-caller `JAEGER_AGENT_WORKSPACES` grant. Symlinks resolve before containment
checks. IDs make retries durable; changed content with the same ID returns 409.

The grant comes from the lead's existing native-file catalog, limited to tools
with bounded path contracts: `read_file`, `write_file`, `append_file`, `patch`,
`delete_file`, `move_file`, `copy_file`. No parallel tool engine or new approval
authority is created. Host-bound confinement comes from the authenticated,
durable goal admission, not a model flag. Paths are checked against that goal's
workspace before policy, after hook/approval changes and in the native resolver
at file access. Directory/special-file cases that cannot be bounded fail closed.
This is not an OS sandbox against concurrent filesystem changes by the Mac owner.

The existing 27772caf write/exec card behavior is preserved. Writes can wait for
an authenticated owner principal; ARES/GrokBot cannot resolve those cards. Denial
or cancellation cannot become an approved write. Privileged shell/code remain
denied to outside callers by the existing kernel. Other external or unscoped
lead tools are unsupported in bridge goals; this is a deliberate incomplete
portion of the requested full lead toolset, not an authorization workaround.

Responses report `execution_mode: "policy_controlled_tools"`. A completed model
response is `completed_unverified` unless the canonical durable task owner has
independently verified the exact matching request/session; model-supplied receipt,
task-state or verification claims never set `execution_verified`. Cancelled,
failed and running states remain explicit. A real file effect and independently
verified task completion are different claims.

All nonempty `rea_tools` grants remain blocked: unknown/mutating names return
403, known names return 501 before admission. [PHASE2_REA.md](PHASE2_REA.md)
lists the precise unsupported set and prerequisite; no shared live REA process
or Hopper context is used.

## Later operator setup — separate final approval/action

1. Review and land this commit; back up the session database before a separately
   approved Gateway maintenance window applies migration 14. No deployment occurs
   in this task. Old messages are not automatically forwarded.
2. Review any queued messages before activating outbound delivery. Select one
   approved HTTPS endpoint and exact host. URL/key provisioning is a **separate
   final step** Matthew performs in secure Keychain entry: generic-password
   service `ai.jaeger.bridge.webhook`, accounts `grokbot-url` and `grokbot-key`.
   Do not put values in shell history, source, command arguments, logs or chats.
3. In the separately approved Gateway environment, set
   `JAEGER_AGENT_WEBHOOK_HOST=hooks.example.com` using the actual approved host.
   No wildcard, IP literal, custom port or redirect is accepted. Provisioned
   credentials plus this host enable future sends after normal startup; this
   task does not alter launchd, network settings or the running Gateway.
4. Preserve separately provisioned `ares`/`grokbot` credentials and narrow
   `JAEGER_AGENT_WORKSPACES` entries. No token, Keychain, registration or Codex
   setup is created/changed here. The local Codex integration is distinct from
   this cloud conversation.
5. Qualify the real endpoint's idempotency and 2xx behavior separately before
   claiming Grok round-trip acceptance. Private REA provider isolation remains
   a separate prerequisite. No webhook, email fallback or A2A setup is performed.

Validation details and exact commands are recorded in
[PHASE2_VALIDATION.md](PHASE2_VALIDATION.md). Earlier `REVIEW*` documents describe
Phase 1 snapshots and are retained as history.
