# JaegerAI 0.12.0 — end-to-end production review

Date: 2026-09-04. Reviewed JaegerAI `c85f425` and JaegerAgent `ef78275`,
plus the local changes described below. Nothing was pushed or released.

Follow-up: [multimodal hardening and pipeline ranking](MULTIMODAL_HARDENING_20260904.md)
implements cancellation, mode continuity and shared settings improvements.
The architecture, live-acoustic, security and distribution gates remain open.

## Decision: do not publish this as production-ready yet

The app has a working shared model/memory composition and a real multimodal
engine. The first complete **application-bridge** benchmark scored **19/19**,
with **2.90% WER**, no case errors, and a clean bridge process exit. However,
the previous claim that every interface already uses one end-to-end agent
pipeline is not supported by the implementation. This review fixed the main
steady-state delay: the final agentic run retained 19/19 accuracy while median
spoken first audio fell to **1.891 s** (7/12 spoken cases selected audio).
Startup and cold/vision tails remain far above the reference. Passing
model-free suites alone did not catch these gaps.

Final single-run results on the reviewed code:

| Result | Chatbot | Agentic |
|---|---:|---:|
| Correct | 19/19 | 19/19 |
| Spoken WER | 2.90% | 2.90% |
| Median spoken first audio | 1.564 s | 1.891 s |
| Spoken cases producing audio | 12/12 | 7/12 (dynamic selection) |
| Full startup | 26.178 s | 36.221 s |
| Runtime errors | 0 | 0 |
| Clean bridge exit | yes | yes |

The reference's median is 1.843 s with 12/12 spoken outputs. The agentic median
has a different denominator and a 17.417 s cold outlier; these results do not
establish blanket parity. **3,206 regression tests pass, 10 skip**, and device
preflight passes 9/9. The development app bundle is rebuilt and launchable,
but the blockers below must be closed before publication.

## Release blockers and remaining risks

| Priority | Finding | Evidence / required closure |
|---|---|---|
| Blocker | Different conversation paths across faces | `interfaces/bridge.py:_turn_worker` still routes native plain text to `run_turn`, while attached engine requests use `run_multimodal_turn`. `main.py:2889` selects the persona-first lane only when `content is None`; multimodal turns supply content. Unify the front door and final-output routing without changing tools/memory ownership. |
| Blocker | Legacy final speech still exists outside the engine | `interfaces/tui/voice_session.py:367`, `interfaces/tui/app.py:887`, and the bridge cron callback still have legacy speech paths. Native dictation is migrated in this review, but this does not complete native/TUI output unification. Explicit read-aloud and standalone speech tools may remain; automatic final speech must use the agent's output channel. |
| Blocker | Cold/vision latency is not reference-equivalent | The cache fix reduced final agentic median first audio to **1.891 s**, but the first spoken turn after vision still took **17.417 s**, image turns took about **17 s**, and startup took **36.221 s**. Dynamic agentic output selected audio in 7/12 spoken cases versus the reference's 12/12. Do not hide these tails or equate the denominators. |
| Blocker | Public dependency cannot resolve | `requirements.txt` references `jaeger-agent@1.2.0`; `git ls-remote` found neither that remote branch nor tag. Local editable sibling installs mask this. Publish an authorized coordinated release and pin tested immutable refs, then test a clean installation. |
| Blocker | Live duplex acceptance is unverified | The recorded suite deliberately bypasses endpoint detection and real devices. Run half-duplex, quasi/full AEC, double-talk, interruption, mute/camera toggles, reconnect and shutdown using the actual app and microphone/speaker hardware. |
| Release gate | Security result cannot be waived as a percentage | The prior agentic report records a memory-poisoning miss (14/15). The scenario runner explicitly labels security failures “DO NOT RELEASE.” This review did not execute allow-all host-breakout scenarios on the developer's machine. Re-run them in an enforced sandbox; demonstrate permission enforcement independently of model refusal. |
| Distribution | Developer signing is absent | The existing bundle reports `Signature=adhoc`, `TeamIdentifier=not set`. External distribution requires the release owner's Developer ID/notarization workflow. |
| Follow-up | Configuration is not yet one source of truth | Bridge boot constructs `SpeechRuntime()` with agent defaults, while legacy voice/STT settings remain in the app. Align settings and live state with the agent-owned pipeline; avoid controls that configure an unused backend. |
| Follow-up | Shutdown is still process-exit dependent | Bridge shutdown uses `os._exit` when native model libraries are loaded. A clean protocol `bye` and exit code are useful, but not proof that all native destructors or active-turn cancellation work normally. |
| Follow-up | Cancellation is not yet end-to-end for agent work | The new socket cancellation reaches neural audio jobs. It does not yet cancel an already-running agent/tool turn. Busy shutdown and cancellation of side-effecting tasks need their own contract and tests. |
| Follow-up | Mode-switch continuity needs coverage | `core/mind_runtime.py` keeps a separate `_chatbot_sessions` collection. Sharing instance memory is not proof that a conversation continues unchanged when switching modes. |

