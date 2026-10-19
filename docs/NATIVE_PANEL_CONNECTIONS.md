# Native Mac panel connections — second pass

Source work only; no installed-app, daemon, WebUI service or configuration changes.
The ready Stop-only candidate at `7422d707` remains isolated and unchanged.
This work continues `feat/native-truthful-panels` after `7f3260d3`.

## Frontend changes implemented

- Skills from the earlier `9feff9af` slice continue to use the authenticated Gateway runtime catalog. Production samples are gone; lifecycle is backend-reported.
- Tasks now displays actual scheduled jobs from the WebUI scheduler, not Gateway owner/orchestration tasks. Shows profile, schedule, enabled/paused state, backend last-run status, running-at-refresh status, hidden foreign-profile count and stored run-output history. An output file is explicitly not a success receipt.
- Kanban now lists backend boards, selects a board locally without changing the backend current-board pointer, and renders its actual columns/cards/statuses/assignees. Empty columns stay empty. Read-only backend status is visible.
- Both panels have Refresh, loading, empty, authentication/permission, changed-profile, disconnected, unsupported endpoint/schema and unavailable-backend states. Failed reads never turn into samples or success. Loading clears stale panel data.
- Both offer an embedded WebUI sign-in/management sheet using the same WebKit cookie store; this works even when embedded chat is not the default chat mode. Close and Refresh explicitly rereads authenticated context.
- Execution and edit controls are absent with an explicit explanation and access to existing WebUI management. No native action calls a mutation endpoint, moves a local card optimistically, simulates a run, or resends work.

## Connection layer changes implemented

- A typed native WebUI reader resolves the deployment through `jaeger webui url` with the selected instance. No copied port, token, model name, scheduler or database ownership.
- Reuses the app's existing WebKit login/profile cookies. Matches host/domain, path boundary, Secure and expiration; never prints or persists the values or reads Gateway credentials.
- Uses an ephemeral HTTP session without a shared cookie jar, rejects redirects and requires JSON. A sign-in HTML page is not decoded as an empty catalog. The session has a bounded request timeout.
- Reads authenticated `/api/native/context` before panel endpoints; subsequent reads carry a profile precondition. There is no automatic cross-profile aggregation or profile selection header.
- Existing chat address discovery now uses the selected instance and reports discovery failure instead of silently contacting a fixed localhost port. Profile-cookie seeding completes before first navigation. Connection errors remain visible even if an old page exists.

## Actual backend changes implemented

- One read-only `/api/native/context` response, inside the existing WebUI `check_auth` boundary, returns only the resolved profile and whether authentication is enabled. No session token, CSRF token or Gateway credential is returned.
- Optional `X-Jaeger-Expected-Profile` on scheduler/Kanban GETs is checked against the already resolved request profile. Mismatch returns 409; this header never selects a profile, grants a permission, or bypasses authentication.
- The earlier draft CSRF-token bridge and blanket preconditions on unrelated/mutating routes were removed from this read-only slice.

## Existing functionality reused, not rewritten

WebUI already owns authenticated browser sessions, profile resolution, runner-local schedule forwarding, cron list/status/history/output and mutation routes. Kanban bridge already owns board/card/dependency/dispatch APIs backed by `hermes_cli.kanban_db`. Gateway already owns durable chat sessions, request cancellation, approval and SSE replay. Native Skills already reads its runtime catalog. None of those engines was replaced by this change.

## Remaining work and concrete boundaries

This is a working **read-only native connection slice**, not completion of all requested panel controls.

- Native scheduler create/edit/delete/pause/resume and run controls still need a typed write adapter with the existing session-bound CSRF contract. They are not falsely described as absent backend capabilities.
- Safe native Run/worker dispatch also needs durable operation identity, reconciliation after an uncertain response and the applicable consequential-action approval flow. The inspected cron run response reports `running`/`already_running` plus job ID, not an admitted immutable run receipt. Kanban dispatch invokes `dispatch_once` and returns its result, without a common durable operation receipt. Adding a button plus automatic retry would not satisfy the no-duplicate/no-optimistic-success requirement. These are integration gaps; no run was executed to test them.
- Native Kanban card/board editing, dependency changes, logs and live event updates remain to be connected. No drag/drop or dispatch is simulated. Manual Refresh reads authoritative state.
- Stored cron output content/detail, history pagination and continuous status updates remain outside this read slice. Current history lists up to ten output records.
- Chat streaming/reconnect and recovered-conversation live attachment need a separate demonstrated-defect slice. This change fixes concrete endpoint/profile-navigation defects only. It does not claim a streaming rewrite or recovered-turn acceptance. Existing durable history, Gateway event replay and Stop recovery remain intact.
- Voice recognition, voice turn arbitration beyond the reviewed Stop changes, speech, avatar animation and embodiment are unchanged and unqualified by this build. IDE and WebUI styling work in other worktrees remains separate.

## Verification and rollout

Swift app target builds in external scratch `/tmp/jaeger-native-panels-second-pass`. Three focused native checks cover scheduler truth/unavailable/error distinction, board states and cookie confinement. Two isolated Python checks cover profile-precondition rejection/no-selection and credential-free context. No broad repository suite, model call, live task, live mutation or service restart is required or performed. Source-level/fixture checks do not establish installed or live authenticated endpoint acceptance.

The new context endpoint needs the approved WebUI deployment/reload before these native connections work against that service; an older server honestly reports unsupported. Native rebuild/install and any coordinated service restart remain pending explicit rollout approval. Preserve the separate Stop-only candidate and do not deploy this branch as a substitute for that reviewed candidate.
