# Backend-first acceptance and measured baseline

Updated 2026-09-11. Source: `finish-alpha`, HEAD `e50d0aa`, plus local uncommitted changes.

## Background delivery repair

Evidence: `~/.jaeger/audits/background-delivery-20260911/`. Backend only; no UI
changes or character replacement. Native bridge contract 16 adds
`background_messages` and `acknowledge_background` to the existing socket
protocol. The gateway stays on :8810; no new HTTP endpoint was introduced.

Cron, heartbeat, and idle completion/board results now save a native
`dispatcher` assistant message and a pending delivery in one SQLite transaction.
The gateway polls that native outbox, committing its transcript message,
`message.created` SSE event, and deduplication receipt together (gateway schema 4).
Only then does it acknowledge the native result. Lost acknowledgement retries
delivery, never model execution. Receipt identity survives gateway restart and
event retention. Two clients can read the same event using the existing
`/v1/sessions/dispatcher/stream` endpoint and fetch the saved transcript with
`/v1/sessions/dispatcher`. Other native instances use a namespaced gateway
destination; the deployed poller currently attaches to the `jaeger` instance.

Heartbeat generation now uses the character-aware turn path. Silent successful
heartbeats produce no message; halted, failed, cancelled, and uncertain results
retain their status. Dispatcher context includes recent initiated messages so
the lead can discuss them without replaying the job. Background ticks respect
the foreground workspace lock. Cron no longer retries a callback merely because
it raised TypeError, and scheduled speech respects `voice.enabled`.

Verification: **209 tests passed in 9.13 s**, including real SQLite rollback,
restart, lost acknowledgement, two subscribers, deletion/clear, failure status,
character-path dispatch, and no repeated callback after TypeError. The initial
run caught a new test using `messages()` instead of the actual `history()` API;
that test was corrected. Ruff fatal checks and `git diff --check` passed.

Live one-shot schedule `backend-delivery-2a06c880` generated
`BACKGROUND_OK_2a06c880`, persisted it once in the native dispatcher and once in
the gateway, and delivered the same event to two independent HTTP SSE clients.
Native generation took **2.13 s**; scheduler wait plus execution and delivery
took **30.12 s**. The native outbox was acknowledged. The one-shot schedule had
already been consumed when cleanup requested cancellation (`schedule not found`).
See `live-scheduled.json` and `tests-release.log`.

After restarting both native bridge and gateway, SSE replay returned the same
event ID **48**, with one saved background message and its native acknowledgement
intact (`live-restart.json`). A fresh ordinary gateway/MCP turn asked which code
Jaeger had sent, without supplying the code, and returned the exact value in
**5.00 s** (`live-followup.json`). Identity and configuration hashes were unchanged.

Limits: this verifies backend delivery, not rendering in either UI. Clients must
consume `message.created` on the dispatcher stream. Crash recovery is guaranteed
for results already committed to the outbox; it does not prove exactly-once
execution of a job interrupted before that commit. The existing volatile
delegation-completion queue, automatic specialist-parent join/resume, and the
full Chronicler research benchmark remain separate unfinished work. No new
memory/proactivity permission defaults or onboarding controls were added here.

## Backend repair follow-up

Evidence: `~/.jaeger/audits/backend-fixes-20260911/`. Changes remain uncommitted
on `finish-alpha` at `e50d0aa`; these measurements concern the working tree.

- Search failures were reproduced from native `tool_calls` records. The rack
  SearXNG endpoint timed out, and narrow queries exhausted the remaining
  backends. Search now distinguishes responding services with no matches from
  transport failures, preserves backend diagnostics, and applies a 60-second
  cooldown to failed configured SearXNG endpoints. DDGS calls specify a timeout.
  This is not a guarantee of primary-source coverage or an overall wall-clock
  deadline for the complete fallback chain.
- Error-only tool envelopes now count as failures in native audit callbacks,
  caching and claimed tool successes, including before result truncation.
  Repeated tool failures receive a tool-free partial summary. The halt remains
  a failed native receipt; fluent summary text does not turn it green.