## Fixes implemented in this review

No package-layout churn or replacement agentic loop was introduced.

- `jaeger-agent/jaeger_agent/core/speech.py:53`: native device PCM is validated
  and resampled inside JaegerAgent; the app no longer needs a dictation model.
- `core/speech.py:68`: incremental transcription preserves real Whisper
  segment timestamps, language, previous-sentence prompt, and cancellation,
  under the existing node's authoritative decode lock.
- `core/speech.py:85`: added a streaming Kokoro API; collection remains only
  as an explicit compatibility operation.
- `nodes/vision-mmproj/runtime.py:18`: a modality-aware projector wrapper
  preserves the model's normal GGUF formatter and KV-prefix reuse for text-only
  histories. The installed MTMD handler otherwise calls `llama.reset()` and
  clears KV on every request, even without images. Media in any history turn
  retains the vision decoder, and returning to a media-free history invalidates
  synthetic image positions once. This does not replace the model or agent loop.
- `interfaces/pyside6/multimodal/remote_runtime.py:111`: streaming replies,
  cancellation, prompt/timestamp transport, immediate disconnect errors,
  bounded handshake wait, and safe socket shutdown. A broken UI event
  subscriber no longer strands inference requests.
- `remote_runtime.py:276`: warmup now reaches the real session and mode;
  it no longer returns `True` without doing any work.
- `interfaces/bridge.py:985`: restore output-ownership context in the actual
  turn worker. Context variables do not cross an IPC or thread boundary.
  Attached turns now retain the speech-tool suppression contract.
- `interfaces/bridge.py:962`: losing a face mid-turn cannot kill the one
  turn-worker thread and break subsequent native conversations.
- `interfaces/bridge.py:1089`: serialize projector setup with inference;
  missing projectors fail clearly rather than reporting successful vision.
- `interfaces/bridge.py:1132`: bounded neural job concurrency, input checks,
  cancellation and connected-socket shutdown; refuse to replace a live
  instance's endpoint or an unrelated file.
  A partial startup failure now also rejects turns, warmup, health and audio
  instead of treating an already-loaded Gemma as a fully ready speech agent.
- `interfaces/bridge.py:1720` and Swift `ChatViewModel.swift:225`: native
  Chat/Avatar dictation sends PCM to the same agent-owned Whisper runtime.
  There is no silent fallback to Apple Speech in this conversation path.
- `interfaces/pyside6/multimodal/worker.py:174`: projector loading moved off
  the Qt constructor thread; camera buffering keeps only the latest frame.
- `interfaces/pyside6/multimodal/window.py:1277`: closing/hiding the window
  resets its auto-start lifecycle so reopening can start it again.
- README now describes the real remaining migration boundary and removes
  installation commands for nonexistent package extras.

## Verification

### Model-free regression baseline

| Suite | Before | After |
|---|---:|---:|
| JaegerAI `.venv/bin/python -m pytest -q` | 2677 passed, 10 skipped; 115.81 s | 2692 passed, 10 skipped; 113.03 s |
| JaegerAgent full pytest using the app virtualenv | 469 passed; 14.55 s | 478 passed; 14.11 s |
| Native `swift test` | 36 passed | 36 passed, including recompilation of the dictation change |

Additional checks:

- Agent file-mode selftest: `python tests/test_multimodal_selftest.py` — 23/23.
- App selftest: `python -m jaeger_ai.interfaces.pyside6.multimodal --selftest` — 11/11.
- Agent `python -m jaeger_agent selfcheck --json` — 19/19, 97 registered
  tools, 39 default-bundle tools and 107 recipe skills. Seventeen recipes
  require host-provided tools; these counts do not prove external integrations work.
