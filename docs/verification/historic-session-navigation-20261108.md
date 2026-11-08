# Historic conversation navigation verification

Date: 2026-11-08. Isolated development checkout only. No deployment, runtime-machine changes, or live operator data.

## Defect and repair

Production entrypoint is `src/main.tsx` → `StableDemo` → embedded `AppWindow` → `AgentsRoster`. The inspector's recent-conversation rows displayed each historic session but navigated using only the agent ID. StableDemo correctly interprets that route as an agent-home request, so selecting old work opened the home conversation instead.

- Recent-conversation rows now carry both encoded agent and exact session IDs.
- The generic **Open chat** action remains agent-home navigation.
- StableDemo waits until route and selected-session state agree before requesting a snapshot. This avoids revalidating the previous conversation against a newer deep link.
- Inspector session-read failures now show an alert and explicit retry instead of “No conversations yet.”
- Model-read failures now show “Unavailable” and retry instead of claiming “Gateway default.” Unsupported model APIs show “Not reported.”
- Existing missing-session and offline behavior preserves the requested link without silently creating or substituting another conversation.

## Verification

Passed, final scoped run:

```sh
cd jaeger_ai/interfaces/ui
JAEGER_UI_TEST_OUTPUT=/tmp/jaeger-historic-final npm test -- \
  src/unified/AgentsRoster.test.tsx \
  src/demo/StableDemo.test.tsx \
  src/demo/StableDemo.historicSessions.test.tsx \
  src/demo/StableDemo.navigation.test.tsx
npm run typecheck
```

38 tests across 4 files passed; TypeScript check passed. `git diff --check` passed.

New tests cover exact encoded historic-session selection, distinct rows, unchanged generic home action, read failure versus empty success, explicit retry, agent-switch late-response isolation, actual production roster-to-shell routing, reload, Back/Forward, missing/offline links, no fallback creation/home navigation, and older snapshot response suppression. The production-shell integration uses the real AppWindow and AgentsRoster, a synthetic source, and a ChatPane mount probe. Existing shell/navigation regressions retain coverage of chat mount preservation across workspace navigation.

Logs and JSON reports are outside the repository under `/tmp/jaeger-historic-final*`.

## Limits

No browser visual acceptance or live Gateway acceptance claimed. Chromium is blocked by this environment's socket restriction, as established in the parent verification task. These are component/integration tests with synthetic data. Full repository aggregate verification and final integration are owned by the parent task. No commit, push, merge, or deployment performed.