- Native `call_agent` submits a durable handoff and yields the parent turn.
  `get_agent_result` reads its result on a later turn without redispatch. The
  child uses a fresh specialist session and a deterministic native receipt ID.
  Empty tool grants mean no tools. Grants travel through gateway, MCP and the
  bridge, and are enforced at the agent executor as well as its catalog.
  The child prompt omits the ordinary frozen personal-facts snapshot.
- Handoff timeouts and interrupted waits report execution_unknown. Reading
  that handoff can reconcile a later native receipt without executing again.
  Terminal handoff results cannot be overwritten by late failure updates.
- Native specialist execution no longer advertises local-only inference:
  the deployed model is `glm-5.3-flash:cloud` through the locked Ollama endpoint.

Verification: **233 tests passed in 10.72 seconds**, then **89 integration
checks passed in 19.04 seconds**. Suites overlap; do not sum them. The first
focused run caught an incorrect callback name in a new test; the first broad
run caught an existing session-contract assertion (version 3 versus producer
version 4). Both were corrected before the passing runs. One earlier test run
also overlapped an audit-file write, tripping the live-state isolation guard;
the clean rerun separated verification from live operations. Ruff fatal/error
checks and `git diff --check` pass. The dispatcher probe's missing `sys` import
was found and repaired by the lint check.

Live evidence: `live-specialist-parent.json` shows one admitted native handoff
and the exact parent acknowledgement in **9.429 s**. The isolated child returned
`SPECIALIST_CHILD_F39C` in **1.24 s native execution time**; both gateway and
native receipts confirm completion (`live-specialist-child.json`,
`live-specialist-native-receipt.json`). A later lead turn called
`get_agent_result` and returned that exact stored answer in **4.041 s**
(`live-specialist-read.json`). This proves a bounded asynchronous handoff,
not automatic parent resumption or general specialist reasoning quality.

The original failed Procopius query returned DDGS results in a new direct
probe. A subsequent query skipped the unavailable SearXNG endpoint during its
cooldown and completed through Wikipedia. See `search-after.json`; a Wikipedia
fallback is not a primary-source research pass.

Honcho was restored at both documented addresses. Docker Desktop launched
inside the Windows SSH job disappeared after the connection closed. Starting
the existing Docker executable through CIM detached it from that job; the
existing containers then stayed up. The fabric supervisor now has that
bounded recovery path. No host reboot, firewall change, new scheduled task or
container recreation was needed. Evidence: `honcho-detached-start.json` and
`honcho-after-detach.json` (both health endpoints return HTTP 200).

The live Honcho 3.0.10 OpenAPI contract also exposed client defects: peer and
session reads used nonexistent GET routes (HTTP 405); message creation returns
a 201 array, not an object; message listing is paginated. All three are fixed.
Filtered list reads remain read-only. Pagination errors remain unconfirmed
rather than turning partial results into proof of absence. The initial live
write reached Honcho but failed response decoding; read-back found its one
stored copy. That failure remains in `live-honcho-write.json`.

After the fix, **a fresh gateway/native write verified both local and Honcho
storage in 6.744 seconds** (`live-honcho-write-final.json`). A separate native
specialist session, restricted to `recall_insight`, retrieved the exact claim
from Honcho in **2.525 seconds**, with only topic/ID in its prompt. Independent
remote read-back found exactly one message (`live-honcho-recall.json`). This is
immediate persistence and retrieval, not a two-hour recall or heartbeat pass.

The full Chronicler rerun did not pass. It produced no research tool calls:
the model returned empty outputs, and the outer controller reset the turn
instead of respecting that failure. After two empty steps (68.89 and 106.71
seconds), the audit requested cancellation; `chronicler/report.json` preserves
the incomplete/cancelled result. OpenAI-compatible reasoning-only length stops
now become `thinking_exhausted`; empty or failed turns cannot reset the outer
budget. Cancelled/failed ledgers detach from automatic continuation while
retaining the unfinished record by ID. The audit's own abandoned ledger was
paused, not marked complete (`reload-honcho/paused-ledger.json`).

