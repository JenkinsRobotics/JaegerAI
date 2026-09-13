# Multimodal hardening and pipeline ranking — 2026-09-04

This follows [the production review](PRODUCTION_REVIEW_20260904.md). Changes
remain local on JaegerAI `0.12.0` and JaegerAgent `1.2.0`; no release is published.

## Ranking: release suitability, not an unmeasured speed contest

| Rank | Pipeline | Recommendation | Evidence and trade-off |
|---|---|---|---|
| 1 | Half-duplex (`structured`) | Default; first live acceptance target | Engine-owned endpointing and structured acoustic context, microphone gated during speech. Fewest overlap/echo failure modes. Text, camera frames and agentic tools remain available. |
| 2 | Quasi-full-duplex (`quasi`) | Experimental | Adds 48 kHz duplex I/O, AEC and barge monitoring while retaining utterance-based decoding. More interactive, but acoustic double-talk and false interruption behavior are not certified. |
| 3 | Full-duplex (`full`) | Experimental | Adds incremental Whisper, stream governor, drift anchoring and utterance aggregation. Greatest overlap capability and synchronization complexity; no measured live-quality/latency advantage is claimed. |
| Control | Plain (`plain`) | Benchmark/diagnostic only | Bypasses structured endpoint/context behavior. Useful for matching the original Gemma recorded suite, not a substitute for live duplex tests. |

Agentic versus chatbot is an independent axis, not a fourth duplex pipeline.
Agentic remains the default and keeps tools/memory. Chatbot uses a strictly
tool-free adapter with the same model and conversation continuity. Its
always-speech benchmark policy differs from agentic dynamic output selection.

## Implemented in this follow-up

- **Request-scoped cancellation:** `jaeger_agent/core/cancellation.py` binds
  the host request event to the existing loop's interrupt event. A cancellation
  before entry is not cleared; a late signal cannot cancel a later request.
  The loop and permission/tool dispatch machinery are not replaced.
- **Real face interruption:** `interfaces/bridge.py` registers and binds
  cancellation for queued/active turns, skips cancelled queued commands, and
  cancels outstanding requests on socket disconnect. Another face cannot cancel
  those requests even if it uses the same session name.
- **Responsive speech interruption:** the attached client stops waiting for a
  blocked Kokoro chunk immediately, while the server cancels at its next safe
  point. Force-listen reaches the agent and suppresses late reply speech.
  Cancellation cannot roll back completed writes or forcibly stop arbitrary
  third-party tools/native kernels.
- **Atomic mode selection:** a GUI toggle applies at the next engine turn;
  it cannot change tool availability or output policy halfway through an answer.
  A missing chatbot implementation fails closed, never into agentic mode.
- **Conversation continuity:** switching modes transfers the current transcript,
  including media and complete tool/result pairs, without sharing mutable lists.
  New-chat clears both modes, preventing an old transcript from reappearing.
  This is short-term session continuity, not a second memory database.
- **One speech configuration:** `Config.multimodal` embeds the agent's own
  `MultimodalConfig`. Bridge startup uses it for Whisper/Kokoro and the projector;
  the attached worker fetches the running configuration before loading. Explicit
  window audio/output selections override those two fields for that session.
  Settings are exposed by the existing catalog and marked restart-required.
  `kokoro_tts` and `whisper_stt` remain separate optional tool-module settings;
  they no longer purport to configure these agent speech nodes.
- **Honest timing:** user-facing turn time includes the personality output filter.
  Cancelled turns skip that filter and do not schedule follow-up memory review.
- **Repeatable checks:** the application benchmark now optionally tests recall
  across agentic → chatbot → agentic, in an isolated instance, in addition to
  the original 19 cases and real file write/readback workflow.

## Configuration

Existing config files acquire defaults without a destructive migration. The
following optional instance `config.yaml` section configures the agent stack:

```yaml
multimodal:
  audio_mode: structured
  output_mode: dynamic
  stt_model: large-v3-turbo
  kokoro_voice: af_heart
  kokoro_language: a
```

Use the Multimodal settings group and restart the agent to apply model/voice/path
changes. Changing a standalone speech tool's settings is intentionally separate.
Half-duplex and agentic are still the initial GUI defaults.

