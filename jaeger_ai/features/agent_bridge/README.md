# Local agent bridge — Part 1 incomplete, Part 3 implemented

**Acceptance status:** authenticated messaging and an explicitly text-only goal
interface are implemented and locally tested. Tool execution is not promised. The proposal's explicit `rea_*` pass-through is
**not implemented**. Goal tool grants were not an equivalent replacement.
All nonempty REA grants now fail closed (501 for exact allowlisted names; 403 for
unknown/mutating names). Full Parts 1 and 3 completion must not be claimed.
See [REVIEW.md](REVIEW.md) for the security review and
[REA_FEASIBILITY.md](REA_FEASIBILITY.md) for the inspected installed API, concrete
limitations, and private-provider prerequisite.

This opt-out feature adds an authenticated local inbox and delegates goals to
Jaeger's existing Gateway admission, request receipts, PolicyKernel, approvals,
and cancellation owner. It creates no execution engine. A delivered `task`
message is inert data; only the explicit `start_goal` operation admits a text-only turn.

## Interfaces

The existing `jaeger mcp` stdio service exposes `send_message`, `list_messages`,
`get_thread`, `start_goal`, `goal_status`, `goal_result`, and `cancel_goal`.
Dedicated `ares` and `grokbot` callers have only `read` + `turn`, separate
`ares:`/`grokbot:` session prefixes, and untrusted `mcp:ares`/`mcp:grokbot` actors.
They cannot approve, administer, or impersonate the other client. HTTP MCP
relays the caller matched by its existing bearer credential. For stdio, set
`JAEGER_MCP_TOKEN_FILE` to an existing absolute, caller-owned private (0600)
credential file. Its actual token is validated through `caller_auth`; a name,
filename or `JAEGER_MCP_CALLER` flag cannot establish identity. Symlinks and
non-private files are denied. No token is generated. Without a token file,
only the existing generic `mcp` credential is used: do not configure ARES or
GrokBot that way, since generic MCP clients share that generic identity.

Gateway routes (loopback peers only, existing bearer authentication required):

| Method | Route | Meaning |
| --- | --- | --- |
| POST | `/v1/agent-messages` | Deliver message data |
| GET | `/v1/agent-messages?after=0&limit=50` | Participant-scoped inbox/sent messages |
| GET | `/v1/agent-threads/{thread}?after=0&limit=50` | Participant-scoped thread |
| POST | `/v1/agent-goals` | Start/replay authorized text-only analysis |
| GET | `/v1/agent-goals/{id}` | Canonical progress/result with thread ID |
| POST | `/v1/agent-goals/{id}/cancel` | Request canonical cancellation |

Message input: `id`, `thread`, `to`, `kind` (`task`, `status`, `result`,
`question`, `answer`), `title`, `body`, optional `refs` and `status_line`.
The server derives `from` and `created_at`; supplying either is rejected.
Identifiers contain 1–96 ASCII letters, digits, underscores or hyphens.
Text byte limits: title 256, body 16384, status line 512; at most 16 references
of 512 bytes each. Request bodies are capped at 32768 bytes, including chunked
requests. Pagination accepts limit 1–100 and nonnegative sequence cursors.
The first message fixes the two thread participants; subsequent messages cannot
add another participant. Any existing caller may address another existing caller.
There is no group delivery or unread state. Callers see only their own goal rows;
a thread recipient does not acquire authority over the sender's execution.

`start_goal(goal, workspace_folder, thread, id, rea_tools=[])` requires an
existing accessible message thread and a per-caller workspace grant. IDs make
retries durable and idempotent; reuse with changed content returns 409. Goal
progress and result use the same thread ID, via the canonical request receipt.
They do not automatically synthesize a second inbox message. The tool grant
is deliberately empty. Responses always include `execution_mode: "text_only"`
and `execution_verified: false`. Canonical request completion is projected as
`status: "text_only_completed"` with `request_status: "completed"`; it means a
text response completed, never that a file was written or a task verified.
Status/result expose text only and discard model-supplied verification/receipt
fields. Goal cancellation uses the same truthful projection. The existing
27772caf write/exec approval policy is unchanged. Usable tool delegation remains
unqualified and is not enabled by this patch. `rea_tools` is retained as a reserved input: the existing 50 exact names
in `core/agent_registry/specialists.py::REA_READ_ONLY_TOOLS` are validated, but
**every nonempty grant is refused** pending REA handle confinement. Unknown or
mutating names return 403; known names return 501 before goal admission. No
`rea_*` raw or delegated tool execution is exposed by the new bridge.

