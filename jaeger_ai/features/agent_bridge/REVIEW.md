# Agent bridge focused review — 2026-10-18

Base: `782914e82cf9898f8d132e7a4569387b55c193ec`.
Branch: `feat/agent-bridge`. All changes remain uncommitted in the separate
`/Users/matthewjenkins/Documents/Codex/2026-10-18/task-2/agent-bridge` worktree.

## Acceptance correction and REA feasibility

**Part 1 is incomplete.** The proposal explicitly requested read-only `rea_*`
pass-through for 50 existing tools. The previous optional goal tool grant was
not an equivalent implementation, and the initial report overstated completion.
Part 3 messaging and the ordinary MCP goal lifecycle are implemented/tested;
full Parts 1 and 3 acceptance must remain open until REA is complete.

The closed 50-name list exists at
`jaeger_ai/core/agent_registry/specialists.py::REA_READ_ONLY_TOOLS`. It is an
appropriate necessary check, but not a sufficient authorization boundary:

- `jaeger_ai/plugins/mcp/client.py::check_mcp_permission` applies existing
  `PermissionPolicy`; the registered tool wrapper calls this before dispatch.
  Calling `MCPRegistry.call` directly skips that wrapper. A new REST route must
  never dispatch directly just because a tool is labelled read-only.
- `packages/jaeger-agent/jaeger_agent/tool_executor.py::HookedToolExecutor`
  already owns the PolicyKernel/authority/confirmation boundary. Bypassing it
  or constructing a separate approval interpretation would duplicate authority.
- The registry's `MCPToolSpec` and `MCPRegistry.call` carry tool metadata and
  arguments, but no caller/thread/workspace ownership of REA binary/session
  handles. REA operations accept existing opaque handles as well as paths.
  A valid allowlisted name and an approved workspace directory do not prove
  the handle refers to an artifact inside that workspace. Canonical workspace
  read-root checks for native file tools do not automatically constrain an
  external MCP server's file access.

Therefore a narrow path-only proxy is insufficient for the requested 50-tool
surface. A safe implementation needs a server-backed handle ownership contract
(or equivalent isolated REA context), strict argument/handle validation for all
50 tools, and an admitted operation through the existing execution/approval
owner. This patch has no such trusted handle metadata to verify. Returning
success based on local mocks would not prove that boundary. No REA server,
credentials, registration, network, or production instance was changed to
manufacture one.

**Fail-closed correction:** unknown/mutating names return 403. Every nonempty
exact allowlisted REA grant now returns 501 *before* any goal/session admission
or tool execution. No new `rea_*` proxy is registered. Ordinary goals retain
an empty tool grant and the normal Gateway authority path. Existing unrelated
MCP/chat behavior is unchanged. Completing REA is a remaining implementation
and acceptance item, not merely a deferred live test.

## Focused security review

| Boundary | Result and evidence |
| --- | --- |
| Sender spoofing | REST rejects `from` and `created_at`; `from` comes only from `request['caller'].name`. MCP has no sender parameter and relays a proven caller token. Absent/wrong HTTP auth cannot fall back to the service token. Cross-client impersonation is covered by auth and bridge tests. |
| Thread recipients | First delivery fixes two existing caller identities. Only those participants may read/reply; a third caller cannot reuse the thread to add recipients. Pagination filters both sent and received rows by authenticated identity. No unread marker exists. |
| Goal workspace | Existing absolute directory required; both target and configured grant roots resolve symlinks before containment checks. Relative paths, malformed/missing grants, `/`, whole-home roots and symlink escapes are denied. This is admission confinement, not an OS sandbox against the owner's filesystem mutations after admission. No REA tool access is granted. |
| Cancellation | Goal lookup is keyed by authenticated caller and goal ID, with thread access checked again. A different caller, including the legitimate message recipient, cannot inspect/cancel the sender's goal. Own cancellation uses the existing Gateway cancellation registry; absent/wrong bearer returns 401. |
| Kill switch | `JAEGER_AGENT_BRIDGE=0` is checked at every new REST and MCP operation, including reads/HEAD/status/result/cancel. Tests enumerate all new entry points. It stops bridge admission/access; it does not terminate already-running canonical work. Normal Gateway cancellation/Global Stop remains the owner. |
| Fixture auth | Tests use the repository's unique `/tmp/jaeger-tests-*/caller-tokens` fixture directory, mode 0600 files and temporary HOME/state. A test makes any Keychain subprocess access fail. The MCP subprocess strips credential-shaped TOKEN/API_KEY/SECRET/PASSWORD environment variables and inherits only fixture caller-token location. Real transport asserts an ephemeral endpoint rather than `:33418`. |
| Approval authority | No message delivery or goal input creates an approval, changes a caller, or executes a raw tool. Normal goals enter `handle_send_turn`; the real PolicyKernel denies the deterministic outside caller's terminal proposal. REA remains disabled rather than bypassing confirmation to claim success. |
| Audit/privacy | Existing redactor masks recognized content patterns; audit rows contain operation/caller/status/time, no bodies/tokens. Canonical handler error responses now also generate failure audit records. Redaction cannot detect arbitrary/encoded secrets. |

