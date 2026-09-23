# Jaeger UI exploratory repair prompt

Use this prompt with an agent that has macOS desktop and browser-control
capabilities. The agent must operate the real interfaces, diagnose defects, edit
the source, and repeat the interaction. Terminal-only inspection is insufficient.

## Assignment

Work in `/Users/matthewjenkins/GitHub/JaegerAI`.

Make the Jaeger WebUI and native macOS app genuinely usable. Explore them as a
human would, find defects without waiting for the operator to describe each one,
repair their root causes, and repeat the failing journey until it passes.

This is implementation and black-box product testing, not a code-review report.
Do not stop after compilation, API tests, screenshots, or one successful message.
Do not return a new plan in place of operating the applications.

## Read first

1. Root and applicable nested `AGENTS.md` files.
2. `docs/architecture/GROK_PERSONAL_RELEASE_PROMPT.md`.
3. Latest entries in `docs/architecture/CONVERGENCE.md`.
4. `/tmp/jaeger-convergence.nJEGqw/CHECKPOINT.md`, if available.
5. `docs/OPERATIONS.md` only as needed for startup behavior.

Inspect the current diff before editing. Preserve all existing staged, unstaged,
and untracked work, especially `VoiceStage.swift` and the staged 0.9.3 roadmap.
Do not reset, clean, stash, commit, push, or overwrite the installed app.

Round 9 already fixed background request conflicts, webhook board deduplication,
producer shutdown/lease handoff, and cron requeue after failed admission. The Mac
source now defaults its bridge to `JAEGER_BRIDGE_EXECUTION=gateway`. Do not repeat
those tasks unless direct testing reproduces a regression.

## Required environment

Use an isolated fresh state root, temporary workspace, owned Gateway, owned WebUI,
owned bridge, and non-operator ports/sockets. Do not connect tests to the user's
live databases or restart their services. Do not inspect private operator content.

Build Swift artifacts under a unique external scratch directory. Build a test
`.app` outside the checkout and `/Applications`; do not replace or launch the
installed `/Applications/JaegerAI.app` as part of this work.

Start with a deterministic scripted model provider so rendering and protocol
failures are reproducible. Make responses include short text, long Markdown,
lists, links, Unicode, a large code block, delayed streaming chunks, reasoning
events if supported, a tool request, an approval, an error, and cancellation.
Label this evidence as scripted. Do not spend money or use private provider
credentials. A live-model smoke test requires existing authorization; if it is
not available, record that narrow limitation and continue UI work.

If you lack browser or desktop-control tools, state that immediately and do not
claim visual acceptance. Use browser automation for WebUI and XCTest/Accessibility
automation for Swift where possible, but a source test that only inspects an
environment dictionary is not UI testing.

## Observe before fixing

Launch the owned stack with stdout/stderr and crash logs captured externally.
Open the WebUI in a controllable browser and the externally built Mac app through
desktop control. Verify visually which instance/session each uses.

While interacting, capture:

- Screenshots before, during, and after failures.
- Browser console errors, failed requests, response status, and SSE lifecycle.
- Gateway, WebUI, bridge, and app process output with timestamps.
- macOS crash/termination evidence for the test app.
- Durable session/event state through public APIs or the owning store interface;
  never open the operator database directly.
- Whether one user action produced one request, one visible message, and one
  terminal result.

Use evidence to locate the producer. A visual symptom may originate in CSS/layout,
Swift view state, event reduction, request identity, session selection, or backend
streaming. Fix the actual owner rather than masking it in both clients.

## Mandatory WebUI exploration

Use pointer and keyboard input through the rendered page. Complete all of these:

1. Open a new session and send at least five sequential messages in that SAME
   session. The second, third, and later messages must not corrupt, reset, duplicate,
   freeze, switch sessions, or crash the page/server.
2. Stream a long response that exceeds the viewport. Confirm all text renders,
   wrapping is readable, the page remains scrollable, and the final content is not
   clipped behind headers, footers, composers, sidebars, or overlays.
3. Scroll up while streaming and confirm the UI does not continually yank the
   reader to the bottom. Return to the bottom and confirm new content is reachable.
4. Render paragraphs, headings, lists, links, Unicode, inline code, and a multiline
   code block. Confirm no raw protocol frames or unintended reasoning text appears.
5. Resize from a wide window to a narrow window. Check composer visibility,
   message width, navigation, overflow, controls, and focus.
6. Cancel a slow response. Confirm streaming stops, the busy state clears, one
   cancellation result appears, and the next message succeeds.
7. Trigger an approval. Test allow-once and deny through the visible UI. Confirm
   no duplicate prompt and that a cancelled request closes its approval.