Follow-up checks: **208 passed in 7.55 seconds**, **28 passed in 3.22 seconds**,
and **191 passed in 7.26 seconds** across overlapping repair suites. The first
208-test run exposed an old supervisor test expecting an obsolete state-root
layout; its replacement verifies the actual requirement that state stays
outside the checkout. Later live probes test the deployed changes. These
results do not establish research quality or a production-wide acceptance pass.

Remaining boundaries: automatic parent resume/join and confirmed specialist
cancellation; authoritative parent lineage;
entity-level memory permissions; delayed agent recall;
and independently reviewed research quality. Current tool grants restrict
which tool executes, not what arbitrary shell/code tools can do if granted.

Final live search through gateway → MCP → native returned results in **7.405
seconds** (`live-search-final.json`). Exact tool receipts for handoff, archive,
remote recall and search are in `native-tool-receipts.json`; trace and final
health are saved beside them. `assessment.json` summarizes measured outcomes.

## Earlier build: Chronicler integration

Evidence: `~/.jaeger/audits/chronicler-build-20260911/`. The scores and earlier
measurements below are the previous baseline, not a new rating of this build.

- Gateway schema 3 commits terminal result, assistant message and event in one
  transaction. Late failures cannot replace completed/cancelled/failed receipts.
  Reconciliation may still resolve an execution_unknown receipt.
- Durable SSE drains all replay pages, includes existing global events and
  signals retention gaps. Wakeups replace lossy subscriber queues. A foreign
  live process lease prevents both startup recovery and cleanup writes.
- Native TypeError no longer causes a second dispatch with fewer arguments.
  Any unconfirmed error after native dispatch is execution_unknown.
- Research tools record_insight/recall_insight use existing instance memory,
  exact topic/ID lookup, atomic immutable IDs, source URLs and attributed
  uncertainty. Optional public Honcho copies require message read-back; remote
  failure never becomes a local-cache pass. These are records, not automatic
  world-model belief promotion or an authenticated sharing policy.
- ARES calls the actual Honcho health method off its event loop. Its recent
  cache retains twenty observations across reload, and blank installations no
  longer invent an operator name or personal projects. It remains a bounded
  operational cache, not a complete world model or an archival memory service.
- The synchronous native call_agent → gateway → same bridge queue cycle is
  blocked before submission. Existing delegate_task remains the in-process
  execution path. Standing-specialist tool enforcement, cancellation and
  complete parent/child lifecycle integration remain open.
- The [Chronicler trial](benchmarks/chronicler-trial.md) records structural,
  transport and memory evidence separately. It never awards source accuracy,
  audio generation, heartbeat execution or delayed agent recall from prose.

Verification before reload: **193 tests passed in 22.89 s** (`tests-final.log`).
After reload: **3/3 native exact-reply turns passed**, median **4.70 s**, range
**4.44–5.15 s** (`live-ready-smoke.json`). All three gateway receipts map to
native **dispatcher**, with three terminal events (`live-receipts.json`).
The first probe during MCP restart returned 503 (`live-smoke.log`); it is not
counted as a successful turn. SQLite backups precede reload in `reload/`.

The research trial's current result is recorded in `trial/report.json`; the
runner stores pending delayed checks rather than claiming two hours elapsed.
No industry comparison or output-quality improvement is established by these
transport and persistence checks.

### Observed Chronicler result: failed

The live research turn ran for **465.98 s**, made **20 web_search calls and two
web_extract calls**, and halted with `repeated_tool_failure`. It returned no
briefing and archived neither research question. Honcho's configured endpoint
failed its health probe. No two-hour memory test or audio test passed.

The gateway timed out at 300 s and recorded execution_unknown. The collector
later reconciled the **original** native receipt, without replaying the task.
That receipt exposed another defect: a structured halt with error=null had
been labelled completed. Native receipt classification, bridge field forwarding
and MCP failure handling now preserve that halt as a failure. Gateway error
handling uses a confirmed failed/cancelled native receipt when available;
otherwise it retains execution_unknown. Historical receipt bytes are preserved,
and the benchmark explicitly rejects the old false completion label.