Remaining limits: all clients sharing `mcp` credentials share one identity and
rate bucket; setup must not claim isolation between them. The deterministic
delegate proves transport/admission/lifecycle, not provider execution or live
REA analysis. Grok round-trip, webhook/outbox, installed Codex configuration,
production migration, real tokens, balenaEtcher acceptance and Apple Notes
mutation were not performed.

## Reproducible checks

Run from the worktree. These exact commands redirect HOME/state/config/cache
outside the checkout. Repository test fixtures further replace caller auth
with unique ephemeral files. Loopback tests require the sandbox's socket-bind
permission; no live gateway is contacted.

```sh
HOME=/tmp/jaeger-agent-bridge-checks/home JAEGER_STATE_DIR=/tmp/jaeger-agent-bridge-checks/state JAEGER_CALLER_TOKEN_DIR=/tmp/jaeger-agent-bridge-checks/tokens PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:packages/jaeger-agent:packages/jaeger-os /Users/matthewjenkins/.jaeger/venv/bin/python -m pytest dev/tests/jaeger_ai/core/test_agent_bridge.py dev/tests/jaeger_ai/core/test_gateway_caller_auth.py dev/tests/jaeger_ai/interfaces/test_mcp_bridge_authority.py dev/tests/jaeger_ai/core/test_gateway_durability.py -q -o cache_dir=/tmp/jaeger-agent-bridge-checks/cache

HOME=/tmp/jaeger-agent-bridge-checks/home JAEGER_VENV=/Users/matthewjenkins/.jaeger/venv JAEGER_STATE_DIR=/tmp/jaeger-agent-bridge-checks/state JAEGER_CALLER_TOKEN_DIR=/tmp/jaeger-agent-bridge-checks/tokens ./scripts/verify.sh

HOME=/tmp/jaeger-agent-bridge-checks/home JAEGER_VENV=/Users/matthewjenkins/.jaeger/venv JAEGER_STATE_DIR=/tmp/jaeger-agent-bridge-checks/state JAEGER_CALLER_TOKEN_DIR=/tmp/jaeger-agent-bridge-checks/tokens dev/scripts/run_tests.sh --smoke

/Users/matthewjenkins/.jaeger/venv/bin/ruff check --no-cache jaeger_ai/features/agent_bridge dev/tests/jaeger_ai/core/test_agent_bridge.py
/Users/matthewjenkins/.jaeger/venv/bin/ruff format --check --no-cache jaeger_ai/features/agent_bridge dev/tests/jaeger_ai/core/test_agent_bridge.py
git diff --check
```

Logs: `/tmp/jaeger-agent-bridge-checks/review-focused.log`,
`review-verify.log`, and `review-smoke.log`. Final results are supplied with the
patch delivery. Modified existing files retain baseline lint debt; new bridge
files have clean lint/format checks. No push, PR, merge or deployment occurred.
