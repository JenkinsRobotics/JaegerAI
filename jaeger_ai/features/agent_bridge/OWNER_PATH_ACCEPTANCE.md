# Isolated production OWNER-path acceptance

This follow-up fixes bridge goal routing and adds an execution acceptance test.
It does not assert live deployed acceptance. The external report about deployed
`f66270c4` and other test counts is not independent test evidence here; its patch
and manifest remain unchanged. No live settings, keys or Gateway were used.

## Regression and fix

The first full-path test completed with `unknown tool 'write_file'` instead of
asking for approval. Its durable receipt showed `agent_id=native:gateway`,
`role=specialist`. `_auto_route` had triaged the unpinned bridge session into the
Gateway specialist, whose standing tools then excluded `write_file`.

Bridge root admission now pins the existing `LEAD_AGENT_ID` with
`agent_pinned=true` and `route_checked=true`, using the same session metadata
pattern as canonical host-assigned sessions. It does not bypass specialist
standing-tool intersection for deliberately delegated children. Existing goal
retries retain their original frozen grant. No authority policy or caller scope
is broadened.

## Exact tested runtime path

1. A fixture-token authenticated HTTP `POST /v1/agent-messages` stores inert data.
2. `POST /v1/agent-goals` validates caller, thread and workspace and pins the lead.
3. `handle_send_turn` admits the canonical durable request and starts
   `_execute_turn` with its frozen execution snapshot and authenticated actor.
4. `_execute_turn_inner` executes unchanged: real `prepare_turn`, strategy
   selection, TaskOwner card opening and owner-side continuation.
5. `_owner_react_turn` binds real task/tool/read scopes and calls the actual
   `EntityRuntime.run_subordinate_react` in a separate temporary OWNER instance.
6. `build_jaeger_agent` builds the real JaegerAgent. `TurnExecutive` and real
   SQLite run/commitment/effect stores own the run and persist its identifier.
7. A scripted model requests native `write_file`. The real executor,
   AuthorityLayer/PolicyKernel and permission decorator reach
   `_GatewayToolConfirmationProvider`; the file is absent while its card waits.
8. Fixture ares/grokbot/mcp callers receive403 when attempting approval. Fixture
   owner CLI approval allows native file I/O; the real model loop reads back the
   actual file. Denial/cancellation leave no file, and late approval after cancel
   returns409.
9. GatewayTaskOwner closes/verifies the real task and the bridge projects the
   canonical receipt in the original thread. The approved run reports
   `completed_verified`, `execution_verified=true`, role `lead`, actor `mcp:ares`,
   native session prefix `owner:` and a durable native run ID. The deny case has
   task state `blocked` and false verification; cancellation is `cancelled`.

The approved file's exact SHA-256 is
`1351a27cd031fbc5446940d4d044bc19a4f3440b2b94bc991294dbdb81c86355`.
The JUnit evidence records decision, run ID, actor, task state, file hash, real
write/read results and the adapter-construction stack through the owner runtime.

## What is and is not substituted

Only model-client construction/selection and adapter transport are scripted.
Peripheral framework/model capability inventories are empty fixtures to prevent
health discovery against operator services while compiling context. A socket
connect guard accepts only the test-owned ephemeral HTTP port. The instance has
its own config, identity, resident lock, memory, event stores, task/run databases
and an empty MCP registration. It uses no model weights, paid provider or keys.

Gateway startup background work is disabled and background summary scheduling is
disabled. `_execute_turn_inner`, `_owner_react_turn`, `run_subordinate_react`,
`prepare_turn`, `finish_turn`, agent construction/loop, policy, approvals, native
file I/O and TaskOwner verification are not replaced. Identity assertions and
captured runtime stack make that boundary reviewable. This is stronger evidence
than the earlier tests that replaced `_execute_turn_inner` with a model harness.

It still is not a live Codex/provider deployment test. Full normal-tool coverage
and direct REA retain the separate documented limits in
[FOLLOWUP_INTEGRATION.md](FOLLOWUP_INTEGRATION.md) and [PHASE2_REA.md](PHASE2_REA.md).
