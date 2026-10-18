# Approved review fixes: identity and truthful outcomes

This is the current review record. `REVIEW.md` and `REA_FEASIBILITY.md` preserve
prior snapshot findings. Work remains based exactly on
`782914e82cf9898f8d132e7a4569387b55c193ec`, branch `feat/agent-bridge`.

## 1. Dedicated authenticated caller identities

Confirmed: previously all unconfigured stdio clients shared `mcp`. Added fixed
`ares` and `grokbot` CallerSpecs, each with only `read` and `turn`; neither has
`approve`, `admin`, `delegate` or `stop`. Their session prefixes are `ares:` and
`grokbot:`. Actors are `mcp:ares` and `mcp:grokbot`, so existing PolicyKernel
untrusted-caller rules still apply, including privileged shell/code denial.

HTTP MCP accepts each caller's existing bearer token and relays it unchanged.
Stdio uses `JAEGER_MCP_TOKEN_FILE`: an existing absolute, owner-private regular
file, opened without following symlinks. Its token is matched by the existing
CallerAuthenticator. A filename, sender field or `JAEGER_MCP_CALLER` label cannot
establish identity; an invalid credential fails closed. HTTP authentication
failure never falls back to a stdio credential. Dedicated tokens also retain
their identity/session prefix through legacy MCP chat/cancel forwarding.

No production credential is minted or configured. Tests add only disposable
0600 fixture credentials. Later approved local setup must give ARES and GrokBot
different credentials. Leaving a client on generic `mcp` explicitly leaves it
in the generic shared identity; the code does not guess which app invoked it.

Private threads are participant-scoped. A legitimate message recipient can read
and reply to that thread, but cannot control or inspect the sender's goals.
Thread IDs remain globally unique; callers should generate random identifiers
rather than common labels. Their collision is denied, not reassigned.

## 2. Explicit text-only outcome contract

Confirmed: the original goal route freezes `allowed_tools=[]`. It cannot execute
a requested write. Simply removing that grant would widen access before REA and
tool/resource confinement were qualified. This patch takes the review's approved
truthful-text-only alternative instead of claiming usable tool delegation.

Every new goal response now includes:

- `execution_mode: "text_only"`
- `execution_verified: false`
- `status: "text_only_completed"` when the canonical request finishes with text
- `request_status: "completed"` retaining the underlying lifecycle state
- `result.output` containing redacted text only

`goal_status`, `goal_result`, start/replay, and cancellation use one projection.
Model-supplied verification flags, task states and receipts cannot become bridge
execution evidence. A textual `write_file(...)` or “verified” claim remains
unverified text and is never represented as a verified effect.

The 27772caf write/exec card behavior is already in the approved base; it is
unchanged. Its four existing regression tests are included in the focused run.
Neither new caller can resolve an approval. Tool-enabled delegation remains a
separate implementation/acceptance item; no normal policy gate is bypassed.

## Evidence and limits

The real MCP stdio subprocess to ephemeral REST Gateway test runs separately as
`mcp`, `ares`, and `grokbot` with actual fixture token validation. It tests each
identity's sender binding and denies foreign thread/status/result/cancel calls.
REST tests also deny cross-caller session admission, thread reuse, goal admission
and approval endpoints. An unauthenticated caller label and misleading token
filename do not impersonate another caller.

The truthful-write test exercises the actual AllowlistToolExecutor,
DirectToolExecutor, and registered `write_file` ToolDef with the admitted empty
grant, verifies denial and an absent temporary file, then forges model completion
claims in the isolated receipt and proves the API still returns text-only and
`execution_verified=false`. This is proof of truthful text-only semantics, not
successful file execution. No paid model or provider is called.

REA still has no enabled direct/delegated pass-through. All 50 known names fail
closed before admission; unknown/mutating tools and nested foreign resources are
rejected. The private-provider prerequisite and installed-source evidence remain
in REA_FEASIBILITY.md. Full Part 1 completion is not claimed. Grok round-trip,
webhook, installed ARES/Grok/Codex setup, production migration and real token
provisioning remain unperformed.

## Exact verification commands

Run from the worktree, with the following prefix for each test command:

```sh
export HOME=/tmp/jaeger-agent-bridge-checks/home
export JAEGER_VENV=/Users/matthewjenkins/.jaeger/venv
export JAEGER_STATE_DIR=/tmp/jaeger-agent-bridge-checks/state
export JAEGER_CALLER_TOKEN_DIR=/tmp/jaeger-agent-bridge-checks/tokens
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:packages/jaeger-agent:packages/jaeger-os /Users/matthewjenkins/.jaeger/venv/bin/python -m pytest dev/tests/jaeger_ai/core/test_agent_bridge.py dev/tests/jaeger_ai/core/test_gateway_caller_auth.py dev/tests/jaeger_ai/interfaces/test_mcp_bridge_authority.py dev/tests/jaeger_ai/core/test_gateway_durability.py dev/tests/jaeger_ai/core/test_gateway_write_exec_cards.py -q -o cache_dir=/tmp/jaeger-agent-bridge-checks/cache
./scripts/verify.sh
dev/scripts/run_tests.sh --smoke
dev/scripts/run_tests.sh --security
/Users/matthewjenkins/.jaeger/venv/bin/ruff check --no-cache jaeger_ai/features/agent_bridge dev/tests/jaeger_ai/core/test_agent_bridge.py
/Users/matthewjenkins/.jaeger/venv/bin/ruff format --check --no-cache jaeger_ai/features/agent_bridge dev/tests/jaeger_ai/core/test_agent_bridge.py
git diff --check
```

Logs use `/tmp/jaeger-agent-bridge-checks/approval-fixes-` plus `focused.log`,
`verify.log`, `smoke.log`, or `security.log`. The final delivery manifest records
actual completed counts, commit and complete patch hash. No logs or credentials
are included in Library attachments. No push, PR, merge, deployment, Keychain,
launchd, live config/database mutation or client registration is performed.
