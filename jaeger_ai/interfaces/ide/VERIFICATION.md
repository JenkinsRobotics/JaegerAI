# IDE client verification — 2026-09-23

This is a first usable client slice, not completion of worker orchestration,
shared-knowledge policy, mobile deployment or full product acceptance.

## Automated evidence

- The selective Kilo adaptation adds deterministic coverage for 500 deltas in
  one frame, text/tool/text order, stable node/disclosure identity, manual scroll,
  and duplicate/stale event rejection. Its external proof first passed 5/5 under
  `/tmp/jaeger-extension-bakeoff.0VH7bI/proof-kilo`.

- `node --test jaeger_ai/interfaces/ide/tests/*.test.js`: 69 passed, zero failed;
  the owned-Gateway case intentionally skips without its fixture URL.
- `dev/scripts/run_tests.sh --integration dev/tests/jaeger_ai/core/test_ide_gateway_client.py`:
  owned Gateway integration passes (one Python test runs all nine JavaScript
  cases, including two turns, cancellation, next-turn recovery, reload and
  approval denial). No operator model or live database used.
- Coverage includes chunked UTF-8/SSE, wrong-request filtering, duplicate event
  IDs, no success on EOF, durable pending-request recovery without resubmission,
  definitive rejection versus uncertain admission and approval session ownership.
- Python source checked with repository Ruff rules; JavaScript syntax checked
  with Node. Package generated with pinned VSCE 3.6.2 outside the checkout.

## Actual graphical interaction

Used an isolated **VS Code Extension Development Host**, separate user data and
extension directories, against the real fixture Gateway at a random loopback
port. The provider was scripted; no claim of live model reasoning is made.

Observed through native Accessibility controls:

1. Jaeger view activates and shows Connected.
2. Create conversation named `IDE acceptance`.
3. Send `Say FIRST-IDE-ANSWER`; visible answer `FIRST-IDE-ANSWER`.
4. Same conversation: send `Say SECOND-IDE-ANSWER`; visible distinct second answer.
5. Start `CONTRACT-WAIT slow response`; incremental chunks and Stop appear.
6. Click Stop; status reaches `cancelled`.
7. Send `Say RECOVERED-IDE-ANSWER`; correct answer appears after cancellation.
8. Reload history; both earlier replies and recovered reply remain.
9. Move Conversation to a New Secondary Side Bar Entry; Jaeger appears beside
   the host's Chat tab on the right, with restored history.
10. Send `CONTRACT-WRITE`; real file approval appears. Click Deny; prompt closes,
    output reports permission refusal. Disk check confirms no test file exists.

The graphical run used the intermediate packaged UI; final follow-up changes
add duplicate-event/rejection guards, clear stale UI on endpoint/session changes,
and hide Stop for requests whose ID this client does not know. Those updates
have automated verification, not a second complete graphical replay.

External scratch: `/tmp/jaeger-ide-host.ZuYWnO`; build staging under
`/tmp/jaeger-ide-build/`. Temporary fixture Gateway and test window are not the
operator's services. No WebUI or Mac settings implementation was edited.

## Installation and remaining checks

Local VSIX installation succeeded using Antigravity IDE's own CLI. Its extension
list reports `jenkins-robotics.jaeger-ide@0.1.0`. This establishes local installation,
not actual Antigravity rendering or a live-provider turn. Do not restart an IDE
hosting active agents just to activate the extension; open it when convenient.

Remaining: actual Antigravity view interaction, configured live model, long-history
performance/windowing, richer Markdown, attachment upload, observing/cancelling
other clients' in-flight requests, task/worker presentation and worker connectors.
Cross-session shared knowledge stays governed by Jaeger's existing backend;
this client does not merge transcripts or claim new memory behavior.

The live donor comparison is separate evidence. With the same local Ollama task
set, Kilo passed prompts 1–2; Cline passed prompts 1–3 plus restart recovery, so
Cline was the operational winner on this machine today. Jaeger nevertheless uses
only Kilo v7.7.9's smaller MIT transcript mechanisms. Cline's React runtime and
Kilo's daemon/provider stack are not embedded. This adapted source has not yet
been installed or replayed in the current Antigravity window. Gateway tool-event
persistence and faithful activity reconstruction after reopen remain pending.
