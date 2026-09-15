# Draft upstream PR: restore session history in `POST /v1/runs`

## Problem

`POST /v1/runs` accepts a `session_id`, but starts with empty conversation history when the
caller omits explicit history. A second turn therefore loses the first turn even though the
native SessionDB contains its structured messages. The separate session chat endpoint already
loads that history, so the two native entry points disagree.

## Proposed change

When a Runs request has `session_id` and does not provide explicit history:

1. Open the adapter's SessionDB through the existing database accessor.
2. Resolve the resumable session identity with the same rule used by native session routes.
3. Load `get_messages_as_conversation(session_id)` and pass the returned structured messages
   to the agent unchanged.
4. Fail the request with a clear server error if the database was expected but could not be
   opened. Do not silently run a contextless turn.
5. Keep caller-supplied history authoritative when it is present.

Do not flatten assistant tool calls or tool results into text. Their role, call ID, arguments,
and result fields are required for correct continuation.

## Tests

- Two Runs requests with the same `session_id`; the second sees the first user and assistant
  messages.
- A stored assistant tool call plus tool result reaches the agent with the same structure.
- Explicit request history overrides SessionDB history.
- A compression-resumed session resolves to and loads the active session.
- A database-open failure returns an error instead of invoking the agent with empty history.

## Jaeger transition

Jaeger currently supplies this behavior through a composition adapter. Once the released
Hermes version contains the fix, Jaeger's construction-time check should detect the upstream
capability and remove its history proxy.
