# Dispatcher continuity verification — September 9, 2026

Implemented the scoped Jaeger-profile WebUI ↔ Mac conversation handoff. No ARES
runtime dependency was added. No donor repository changes, conversation merges,
profile credential changes, permission grants, or data deletions were performed.
The 14 pre-existing staged reference-image deletions remain untouched.

## Changes

| Area | Result |
|---|---|
| Durable history | Stable message IDs from the existing native sessions database; both clients read Dispatcher history |
| Admission | WebUI binding normalizes to the same native `dispatcher` session; persistent request identities prevent duplicate desktop retries |
| Controls | Shared run receipt, pending approvals, tools, cancellation confirmation and restart reconciliation |
| WebUI | Owned patch after existing auth/CSRF; canonical transcript projection only for Jaeger Dispatcher; automatic refresh and visible run outcomes |
| Mac | Dispatcher default, explicit New Chat/return controls, shared history/status/approvals, automatic reconnect, optional `--chat` launch |
| Packaging | Owned WebUI overlay/image rebuilt; installed signed Mac app; existing data and upstream checkout preserved |

## Test results

- Full `.venv/bin/pytest`: **3,848 passed, 1 skipped**, one existing `audioop`
  deprecation warning; 114.31 seconds.
- Final continuity/projection/surface-contract checks: **10 passed**.
- Ordinary Swift suite: **56 passed**, two opt-in live tests skipped by default.
  Each opt-in live handoff and restart test was also run explicitly and passed.
- Owned JavaScript routing test passed; deployed script SHA-256 matched source.
- `git diff --check` passed; the Hermes WebUI donor worktree remained clean.

## Execution evidence

- Real Chromium composer sent `HANDOFF-597d7545b4`; the native model replied with it.
- Production `ChatViewModel` loaded that browser exchange with stable view IDs,
  sent a continuation through `DispatcherClient`, and received
  `HANDOFF-597d7545b4 MAC-CONFIRMED`.
- The still-open browser rendered the Mac reply without switching sessions.
- Browser offline/reload recovery retained history; a subsequent browser turn
  returned the same identifier with `WEB-CONFIRMED`.
- An actual native `execute_code` permission request was visible through the
  WebUI conversation proxy. It was denied there; no permanent permission was granted.
- A second actual permission-bound run was stopped via the native client route;
  the WebUI observed `cancelled` with `cancellation_confirmed: true`.
- The opt-in Swift restart test restarted the idle bridge and adapter, reattached
  the desktop client, and verified identical transcript text and view IDs.
- Real two-turn checks passed for Hermes/default, Jaeger Focus, OpenClaw and
  Roundtable, including member output checks and saved history.
- All 837 Python sources under `jaeger_ai/` and workspace `packages/` compiled.

Logs are in `/tmp/jaeger-continuity-*.log`. The final repeatable handoff
record is `/tmp/jaeger-continuity-live-final.log`; earlier selector probes are
kept separately for audit. The final test used the real assistant transcript DOM
and verified there were no page JavaScript errors.

## Limits and operator state

Mac interaction was verified through its production Swift view model and network
client, plus installation/launch of the real app. macOS accessibility automation
returned no usable window tree, so this report does **not** claim an automated
click-through of the native window. Browser interactions were real headless
Chromium DOM/composer operations, with no screenshots. The built-in browser
connector was unavailable.

`doctor` still reports that the large memory SQLite database exceeds its routine
two-second integrity-scan budget. That is an unverified full scan, not a newly
confirmed corruption. The database was preserved. All supervised services and
both existing containers were running at handoff; Honcho remains intentionally
paused as before.

The live WebUI container keeps its existing creation-image label and has the
owned overlay installed in `/apptoo`. The rebuilt managed image contains the
same overlay for future recreation. Current profile and session volumes were
not recreated.

Rollback copies: `/tmp/JaegerAI-before-continuity.app` and
`/tmp/jaeger-webui-before-continuity.tar.gz`. These are temporary local copies;
normal repository/versioned backups remain the long-term recovery mechanism.
See [daily use](../../../docs/DISPATCHER_CONTINUITY.md) for launch and verification commands.
