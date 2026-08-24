# ADR 0004 — Tool execution is a port, not a loop detail

Status: accepted
Date: 2026-08-23
Extends: ADR 0001 — ports, not frameworks

## Context

The loop already chose *which* declared tool to call. It also invoked
`ToolDef.dispatch()` itself. That fused selection with execution, so a
host that needed a sandbox, a remote worker, an audit wrapper, or a
test double had to edit `JaegerAgent`.

ADR 0001 says the model proposes and the store decides. The same split
applies here: the loop proposes a tool name and arguments; an executor
performs the call.

## Decision

`ToolExecutor` is a runtime-checkable protocol with one method:
`execute(tool, arguments)`. The production adapter is
`DirectToolExecutor`, which calls `ToolDef.dispatch()` and therefore
keeps the existing validation behaviour.

`JaegerAgent` accepts an optional `tool_executor`. The default is
`DirectToolExecutor`, so hosts that do not inject one see no behaviour
change. Serial and parallel dispatch both go through
`_execute_prepared`, which is the only call site.

A substitute executor that passes
`tests/contract/test_tool_executor_contract.py` can stand in without
changing the loop or the tool definitions. The architecture fitness
test forbids `JaegerAgent` from calling `.dispatch` directly.

## Consequences

- Sandbox / remote / audited executors are additional adapters, not
  loop forks.
- `LedgerToolExecutor` wraps `once()` for tools whose `side_effect` is
  `external` (`send_email`, `send_message`). The loop default remains
  `DirectToolExecutor` so hosts opt in. Silent retry of an email is
  still forbidden once a host injects the ledger executor.
- Bridge verbs `list_runs`, `list_commitments`, `list_effects`,
  `deliver_event`, `resolve_effect`, and `abandon_effect` expose the
  durable runtime without ARES opening `state.db`.
