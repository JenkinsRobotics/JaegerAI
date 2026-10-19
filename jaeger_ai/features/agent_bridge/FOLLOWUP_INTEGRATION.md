# Follow-up: canonical teams and remaining normal-tool integration

The delivered `f66270c4` commit and its patch/manifest remain immutable. This
follow-up uses the existing team dispatcher; it does not create another worker.

## Implemented integration

`tools/call_agent.py` already submits handoffs over authenticated Gateway HTTP.
`server.handle_handoff_agent` persists them; `_execute_handoff` invokes
`NativeSpecialistRuntime`, whose `_specialist_chat` admits a normal child turn.
The child then uses `_execute_turn` / `_owner_react_turn`, normal AuthorityLayer,
PolicyKernel, tool executor, confirmation provider, durable receipts and cancel.

The missing origin propagation is now implemented. Handoff metadata records the
authenticated caller actor and a validated root bridge admission. Deterministic
specialist session/request identities bind descendants to that record; editable
session metadata alone cannot opt into bridge authority. Children inherit and
revalidate the root workspace, current caller grant, kill/cancel state and tool
ceiling. A specialist's standing tools are intersected normally. Handoff approval
cannot remove write approvals, change actor, choose a foreign project/workspace,
or restore an unrestricted grant. Retries compare root identity. Result lookup
and cancellation operate only on that root's handoffs. Depth/ancestry come from
durable host records instead of model-supplied chain flags.

Isolated tests run actual call_agent/run_team HTTP, the real specialist runtime,
canonical child admission/standing-tool intersection, and real file dispatch.
Only the model transport and caller credentials are test fixtures. Owner handoff
approval precedes a separate owner write approval and an actual temporary file.
Cancellation at either wait leaves no file; outside callers cannot approve.

## Why removing allowed_tools alone is not full acceptance

`server._owner_react_turn` deliberately interprets absent `allowed_tools` as the
owner's normal registered catalog. The initial bridge selected seven native file
tools, so `call_agent/run_team` were excluded before canonical team dispatch.
This follow-up removes that particular gap by granting the three canonical team
tools. It does not label every other lead tool permanently unsupported.

Two existing contracts still prevent claiming the entire normal catalog:

1. `core/authority/kernel.py::_check_identity_trust` returns DENY for shell,
   remote shell, arbitrary code, deployment and push from `mcp:*` actors, before
   commissioning/approval checks. Preserving caller identity across children
   preserves that denial. Neither an `allowed_tools=None` grant nor a handoff
   approval changes it. Making bridge exec raise a card requires a deliberate
   authority-policy change, limited to host-bound goals and owner approval;
   changing the actor to owner would be privilege laundering. This follow-up
   does not expand that policy.
2. `ToolDef` defines argument schema, side_effect, permission_tier and availability,
   but no per-caller resource contract or workspace ceiling for arbitrary tools.
   The owner's normal catalog includes `get_credential`/`set_credential` and host
   tools whose bodies do not use native workspace resolvers. Native file
   `read_confinement` cannot confine those implementations or arbitrary MCP
   providers. Merely selecting the catalog is not a workspace/access proof.

The remaining code work is canonical capability/resource-policy integration for
those normal tools, rather than maintaining another manually enumerated catalog.
The minimum policy decision is whether outside bridge shell/code should remain
DENY or become per-call owner-approvable within an enforceable goal boundary.
There is no need to broaden caller token scopes, touch live configuration, or
provide secrets to make that decision. Until it is resolved and tested, the
full normal lead toolset requirement remains explicitly unfinished.

## Direct REA

A private provider/handle adapter can be written in code without live access.
The concrete real-provider qualification failure and input contracts are in
[PHASE2_REA.md](PHASE2_REA.md). Private-process scaffolding plus mocked isolation
would not prove all 50 real operations confined. A working private resource
boundary/provider contract remains the acceptance prerequisite. No Grok or real
balenaEtcher acceptance is claimed.