Post-fix validation: **210 regression tests passed in 23.49 s**; the final
focused durability/collector run passed **15 tests in 2.61 s** (overlapping
coverage; do not add the counts). Fatal-error lint and diff checks passed.
Reloaded the fix while the native trace was idle, with another gateway/native
receipt backup in `reload-halt-fix/`.

A **separate control**, not the failed research trial, verified record_insight
on the native path: write and gateway reply in **9.27 s**, followed by
recall_insight in a fresh native session in **6.42 s**. The expected answer was
absent from the recall prompt. SQLite and trace checks found the stored record
and exactly one invocation of each tool. This verifies immediate local memory
integration, not Honcho or delayed recall. Evidence: `memory-control-write.json`,
`memory-control-recall.json`, `memory-control-trace.jsonl`, `assessment.json`.

Next: repair/measure research-provider failures and task budgeting; complete
standing-specialist execution and tool enforcement; restore and verify Honcho;
then rerun the full trial and its genuinely delayed recall phase.

## Scope and sequence

The current priority is **native agent → stable gateway → agent connections → UI**.
The Mac and browser are clients. Their availability, appearance and completion
must not determine whether the backend passes. The earlier product/UI acceptance
documents remain useful for the later interface stage; they are not the current
backend scorecard.

Jaeger's intended world model covers multiple people, groups, places, projects
and objects. A working chat transport does not establish that this larger model
is complete or that its answers outperform a baseline.

## Previous engineering judgment (before this build)

Scale: 0 = absent; 5 = partially working with major integration gaps; 10 = complete
for its stated scope with sustained failure/recovery and workload evidence.
These judgments are distinct from the measurements below.

| Area | Score | Basis |
| --- | --- | --- |
| Backend architecture | 7/10 | Existing runtime, knowledge, execution and bridge contracts support separate clients. Gateway health no longer requires the UI. Native execution still passes through a Hermes-named transport module; responsibility and protocol boundaries need further consolidation. |
| Native agent execution | 7/10 | Real MCP turns, a random-value memory retrieval, trace evidence and native dispatcher persistence now work. Broader autonomy, approval handling and relational output quality remain incompletely measured. |
| Gateway stability | 6/10 | Native failure affects readiness, explicit text fallback is separate, transcripts survive restart, and interrupted runs are marked unconfirmed. Durable request deduplication, event replay and reconciliation are incomplete. |
| Connections to other agents | 3/10 | Registry and adapters exist, but lead-facing specialist handoff remains an in-memory stub. Registration is not completed delegated work. |

Current stage score: **approximately 6/10**, using 40% native execution, 40%
gateway stability and 20% agent connections (5.8 before rounding). UI receives
zero weight. Architecture is reported separately, not added as bonus points.

## Measured live results

Machine: this Mac. Model reported by the native bridge:
`glm-5.3-flash:cloud`, provider Ollama, serving through the locked
`http://192.168.64.1:11434/v1` endpoint. The model is cloud-backed through Ollama;
these are not local-model inference benchmarks.

| Probe | Measured result | Evidence file |
| --- | --- | --- |
| Exact-reply native chat | 5/5 passed across two batches separated by a gateway restart; median 3.93 s, range 3.44–7.81 s end to end | `backend-benchmark.json`, `backend-post-restart-benchmark.json` |
| Missing synthetic memory key | Expected reply in 5.08 s; native trace shows one `recall` call | `backend-tool-benchmark.json`, `backend-trace.jsonl` |
| Seeded synthetic memory key | Returned the random stored value, absent from the prompt, in 5.25 s; native trace shows one `recall` call | `backend-memory-benchmark.json`, `backend-memory-fixture.json`, `backend-trace.jsonl` |
| Native dependency outage | Health changed 200 → 503 with the MCP proxy stopped, then returned to 200 after restoration | `backend-recovery-benchmark.json` |
| Gateway restart persistence | All six messages from the first probe batch were identical before and after restart | `backend-recovery-benchmark.json` |
| Native shared session | First five probe replies each occur once as assistant messages in `dispatcher` | `backend-native-session-proof.json` |
| UI independence | Controlled test: WebUI and optional HTTP adapter unavailable, native backend healthy → health stays 200 | `test_backend_health_does_not_require_ui_or_http_adapter` |