## Remaining release gates — not waived by passing tests

1. **One conversational front door is unfinished.** Native/TUI still have the
   persona-first and legacy voice composition; the attached multimodal engine
   enters the agentic tool loop directly for content-bearing turns. The neural
   models are shared, but this is not yet one shared end-to-end floor/output
   controller across every interface. Native/TUI/cron final-output migration
   must preserve character behavior explicitly, not silently bypass it.
2. **Live acceptance:** record half-duplex wake/endpoint behavior, quasi/full
   far-end echo, near-end speech, double-talk, stop/continue barge policy, mute,
   camera-off, device removal/recovery and shutdown. Enumeration is not an
   acoustic test. Camera inputs are sampled images, not a certified temporal
   video-reasoning benchmark.
3. **Tail latency:** the preceding measured agentic run had an approximately
   17-second first spoken response after vision. Median-only parity is insufficient.
4. **Security:** the previously reported memory-poisoning miss remains a release
   blocker. Host-breakout/allow-all model scenarios must run in an enforced
   sandbox; a temporary working directory alone is not a sandbox.
5. **Distribution:** the required public `jaeger-agent@1.2.0` ref remains absent
   on remote inspection. Clean-install testing needs an authorized coordinated
   release/pin. Developer ID signing/notarization is still outstanding.
6. **Lifecycle:** cooperative cancellation covers the actual core loop and face
   transport, not every legacy persona callback or arbitrary blocking tool.
   Native model teardown still relies on process exit; busy-shutdown acceptance
   remains necessary.

No claims of full production readiness or certified live full-duplex performance
are made by this follow-up.

## Verification

Final regression results, after the defensive follow-ups:

| Suite | Before this follow-up | Final |
|---|---:|---:|
| JaegerAI pytest | 2692 passed, 10 skipped | **2700 passed, 10 skipped**; 119.21 s |
| JaegerAgent pytest | 478 passed | **485 passed**; 14.65 s |
| Native Swift | 36 passed | **36 passed** |
| Total passing tests | 3206 | **3221** |

All original tests remain passing. The 15 additional tests cover cancellation,
disconnect/blocked-TTS recovery, malformed-request survival, session-scoped
interrupts, mode handoff and settings. Three dependency deprecation warnings
remain in the final app run. Logs: `/tmp/jaeger-ai-hardening-verified.log`,
`/tmp/jaeger-agent-hardening-verified.log`, and
`/tmp/jaeger-swift-hardening-final.log`.

Code locations (paths relative to their respective repositories):

| Change | Location |
|---|---|
| Request cancellation binding | `jaeger_agent/core/cancellation.py:20`, `jaeger_agent/loop/jaeger_agent.py:340` |
| Next-turn mode selection / force listen | `jaeger_agent/core/engine.py:782`, `jaeger_agent/core/engine.py:790` |
| Built-in runtime session interruption | `jaeger_agent/core/runtime.py:364` |
| Mode transcript handoff | `jaeger_ai/core/mind_runtime.py:188` |
| Agent config embedded in app | `jaeger_ai/core/instance/schemas.py:836` |
| Validated speech startup config | `jaeger_ai/interfaces/bridge.py:695` |
| Client request and speech cancellation | `jaeger_ai/interfaces/pyside6/multimodal/remote_runtime.py:198` |
| Mode toggle forwarding | `jaeger_ai/interfaces/pyside6/multimodal/worker.py:254` |
| Factory-default settings serialization | `jaeger_ai/core/settings/catalog.py:117` |

Commands used from the JaegerAI repository:

```bash
.venv/bin/python -m pytest -q
(cd ../jaeger-agent && ../JaegerAI/.venv/bin/python -m pytest -q)
(cd jaeger_ai/interfaces/swift && swift test)
.venv/bin/python ../jaeger-agent/tests/test_multimodal_selftest.py
.venv/bin/python -m jaeger_ai.interfaces.pyside6.multimodal --selftest
.venv/bin/python -m jaeger_agent selfcheck --json
JAEGER_INSTANCE_NAME=jaeger-dev .venv/bin/python -m jaeger_ai.interfaces.pyside6.multimodal --check --audio full
.venv/bin/python -m pip check
```

