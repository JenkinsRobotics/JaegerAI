# ADR 0005 — Schedules are a Jaeger port, ARES is a projection

Status: accepted
Date: 2026-08-23
Extends: ADR 0001 — ports, not frameworks

## Context

Scheduled prompts live in JaegerAI `state.db`. ARES also has
`jobs.json`. Treating ARES as authoritative while the bridge is up
split the SI's clock in two.

## Decision

`ScheduleStore` is a replaceable port (`add`, `list`, `cancel`). The
in-memory adapter is the contract reference. SQLite wraps the existing
`schedules` table. ARES lists the same rows as a projection through
the bridge; it does not open `state.db`.

## Consequences

- A new schedule backend implements `ScheduleStore` and passes
  `tests/contract/test_schedule_store_contract.py`.
- ARES local jobs remain `ares_local` only when Jaeger is unavailable.
