# Gateway-owned session queue — 2026-09-24

## Scope

Implemented the Gateway queue and IDE controls without restarting the operator's live
Gateway/Ollama. The running daemon therefore does **not** expose the new routes until the
operator approves a controlled restart.

- Gateway queue contract: 9 tests passed, 0 failed.
- IDE queue contract: 6 Node tests passed, 0 failed.
- IDE Plan-mode contract: 4 Node tests passed, 0 failed.
- IDE context-chip contract: 3 Node tests passed, 0 failed.
- Full IDE Node suite: 123 passed, 1 intentional isolated-Gateway fixture skip, 0 failed.
- The IDE Plan-mode test file is included in that suite; the focused file itself passes 4/4.
- `git diff --check` passed.

## Limits

This is source and unit/owned-process evidence only. It does **not** claim live-provider
execution, an installed Antigravity host pass, physical-device qualification, or a live
Gateway restart. Live acceptance still needs a controlled Gateway restart, a real
configured-provider turn, queueing while a tool or stream is active, Stop/cancel, and an
immediate next-turn admission check.
Plan mode also still needs a live-provider turn to prove the model actually calls
`update_plan` and that the restricted tool set is visible in the model catalog and
execution receipt.
Context chips still need installed-host acceptance to confirm they refresh on editor
selection, tab, and diagnostics changes in the actual Antigravity/VS Code host.

---

# End-to-end repair acceptance — 2026-09-23

This section supersedes installation/pending statements in the historical notes below.
Existing uncommitted changes were preserved. Evidence and scratch files are outside
source: `~/.jaeger/verification/end-to-end-20260923/`.

| Requirement | Result | Evidence |
|---|---|---|
| Backend execution | VERIFIED for tested tasks | Real Antigravity coding request `50f0497c-9c82-4aad-8003-668e3193fb90`: read requirements 1–8, continued with 9–10 without repeated inspection, implemented calculator fix, ran four passing tests. Two checkpoints retained. Subsequent native write/read/Python assertion request `820821d9-70b9-4d95-962a-df8588cca271` succeeded with a recorded +1/−0 file change. |
| Streaming contract | VERIFIED | Explicit progress/checkpoint/tool events; final output only contains the final response. `live-evidence.json`, adapter and reducer regressions. |
| Frontend history | VERIFIED | Actual panel collapsed to Worked for 28s above one answer; expansion/reopening retained ordered work, including failures and checkpoints. Durable activity crossed a 500-event page boundary. Tests replay 125 tool rows and archive events after SSE retention eviction. |
| Connection/recovery | VERIFIED for tested paths | Foreign request `e2e-foreign-cancel-20260923` appeared live without manual refresh, survived session switching, and was stopped in the IDE. Full-window reload during `06296f6b-914d-42d6-a59d-fc845ef9efc3` restored Worked for 30s and one result; durable proof has one admission and one tool execution. An idle Gateway outage displayed Unavailable · reconnecting and automatically recovered. |
| Product integration | BLOCKED on Mac visible acceptance | IDE and WebUI used actual owner-react, persistent Jaeger identity, memory and tools with `ollama:kimi-k2.7-code:cloud`. Memory written in one conversation was recalled in another and in WebUI. Native project file writes and terminal assertions succeeded. Installed `/Applications/JaegerAI.app` rebuilt, signed, replaced with backup retained, and launched; menu-only app cannot be inspected because CUA times out. Operator asked to open its menu. |

## Latest validation

- `final-tests.log`: 112 targeted Python tests passed, including owned-Gateway IDE integration.
- `ide-tests.log`: 80 passed, one optional standalone integration test skipped.
- `owned-node.log`: 38 client cases passed against an isolated real Gateway.
- `lint-delta.json`: no newly introduced Ruff findings compared with preserved
  pre-task source; baseline lint debt remains. `git diff --check` passes.
- `disk-assertions-final.json`: zero in-repository runtime/cache directories.
  Twenty-four pre-existing bytecode directories, all older than this task, were
  moved to the external evidence backup. Verification did not recreate them.
- `acceptance-receipts.json`, `reload-proof.json`, `live-evidence.json`: durable
  request/tool metadata. Native write contents independently checked on disk.
- WebUI retrieved `copper-orbit-742` from memory, read the real calculator and
  native-proof files, and rendered saved tool completion after browser reload.
- Launchd PATH now includes Jaeger's Python and installed worker locations.
  Codex, Claude and Gemini CLI version probes succeed through the Gateway.
  Worker authentication and delegated task execution are not established by those probes.
- Latest functional VSIX installed through Antigravity's CLI and activated in
  the external acceptance workspace. The main active coding window was preserved.

## Limits and blocker

Full product acceptance is **not complete**. Open the Jaeger menu-bar menu so its
connection state and controls can be inspected. The installed process runs, but
that alone does not establish a working Mac interface. No pixel-identical Codex
or identical model behavior claim is made. Previously pruned activity predating
the new durable archive cannot be recovered; future activity is paginated rather
than silently truncated. The local bounded cache is only a fallback. Cancellation
is cooperative; the observed sleeping shell command finished before cancellation
settled. Arbitrary shell edits are not covered by native file-tool Undo.

---

# IDE client verification — 2026-09-23

## Earlier live Antigravity acceptance

The notes below this section describe earlier checkpoints, not the current
installation status. The extension has now been installed and exercised in the
actual Antigravity Jaeger panel against the local Gateway and live model.

- Read → patch → read: observed white progress paragraphs alternating with
  grey `Read files` / `Edited files` disclosures while the elapsed timer ran.
- Completed turn: automatically collapsed to `Worked for 6s`; opening it showed
  the same ordered progress and tool history above the final answer.
- A disposable sandbox file produced an actual `+2 −1` change card. Selecting
  its row opened an inline diff with old/new line numbers and red/green lines.
- `Open diff` opened the immutable before/after snapshots in Antigravity's diff
  editor. Undo required confirmation, restored the test file, and became
  disabled; the restored contents were also checked on disk.
- Copy acknowledged the clipboard action. Edit and resend populated the exact
  original message. A separate read-only turn was stopped through the panel and
  displayed `Stopped after 6s`.
- Automated: 77 IDE tests passed, one optional test skipped; 41 targeted
  Gateway/file-change tests passed, including postimage conflict rejection,
  request/session isolation, persistence, and protection of pre-existing edits.

Limits: no claim of pixel-identical Codex rendering or identical model behavior.
Inline diffs color changed lines; full language highlighting is in the IDE diff
editor. Turn Undo covers the native text file tools documented in README, not
arbitrary shell/MCP changes. Attachment/model controls and the separate native
app Offline indicator are not newly verified by this live test.

## Earlier verification notes

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