The import check actively blocks `pyaec`, `kokoro`, and `pywhispercpp` and
confirms `import jaeger_agent` still succeeds. Critical Python lint and
`git diff --check` pass; full-repository lint debt is not claimed resolved.

Real-model command:

```bash
.venv/bin/python dev/benchmark/attached_multimodal.py \
  --source-instance .jaeger_os/instances/jaeger-dev \
  --benchmark-dir '../VoiceLLM-Playground/Multimodal LLM/benchmark' \
  --audio-dir ../jaeger_agent_omni/research/cases12 \
  --model-path jaeger_ai/models/gemma-4-E4B-it-Q4_K_M.gguf \
  --output dev/benchmark/results/release_review_20260904/attached_agentic_hardened.json \
  --workflow --mode-switch
```

Chatbot control uses `--no-agentic-tools`, omits `--workflow --mode-switch`, and
writes `attached_chatbot_hardened.json`. Both use the original external scorer.
The source instance is read as a template; all benchmark writes stay in a fresh
temporary instance. No microphone, camera or speaker is opened by this suite.

### Real-model results

| Metric | Original Gemma modular | JaegerAI chatbot | JaegerAI agentic |
|---|---:|---:|---:|
| Correct cases | 19/19 | 19/19 | 19/19 |
| Spoken WER | 2.90% | 2.90% | 2.90% |
| Spoken cases producing audio | 12/12 | 12/12 | 7/12 |
| Median spoken first audio | 1.843 s | 1.701 s | 2.008 s |
| Worst spoken first audio | — | 2.255 s | 18.255 s |
| Startup/load boundary | 15.699 s | 28.140 s | 43.087 s |
| Case runtime errors | 0 | 0 | 0 |
| Process exit | clean reference | exit 0 + `bye` | exit 0 + `bye` |

These are single runs, not a three-repetition statistical comparison. The
agentic median excludes five spoken cases that intentionally selected no audio;
it is not directly comparable to the reference's always-speech denominator.
Chatbot steady-state latency is reference-level in this run, but app startup is
not. Agentic image cases took 17.381/17.376 seconds; cold/vision and mode-switch
costs still prevent a blanket latency-parity claim.

The actual `write_file` → `read_file` workflow passed in 15.771 seconds and
verified `READY-012` in the isolated workspace. The new mode-continuity check
also passed: both chatbot and the restored agentic mode recalled
`ORBIT-CEDAR-712` from the original agentic turn. Returning to the tool-bearing
prompt took 16.31 seconds, so this proves continuity, not instant mode switching.

Artifacts:

- [Agentic raw results](../../../benchmark/results/release_review_20260904/attached_agentic_hardened.json)
  and [independent comparison](../../../benchmark/results/release_review_20260904/attached_agentic_hardened_comparison.md).
- [Chatbot raw results](../../../benchmark/results/release_review_20260904/attached_chatbot_hardened.json)
  and [independent comparison](../../../benchmark/results/release_review_20260904/attached_chatbot_hardened_comparison.md).
- Matching `.lifecycle.json` files record isolated instance paths and clean exits.

The final malformed-request/disconnected-transport guards and chatbot telemetry
correction were added after these successful-turn measurements; their behavior
is covered by the subsequent regression run, not claimed as an extra model run.

### Packaging and additional checks

- Agent selftest: **23/23**; UI event selftest: **11/11**.
- Agent selfcheck reports `ok: true`; duplex device preflight: **9/9**.
- `pip check`: **No broken requirements found** in the existing editable environment.
- Fresh wheels built successfully in `/tmp/jaeger-hardening-wheels.lHopWq`:
  app 40,680,371 bytes; agent 3,097,537 bytes. The agent wheel contains the new
  cancellation module and all six node manifests. The app wheel has no GGUFs,
  bytecode caches or Swift build directory.
- Importing the **built agent wheel**, with all three optional neural dependencies
  blocked, succeeds. This does not replace a clean-install test of remote pins.
- No former nested multimodal import path remains in the agent repository.

For a local development launch after testing: `./jaeger dev --dev`. This is a
development build, not a claim that the release gates above have passed.