8. Create another session, switch repeatedly, and verify messages never bleed
   across sessions. Reopen the original session and continue it successfully.
9. Refresh during and after a turn, reconnect, and verify durable history and one
   terminal outcome. The UI must recover from an interrupted SSE connection.
10. Attach a temporary file through the actual file control. Confirm its name,
    state, removal behavior, request association, and error display.
11. Exercise tool output and a deliberate backend error. The UI must show a useful
    status, clear its loading state, and allow the next turn.
12. Inspect existing settings and feature panels for obvious broken controls,
    unreadable layouts, fake success, dead navigation, and production sample data.

## Mandatory macOS app exploration

Operate the externally built app, not only its Swift tests:

1. Launch it against the same owned Gateway. Confirm its bridge starts in Gateway
   mode and no second local agent/runtime or producer lease is created.
2. Send at least five sequential messages in one session, including the delayed
   long response. Check partial streaming, final reconciliation, scroll position,
   full text rendering, composer focus, window resize, and absence of duplication.
3. Cancel an active response and send another message immediately afterward.
4. Complete approval allow/deny flows and verify cancelled approvals close.
5. Create, switch, and reopen sessions. Quit/relaunch the test app and recover
   history from the same owner.
6. Disconnect and restart the OWNED Gateway. Confirm a truthful connection state,
   no local fallback, and successful reconnect when the Gateway returns.
7. Exercise a temporary attachment and harmless tool operation if those controls
   are exposed in the shipping view. Record missing UI as unfinished rather than
   silently counting a backend test as client acceptance.
8. Exercise voice controls where the host supports them. If microphone/audio/model
   permission is unavailable, distinguish that external limitation from view,
   transport, or state-management failures. Text operation remains mandatory.
9. Inspect menus, settings, activity/status, keyboard navigation, window sizing,
   empty/error/loading states, and obvious accessibility labels/focus problems.
10. Keep the app open while a background result arrives. Confirm visible activity
    or notification behavior accurately reflects what the current product supports.

## Cross-client checks

Both clients must use one Gateway and one selected instance:

- Send from WebUI, observe durable history in Mac; reply from Mac, observe WebUI.
- Stream concurrently in separate sessions without event crossover.
- Cancel one session without interrupting the other.
- Resolve an approval in its originating client without leaking it elsewhere.
- Restart/reconnect both clients and verify consistent session ordering/content.
- Confirm no duplicate local agent, producer, or conflicting execution lock.

## Repair loop

For every defect:

1. Save minimal reproduction steps and visual/log evidence.
2. Identify whether the producer is backend contract, WebUI reducer/rendering,
   Swift state/view code, or launch/configuration.
3. Add the smallest useful regression test at the owning boundary. For visual
   behavior, add browser/XCTest interaction where practical; do not replace the
   visual rerun with a string assertion.
4. Fix the source without deleting intended features or changing UI frameworks.
5. Repeat the exact failed interaction through the real UI.
6. Run focused regressions for the touched owner.
7. Continue exploring; do not stop after the first repair.

Prefer direct fixes over new abstraction layers. Preserve public routes and wire
formats unless a compatible correction is required. Do not weaken cancellation,
permission, request identity, state-isolation, or duplicate-action behavior to
make a screen pass.

## Acceptance evidence

The UI milestone is complete only when:

- WebUI and the external Mac app both pass the multi-turn, long-render, cancel,
  history, reconnect, and cross-client journeys through one owned Gateway.
- The second and later messages in one session work repeatedly.
- Long content is fully visible and usable at tested window sizes.
- There are no unexplained console exceptions, process crashes, duplicate
  requests/messages, stale busy states, or session crossovers.
- The test processes exit successfully with no operator-state or in-repo writes.
- The externally built `.app` path and exact owned-stack launch commands are
  recorded. Do not install it automatically.

Record each scenario as `pass`, `fail`, `blocked_external`, or `not_run`. Include
the source revision/worktree fingerprint, commands, process exit codes, screenshots,
logs, tested viewport/window sizes, and whether the provider was scripted or live.
Do not call the app finished when only backend or offline Swift tests pass.

## Continue after UI stabilization

Once both clients pass, continue the personal-release prompt: prove one contextual
proactive-assistance journey, then replace production sample data in Skills,
Tasks, Kanban, and Workspace with authoritative services. UI stabilization is the
first usable milestone, not the end of Jaeger's product work.

Before usage expires, update `docs/architecture/CONVERGENCE.md` and an external
checkpoint. State what was visually exercised, defects fixed, exact remaining
failures, artifact paths, and the next executable task. Continue until a real
blocker or usage limit; do not ask the operator to manually discover issues that
the available UI-control tools can reveal.
