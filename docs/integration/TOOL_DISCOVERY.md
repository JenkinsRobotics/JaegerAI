# Tool discovery and selection

The canonical tool registry owns definitions. Each `JaegerAgent` owns its selections;
ContextVars bind that agent's state during a turn and parallel dispatch. Discovery does
not grant execution permission. Gateway grants, untrusted-content restrictions, explicit
agent catalogs and the existing executor remain authoritative.

## Behavior

- `list_tools(query, limit=5, source='')`: ranked multiword search over admitted tools;
  limit is bounded at 20. Results identify exact names, groups, availability, and selection.
- `describe_tool(name)`: schema and metadata from the admitted catalog. Missing permission
  metadata is `UNKNOWN`, never implicitly `READ_ONLY`.
- `load_tools(tools=[name])`: load up to 20 exact, available tools in the current agent.
  `load_tools(name='group')` remains compatible. Loading changes local selection state;
  it runs serially and does not authorize the underlying tools.
- Intent classification resolves against the same categories as discovery. Restrictions
  apply after classification and again before dispatch, including explicit tool lists.
- Local forced scoping and system-prompt instructions share one effective mode. Cloud
  full-tool loading remains the default; this release does not enable a local model.
- New registry snapshots are picked up before each model step. A separate agent never
  inherits another agent's explicit loads. Fresh agent instances begin with fresh selection.

## MCP inventories

The existing MCP client reads all `tools/list` pages before publication, rejecting repeated
cursors, duplicates and oversized pagination. SDK `notifications/tools/list_changed`
notifications trigger coalesced, bounded refreshes. Registry replacement validates the
entire inventory and ownership before publishing; changed/removed tools cannot leave a
partial snapshot. In-flight calls finish against their original snapshot; publication waits.
New calls are held while refresh is pending or failed, and stale function handles refuse
to dispatch. Failed refreshes retain the last complete inventory and report a failed state;
a new notification or owner disconnect/reconnect can recover it. Remote effects are never
replayed by refresh. Read-only tiers come from owner configuration, not server claims.

## Observability

The existing Gateway event bus persists `tools.selected` per model step. Shared native/web
chat renders the latest snapshot under **Tools available**, including source, selection
reason, and unavailable prerequisites. It records Jaeger's selected catalog, not proof that
a provider consumed a schema or that a tool executed. It stores no arguments, credentials,
full schemas, or private prompts. Receipts are bounded to 250 rows.

## Reuse and provenance

`packages/jaeger-agent/jaeger_agent/skill_registry/tool_search.py` adapts only the pure
BM25 retrieval, Snowball tokenization, rarest-term admission and coverage functions from
[NousResearch/hermes-agent at b7db40d82568ea68ce321ac1ead3bfea354c7f56](https://github.com/NousResearch/hermes-agent/blob/b7db40d82568ea68ce321ac1ead3bfea354c7f56/tools/tool_search_catalog.py).
The complete MIT notice is retained in that file. Jaeger's registry adapter and permission
filter are local code. No Hermes runtime or second tool dispatcher is introduced.
Snowballstemmer 3.x is a declared, bundled dependency.

The bounded, deferred discovery pattern was also compared with public Codex tool search;
no proprietary ChatGPT/Grok implementation is claimed or copied.

## Measurement and gate

A six-query smoke corpus against package + host registrations found the expected tool in
the top five for terminal commands, file search, current weather, calendar events, session
organization and inbox browsing. This is a small retrieval check, not model-quality proof.
A separate `weather forecast` probe returned no results: the registered weather tool
advertises current conditions, illustrating both conservative admission and the need to
retry/rephrase. Search is lexical, not semantic.

On that isolated catalog: full mode 159 schemas / 105,723 serialized characters;
progressive initial mode 32 / 26,078 (75.3% fewer characters); exact terminal loading
33 / 26,835. These figures exclude configured MCP servers and are not token, latency,
or end-to-end success measurements. Cloud defaults stay unchanged pending a larger
real-provider task corpus with success, extra steps, latency, and cost measurements.

## Ownership and verification

| Active owner | Repair | Evidence |
|---|---|---|
| Registry + JaegerAgent | Per-agent selection, final authority filtering, categories | Actual run-turn, concurrent agents, grant and untrusted tests |
| Existing meta tools | Ranked retrieval, exact load, truthful readiness | Multiword/bounded lookup and next-step model schema tests |
| MCPRegistry + SDK client | Pagination, atomic refresh, stale-handle protection | Paged fixtures plus real SDK notification/cancellation tests |
| Gateway event bus + shared UI | Live and persisted selection disclosure | Store projection, reload mapping, UI/type checks |

`./scripts/verify.sh` includes the discovery, scoping, owner-mode and MCP regressions.
No registry, Gateway, executor, runtime owner, data owner, or feature was replaced.