Schema migration 13 in `GatewaySessionStore` adds inbox, thread, goal-to-request
mapping, and content-free audit tables to the **session database**. Opening an
isolated store applies it idempotently; this task does not migrate the live store.
Authenticated requests share a persistent 60-per-minute bucket per caller across
all bridge endpoints, including reads. Audit rows contain caller, operation,
outcome and time, never bodies or tokens. An admitted attempt and a subsequent
validation failure have separate audit rows; both consume the bucket. Existing
auth middleware rejects missing/wrong tokens before bridge handlers run.

## Proposed later setup — requires separate approval

No production setup is performed by this patch. Later operator-approved changes:

1. Review/land the patch and back up the live session database before the normal
   Gateway start applies migration 13. Select a production maintenance window.
2. Provision/verify **separate** `ares` and `grokbot` credentials through the
   existing `caller_auth` workflow and approved credential storage. This task
   creates only test fixture tokens, no production credentials. Bind each local
   stdio client to its own approved private credential file via
   `JAEGER_MCP_TOKEN_FILE`, or its own HTTP bearer token. Never reuse a generic
   `mcp`, owner or `jaegerd` token. Any clients sharing one credential still share
   its identity/rate bucket; the filesystem owner's own processes are not an OS
   sandbox boundary. No Grok access is configured here.
3. Set a narrowly scoped Gateway environment grant, for example
   `JAEGER_AGENT_WORKSPACES='{"ares":["/absolute/approved/ares"],"grokbot":["/absolute/approved/grok"]}'`.
   Omitted, malformed or unmatched grants deny goal admission. Paths resolve
   symlinks before containment checks. Do not grant `/` or a whole home tree.
4. Register the installed local `jaeger mcp` executable with the **local Codex
   app/CLI** using its supported MCP configuration. This cloud conversation is
   not a local MCP client and gains no such connection from this patch.
5. Complete and separately qualify the missing REA pass-through first, including
   caller/thread/workspace ownership of opaque handles and canonical approvals.
   Verify REA's existing connection and owner permissions separately. Do not
   broaden its read-only list, mutate Apple Notes, or run real acceptance as part
   of configuration review.

`JAEGER_AGENT_BRIDGE=0` disables every bridge operation (including reads) at
request time. It stops new bridge admission, not already running canonical
requests; use normal cancellation/Global Stop for existing work. No launchd,
network exposure, proxy, webhook, A2A, email, outbound outbox, or Grok setup is
included. No push, deployment, or MCP registration is performed.

## Security limits and evidence

The shared existing redactor masks recognized secret patterns before message
persistence/return and goal admission/result return. It cannot identify arbitrary
secrets, encoded secrets, sensitive project information, or all credentials.
Do not paste secrets. Reference text is not fetched. Message contents never
become tool grants, approvals, identities, or configuration. Workspace grants
bound admission; normal runtime policy remains essential. REA handles have no
bridge confinement yet, so nonempty REA grants are refused. This is not an OS
sandbox against the Mac's owner.

`dev/tests/jaeger_ai/core/test_agent_bridge.py` uses temporary stores, caller
fixture tokens, an ephemeral loopback Gateway, a deterministic delegate, and a
real MCP stdio subprocess. It proves transport, storage, admission, identity,
denials, redaction, pagination, rate limits and lifecycle contracts. It does not
prove live-provider execution, Grok round-trip/webhook delivery, secret-detection
perfection, installed-client setup, or real REA analysis. No model downloads or
paid provider calls are needed. Only task-owned test processes are cleaned up.

The required identity/outcome review fixes and their current test commands are
recorded in [REVIEW_FIXES.md](REVIEW_FIXES.md). Earlier review documents describe
previous snapshots; this README and REVIEW_FIXES.md describe the committed result.
