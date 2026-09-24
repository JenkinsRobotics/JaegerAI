# Gateway task ownership

The Jaeger Gateway owns admission, execution receipts, background task scheduling,
cancellation and result delivery. IDE, WebUI, native app and terminal clients use
its REST/SSE contract. `jaeger gateway daemon` starts the owner; bare `jaeger
gateway` still manages the separate external Agentgateway proxy.

## Persistent work

`POST /v1/tasks` accepts an objective, originating session, execution choices and
optional artifact paths. `request_id` identifies the originating submission;
repeat it with the same objective/configuration to recover the same task. Different
user requests can intentionally repeat an objective. Model-created tasks get their
parent, execution choices and authorization context from the running Gateway, not
from tool arguments. Explicitly requested background work is admitted immediately;
unsolicited proposals use the existing approval channel.

Tasks, client request receipts, orchestration records, activity history and the
completion outbox share `gateway_sessions.sqlite3`, resolved through
`operator_state_root()`. Identity and memory retain their existing authoritative
stores; they are not copied into another agent or replaced with UI state.

A task owns a child session and successive bounded execution slices. A slice may
yield without completing the task. Its native run identity, tool effects, agent
messages and work ledger persist across continuations. Completion requires outcome
evidence; returning prose alone does not complete durable work. Artifact receipts
are rechecked against the current file before delivery. These checks establish
artifact integrity, not the semantic adequacy of an arbitrary report.

Cancellation requests wait for the current execution/effect receipt. Unknown effects
remain indeterminate until reconciliation; ordinary approval cannot restart them.
Results are inserted once into the originating session under a stable delivery ID.
Deleting a parent session does not erase the task result or cause replay elsewhere.

## Client projections

`GET /v1/tasks` and `GET /v1/tasks/{id}` expose persisted state.
`POST /v1/tasks/{id}/cancel` requests cancellation. Task changes publish session
SSE events. The IDE shows active child tasks while foreground work continues;
opening a task uses its ordinary chronological conversation history.

The terminal and native bridge default to Gateway execution. The explicit
`JAEGER_BRIDGE_EXECUTION=local` mode remains for isolated protocol diagnostics.
It is not an automatic recovery fallback. Legacy Deep Think board cards imported
at startup are retained as history projections and excluded from old queue pickup.

## Recovery boundaries

Gateway task recovery uses admitted request and effect receipts, not a blanket
"mark everything queued" pass. External IDE worker admission and terminal results
are persisted. An external worker without a recoverable terminal receipt is shown
as unknown after an owner crash; it is never silently launched again. External
CLI process reconciliation is a remaining boundary, not evidence of successful
completion.

Regression coverage includes actual Gateway/agent/tool execution in an isolated
child process, result verification, process restart, identical request replay,
cancellation races, completion overflow and client activity during foreground work.
Installed-client acceptance must be recorded separately from these tests.
