# Durable live steering admission

Gateway POST `/v1/sessions/{id}/requests/{request_id}/steer` remains live
ReAct guidance, not a second turn. A client that needs retry safety must
supply a stable `steering_id` and reuse it with the same normalized text.
Legacy POSTs without an ID still receive a generated ID; anonymous
resubmission after a lost response has no cross-request deduplication guarantee.

Schema 20 adds `steering_admissions` without modifying historical requests,
activity, queues, approvals, cancellation, or owner/background journals.
Legacy `turn.steer` activity remains the success receipt and is still readable.
Admission tombstones intentionally survive supported request/session cleanup.
Deleting a session and reusing its request/steering IDs cannot erase uncertain
delivery or grant a new producer permission to replay it.

Admission is committed before delivery. A producer capability, the admitted
request identity, payload, session, and current Gateway lease/source bind the
reservation. A second committed, single-use dispatch claim precedes the
synchronous agent call. Request status/ownership and cancellation are checked
again at delivery; a write transaction fences persisted ownership/cancellation
changes while that call runs. Neither reservation nor dispatch claim means the
agent accepted guidance. Only the post-injection `turn.steer` receipt records
confirmed queue acceptance, not eventual model consumption.

An interruption or exception before/during/after delivery leaves a durable
unknown outcome. Retries and GET return 503 with `delivery_unknown` and never
inject again. A known agent refusal is retained as `rejected` (409). Unknown delivery uses
503 so existing clients retain the steering identity rather than offer a new
queued turn after a definite rejection. A failed write
returns a sanitized 503, and callers must read/retry the **same** ID rather
than create a replacement. A successful retry reads the original receipt.
Changing text under an existing identity returns a conflict. There is no
automatic replay or recovery promotion of unknown steering, even when a
crash happened before the agent call. This intentionally favors at-most-once
delivery over guaranteed delivery.

Focused checks: `test_gateway_steering_admission.py` and
`test_gateway_live_steering.py` under `dev/tests/jaeger_ai/core/` cover durable
failure windows, reopen, concurrent admission, producer/lease changes,
cancellation, rejection, payload conflicts, legacy receipts and API behavior.
Run using the repository's isolated Python test environment with external
state, home, bytecode, and pytest cache directories.
