# ADR-0014: Gateway-owned agent peers and operator continuity

**Status:** Accepted
**Date:** 2026-11-07

## Context

Jaeger already authenticates Grok Bot, Muse, Hermes, ARES, local agent apps,
and workers as distinct callers, but clients had no canonical read model for
those peers. Separate bridge and UI lists could therefore drift. The current
conversation was also partly held in one Gateway process variable, so a Mac,
iPhone, browser, or IDE could reconnect to a different conversation after a
restart.

The useful behavior across the compared agent systems is complementary:
stable peer identities and direct addressing, one durable main thread across
devices, durable queues and approvals, and a Gateway that owns sessions while
models and clients remain replaceable.

## Decision

The Gateway owns both contracts:

- `caller_auth.CALLERS` remains the authority for an agent peer's identity,
  credential, scopes, session namespace, transport, and framework binding.
  `GET /v1/agent-peers` is a read model generated from that registry. It is
  discovery, not a second writable agent registry.
- `GatewaySessionStore.operator_state` stores the active owner conversation as
  a revisioned SQLite record. Owner clients read or compare-and-set it through
  `GET/PATCH /v1/operator/session-state`.
- Creating a session, accepting an owner turn, and queuing an owner follow-up
  select that session. Deleting the selected session clears it. Each change
  publishes `session.active.changed` on the global Gateway stream.
- External agent callers keep their existing session prefixes and may discover
  the peer catalog, but cannot read or change the operator's active session.

## Consequences

- Mac, iPhone, WebUI, and IDE clients can reconnect to the same conversation
  after a Gateway or client restart.
- Stale device writes receive a revision conflict instead of silently
  overwriting a newer selection.
- Grok Bot, Muse, Hermes, and future agent bridges use the same authenticated
  peer facts as every client projection.
- The persistent Jaeger entity remains separate from conversations: this
  record selects a conversation window and does not replace entity memory,
  identity, runs, tasks, approvals, or agent-to-agent messages.
- Clients must project these contracts through the Gateway API and event
  stream; they must not open the SQLite database directly.