- Full-duplex preflight:
  `JAEGER_INSTANCE_NAME=jaeger-dev python -m jaeger_ai.interfaces.pyside6.multimodal --check --audio full`
  — **9/9**. It found pyaec, all model assets, the Elgato XLR Dock microphone,
  HD Pro Webcam C920 and OBS Virtual Camera. Enumeration/import success is not
  an acoustic echo-cancellation, live capture, playback or barge-in test.
- `pip check` — no broken requirements in the current editable environment.
- Both wheels built with `pip wheel --no-deps --no-build-isolation`.
  Agent: 3.10 MB, six node manifests and 107 skill recipes. App: 40.67 MB.
  Neither wheel contains bytecode, model GGUFs, or Swift build caches.
- Rebuilt the actual native development bundle with
  `jaeger_ai/interfaces/swift/Scripts/build-app.sh --dev`; its
  `codesign --verify --deep --strict` check passes. This is still an ad-hoc
  development signature, not a notarized distribution build.
- Importing the built agent wheel with `pyaec`, `kokoro`, and `pywhispercpp`
  blocked succeeds; none is imported by `import jaeger_agent`.
- No matches for the former nested multimodal import path in the agent repo.
- `git diff --check` passes in both repositories. Critical Python lint checks
  pass. Full-file Ruff still reports pre-existing lint debt in the bridge/worker;
  it is not described as globally clean.

New regression coverage includes real-socket first-chunk delivery, authentic
Whisper segment transport, cancellation, disconnect during a pending request,
continuation after a closed face, warmup ownership, endpoint collision,
invalid audio/model rejection, native dictation command routing, missing
projector failure, partial boot failure, UI-thread loading avoidance and
latest-frame buffering. Six tests cover the cache router, including both
standalone and late-attachment construction and preservation of image history.

### Real-model application benchmark

The new `dev/benchmark/attached_multimodal.py` starts the **actual native
bridge**, creates isolated application state using the existing hermetic
fixture, and attaches the same engine/runtime/speech proxies used by the
Multimodal window. No standalone replacement Gemma is loaded for the face.
Raw results are independently scored by the original VoiceLLM scorer.

The first exploratory run is saved under
`dev/benchmark/results/release_review_20260904/attached_agentic.json` with its
bridge log and lifecycle record. It verifies all 19 cases and clean process
exit. Its `load_ms=108.81` is **only face attachment time**, not model load;
the bridge itself took 31.31 seconds to become ready. The comparison file's
load row must not be used as a performance claim. The runner was corrected
to include bridge/projector startup and separately label engine startup.

The corrected **chatbot control** completed on the updated transport:

| Metric | Gemma modular reference | Attached JaegerAI chatbot |
|---|---:|---:|
| Correct | 19/19 | 19/19 |
| Spoken WER | 2.90% | 2.90% |
| Overall audio coverage | 100% | 100% |
| Spoken cases with audio | 12/12 | 12/12 |
| Median spoken first audio | 1.843 s | 1.851 s |
| Startup / load | 15.699 s | 28.200 s |
| Runtime errors | 0 | 0 |
| Bridge exit | clean baseline | exit 0, `bye` received |

The 8 ms latency difference is **single-run near-parity**, not a statistically
established equivalence. Both use the same M1 Max and Gemma E4B Q4_K_M; the
app uses its configured 32K context and 4096-token ceiling, rather than
pretending these were the smaller standalone benchmark settings. Sampling
temperature is 0. The native dictation probe also recognized the recorded
“What is 2 plus 2?” through the actual stdio command in 571 ms.

Artifacts: `attached_chatbot_final.json`, `attached_chatbot_comparison.md`,
and the matching `.bridge.log` / `.lifecycle.json` files in the same results
directory. This control strongly points to the app's agentic composition as
the source of the large steady-state gap; it does not identify the exact
prompt, tool, or persona contribution without further profiling.

Further inspection did identify a concrete contributor: installed
`llama_cpp/llama_chat_format.py:3511` resets the model and clears KV before
every MTMD call, including text. The exploratory application's
`logs/latency.jsonl` records approximately **15.8 s first-token latency** on
one-iteration spoken turns with **zero tool calls**; the calculator itself
took **1 ms**. Re-evaluating the large prompt, not executing the calculator
or reloading Whisper/Kokoro, dominates these observations. The node wrapper
above addresses text-only cache reuse. Real image-history optimization remains
a separate problem; it must not discard images to improve a timing score.

