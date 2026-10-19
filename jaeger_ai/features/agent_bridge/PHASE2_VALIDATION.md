# Phase 2 validation record

Worktree: `agent-bridge-2`, branch `feat/agent-bridge-2`, base
`1ab5e31221fdf93e0447f2e872d227be752ff0c3`.
The Phase 1 branch `feat/agent-bridge` is preserved separately. Phase 2 explicitly
authorizes webhook implementation, isolated testing, commit and patch export;
production activation and secret access remain excluded.

Combined bridge command: installed venv Python `-m pytest -q` over
`test_agent_bridge.py`, `test_agent_bridge_outbox.py`,
`test_agent_bridge_outbox_integration.py`, `test_agent_bridge_rea_phase2.py`,
and `test_agent_bridge_tool_goals.py`: **116 passed**, 78 aiohttp warnings,
8.41 seconds. Log: `/tmp/jaeger-agent-bridge-2-checks/final-focused.log`.

Tests use temporary HOME/config/database/caller fixtures, a task-owned ephemeral
loopback receiver and scripted model responses. The approval test runs the actual
JaegerAgent loop and real native file tool: no file before approval, correct bytes
after fixture-owner approval, denied/cancelled writes absent. Late kill switch,
symlink and directory destinations fail closed. A separate canonical task-owner
receipt test validates verification provenance.

Outbox fake acceptance covers transaction rollback, migration preservation,
duplicate IDs, restart/retry/lease recovery, redirects, rate/kill behavior and
mock-only Keychain credentials. It proves no external endpoint or Grok round-trip.
No paid providers or models are needed. Real REA remains unsupported.

Final results: `./scripts/verify.sh` all passed; `dev/scripts/run_tests.sh --smoke`: 170 passed, 6470 deselected; `--security`: 188 passed, 12 warnings. Ruff check and format check passed for nine bridge/test modules; `git diff --check` passed.

Affected canonical contracts: 112 passed, 51 warnings in 2.84 seconds across
`packages/jaeger-agent/tests/contract/test_tool_executor_contract.py`,
`packages/jaeger-agent/tests/test_default_workspace.py`,
`dev/tests/jaeger_ai/core/test_workspace_dir.py`, `test_gateway_caller_auth.py`
and `test_agent_workspaces.py`. Log: `final-contracts.log`.

Final pipeline logs use `/tmp/jaeger-agent-bridge-2-checks/final-` prefixes.
No changes were deployed. The current Phase 2 authorization supersedes the old
Phase 1 outbox exclusion. No credentials, launchd, network settings, live session
data or MCP registration were changed. All Keychain calls in tests are mocked;
the production credential adapter was not run against the live Keychain.


## Canonical team follow-up

The original `f66270c4` patch/manifest are preserved unchanged. The follow-up
uses canonical call_agent/run_team, durable originating actor/root binding,
standing specialist catalog intersection, per-tool owner approvals, bounded
workspace/result access, cancellation, host-derived ancestry and frozen retry
grants. [FOLLOWUP_INTEGRATION.md](FOLLOWUP_INTEGRATION.md) distinguishes this
implemented path from the unfinished full normal catalog and direct REA.

Validation (all isolated temporary state/fixture credentials):

- Combined bridge, outbox, REA-denial, team, existing handoff, specialist and
  project regressions: **147 passed**, 96 warnings, 12.78 seconds.
- Final team/handoff regression after origin handling refinement: **19 passed**,
  18 warnings, 3.71 seconds. Includes seven new team/retry tests.
- Smoke: **170 passed**, 6477 deselected, 15.84 seconds.
- Security tier: **188 passed**, 12 warnings, 10.47 seconds.
- `./scripts/verify.sh`: **all passed**.
- Ruff check and format: **six changed bridge/test modules passed**;
  `git diff --check` passed.

Logs: `/tmp/jaeger-agent-bridge-2-checks/followup-{focused,team-final,smoke,security,verify}.log`.
The tests use actual local HTTP handoff/child admission, NativeSpecialistRuntime,
a scripted-model JaegerAgent test harness, standing-tool intersection and native
file tools. They prove real file effects after owner approvals, not paid provider
or full production EntityRuntime/model acceptance.

The separate private REA sandbox qualification **failed before MCP initialization**
with subprocess return code -6/SIGABRT and empty stderr. A same-profile
`/usr/bin/true` diagnostic failed identically. It did not establish private REA
acceptance. No unconstrained provider was launched as a fallback. No live keys,
registration/configuration, shared provider or network settings were used.