Evidence directory: `~/.jaeger/audits/e50d0aa-20260911/`.
Live probes used HTTP/MCP and database/trace inspection, with no UI interaction.
The UI-independence test used controlled dependency responses; the live WebUI
was not stopped. Read-only tool calls appear in trace/latency records; they are
intentionally excluded from the effect-checkpoint ledger. An initial check of
only that ledger was insufficient evidence of whether `recall` executed.

These are small smoke/recovery benchmarks. They establish observed behavior on
these tasks, not an availability SLA, concurrency capacity, performance under
load, general intelligence, or an output-quality advantage over another system.
Unit/contract test counts are regression evidence, not intelligence benchmarks.
The final affected-suite run passed **217 tests in 7.11 seconds**, with no
isolation warning: `backend-final-regression.log`. An earlier targeted run
overlapped the deliberate live restart probe and triggered the test guard's
live-state-change warning; the final run was performed after those mutations
finished. No new GitHub Actions result is claimed.

Reproduce the basic chat measurement from the repository:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPYCACHEPREFIX="$HOME/.cache/jaeger/pycache" \
"$HOME/.jaeger/venv/bin/python" scripts/benchmark-backend.py \
  --count 3 --output "$HOME/.jaeger/audits/backend-chat.json"
```

The script creates named benchmark sessions, records SSE completion/backend
labels, checks exactly one persisted matching reply, and stops after a failure
instead of retrying potentially accepted work. Custom memory probes additionally
require independent native trace inspection; exact text alone proves no tool use.

## Changes applied in this pass

- Started the existing Jaeger-owned MCP proxy on :8811; retained its existing
  backend targets and ports.
- Reloaded bridge, MCP HTTP and gateway services from this checkout. Corrected
  the instance's Ollama base URL to the locked endpoint and the gateway's
  launchd interpreter path to `~/.jaeger/venv/bin/python`.
- Backed up native knowledge, native sessions and gateway sessions before
  reloading. Backups and prior configuration are in `backend-reload/` under the
  evidence directory. No transcript migration or deletion was performed.
- Made UI/optional HTTP adapter status informational. Native MCP readiness now
  checks the live bridge through its existing read-only health tool; a tool
  catalog alone is insufficient. Model execution is still explicitly unverified
  by a health request.
- Native MCP errors/unknown execution raise tool errors instead of becoming
  successful reply strings.
- Gateway startup marks previously running sessions `execution_unknown` and
  rejects further sends to them pending reconciliation. This prevents silent
  replay; it does not implement reconciliation.

## Backend gates (updated after this build)

1. **Durable lifecycle:** request IDs, mappings, transactional completion and
   replay are implemented. Extend live failure tests to concurrent clients,
   cancellation, disconnect and process death with a counted side effect.
2. **Recovery and supervision:** receipt-based reconciliation and exclusive
   startup ownership are implemented. Prove supervision and prolonged
   failure/recovery behavior under realistic workloads.
3. **Backend approvals and permissions:** carry approval requests/decisions through
   the gateway to native execution, independently of the eventual UI. Denial
   must prevent the effect. Relationship knowledge must never grant permission.
4. **Real agent connections:** durable handoff records and a runtime adapter
   exist, but full scope/tool enforcement, cancellation and native lead-to-child
   execution remain incomplete. Benchmark the integrated path and its failures.
5. **World-model quality:** test multiple people/groups, identity ambiguity,
   corrections, time, permissions and commitments across turns. Compare answers
   and task results with world context enabled/disabled on the same model and
   fixed fixtures. Do not claim quality gains before that measurement.

The backend is now working on the measured native chat/memory path. It is not
yet accepted as fully stable or fully integrated. UI development can remain
deferred while these gates are completed.