The **post-cache-fix agentic run** then verified the improvement:

| Metric | Exploratory app run, before cache fix | Final agentic run |
|---|---:|---:|
| Correct | 19/19 | 19/19 |
| Spoken WER | 2.90% | 2.90% |
| Spoken audio coverage | 7/12 | 7/12 |
| Median spoken first audio, audio-producing cases | 17.971 s | 1.891 s |
| Calculator case total | 34.481 s | 2.135 s |
| Capital-of-Japan text case total | 16.351 s | 0.672 s |
| Worst spoken first audio | 19.371 s | 17.417 s |
| Image case totals | 17.383 / 17.317 s | 16.909 / 16.731 s |
| Full startup boundary | not captured correctly in first run | 36.221 s |
| Runtime errors | 0 | 0 |
| Bridge lifecycle | exit 0 + `bye` | exit 0 + `bye` |

The long final spoken outlier is the first speech request after image-history
processing. The cache is intentionally invalidated at that transition to avoid
reusing synthetic image token positions as text. Warm medians are near the
reference; cold transitions, image prompt evaluation and startup are not.
Agentic audio coverage is a deliberate output-channel choice, not missing
Kokoro synthesis, but it makes an all-cases audio parity claim invalid.

The final file workflow executed both `write_file` and `read_file`, verified
the actual temporary file's `READY-012` contents and the model's readback,
and completed in 15.25 s. An intermediate pre-cache run also passed this
workflow, but needed recovery from an absolute-path rejection; its timing
is not an apples-to-apples workflow speed comparison. The final prompt uses
the tool's documented workspace-relative path.

See [the final agentic comparison](../../../benchmark/results/release_review_20260904/attached_agentic_cached_comparison.md)
and [raw final agentic result](../../../benchmark/results/release_review_20260904/attached_agentic_cached.json).
Only the final timing pass was used to evaluate the cache fix; an intermediate
correctness/lifecycle pass overlapped regression testing. These are development
iterations, **not three repetitions of an unchanged release candidate**.

The final-code chatbot rerun also passed **19/19**, **2.90% WER**, **100% audio
coverage**, and clean shutdown: median first audio **1.564 s**, worst **2.016 s**,
startup **26.178 s**. See [its comparison](../../../benchmark/results/release_review_20260904/attached_chatbot_cached_comparison.md)
and [raw result](../../../benchmark/results/release_review_20260904/attached_chatbot_cached.json).
Across all five development runs, all 95 submitted benchmark cases scored
correct, no case recorded a runtime error, and every bridge emitted `bye` and
exited 0. The two file-workflow runs also passed. This does not certify
active-turn shutdown, live devices, every external skill or production security.

Reproduction, from the JaegerAI repository root:

```bash
.venv/bin/python dev/benchmark/attached_multimodal.py \
  --source-instance .jaeger_os/instances/jaeger-dev \
  --benchmark-dir '../VoiceLLM-Playground/Multimodal LLM/benchmark' \
  --audio-dir ../jaeger_agent_omni/research/cases12 \
  --model-path jaeger_ai/models/gemma-4-E4B-it-Q4_K_M.gguf \
  --output dev/benchmark/results/release_review_20260904/attached_agentic_cached.json \
  --workflow
```

Use `--no-agentic-tools` without `--workflow` for the chatbot control.
The file workflow additionally checks an actual file creation/readback inside
the temporary workspace. The native dictation probe exercises stdio NDJSON,
not just the attached-face Unix socket. Neither replaces live GUI acceptance.

### Release acceptance still required

1. Complete the single-pipeline migration across native, TUI and scheduled
   user-facing output. Pin it with cross-interface integration tests.
2. Run three controlled full repetitions per mode, same settings/hardware,
   reporting accuracy, spoken-only audio coverage, median/tail latency,
   startup boundary, process exit and real tool execution separately.
3. Exercise live devices, GUI open/close/reopen, busy shutdown, device removal
   and multi-window arbitration. Verify no duplicate model loads or overlapping
   owners of the microphone/speaker.
4. Pass sandboxed security gates, clean-install/update/rollback tests against
   published immutable dependencies, then sign and notarize release artifacts.
