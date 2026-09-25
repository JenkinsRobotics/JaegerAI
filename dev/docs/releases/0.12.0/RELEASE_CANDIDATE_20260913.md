# Jaeger AI 0.12.0 release candidate — 2026-09-13

The source candidate is prepared for release review. **Public shipment is still
held for live conversation acceptance and macOS distribution validation.**
The native bundle is a repository-backed development launcher, not a portable,
notarized application zip. Full/quasi duplex remains experimental.

## Changes completed

- Ground desktop, camera, spoken, and CLI turns in the shared worker before
  persona composition. Preserve images, selected output channels, cancellation,
  and explicit exact-answer constraints. Voice input normally receives speech.
  Carry caller cancellation scopes across the attached socket, as well as the
  face's explicit Stop action; later requests retain independent cancellation.
- Route native/TUI final speech through the process-owned JaegerAgent Kokoro
  runtime, with bounded playback writes and cancellation cleanup. Serialize
  scheduled and interactive bridge turns across persona/session bookkeeping.
- Reject stored permission grants and safeguard overrides before writing facts;
  filter legacy authorization claims from the initial facts snapshot. Runtime
  permissions remain authoritative. This is not a claim of universal injection
  resistance.
- Reuse exactly matching text tokens before images while decoding every image
  anew. Image positions are excluded from text-prefix reuse.
- Drain the installer's process table before refusing a live legacy migration;
  busy hosts now receive the intended warning instead of a SIGPIPE exit.
- Close and restart the Qt face asynchronously while its worker finishes.
  Avoid freeing native model contexts while a bridge worker or cron job is active.
- Publish four immutable dependency candidates and replace the missing agent
  branch reference. Pin llama-cpp-python 0.3.34. Install Kokoro's English language
  model with the audio extras, and package the exact 1,289,603-byte reference
  Silero VAD with its MIT license and checksum.
- Enforce OS isolation before adversarial model scenarios. Fail release commands
  on failed/inconclusive security cases, wrong benchmark answers, missing voice
  audio, or dirty wheels. Native builds now verify both signatures and actual
  embedded-interpreter startup; the Python helper has scoped library/JIT
  entitlements required to load the installation's native libraries.

## Verification

| Check | Result |
| --- | --- |
| JaegerAI final full pytest | 2,753 passed, 10 skipped |
| Final bridge/attached serialization and cancellation checks | 67 passed |
| Final package/scenario checks | 71 passed |
| Installer migration, including large process table | 3 passed |
| JaegerAgent full pytest, including bundled VAD | 511 passed |
| JaegerOS full pytest | 561 passed |
| Kokoro/Whisper manifest checks | 19 passed, 2 skipped |
| Swift tests | 39 passed |
| Multimodal event-routing selftest | 11/11 |
| Final enforced-sandbox security suite | 15/15, no inconclusive cases |
| Actual product artifact update/rollback from 0.9.6 | Passed; temporary state and environment preserved |
| App and agent wheel hygiene/required assets | Passed |
| Critical-error lint and git whitespace checks | Passed |
| Native release build, strict signature verification, embedded Python launch | Passed with ad-hoc signing |

The final full app suite includes the bridge serialization, cancellation-scope,
and installer fixes. Focused checks are listed for traceability and overlap with
that suite. Four dependency warnings remain; skipped tests are not counted as passes.

The security runner first verified that a subprocess could not read, rewrite,
or chmod an outside canary or open a network connection. The 15 model scenarios
then ran under that same OS boundary with disposable state and no credentials.
Intermediate failures were retained locally: persona-only routing skipped file
reads, and a later refusal quoted internal prompt wording. The final run passed
all cases without relaxing the checks.

[Security results](../../../benchmark/results/release_candidate_20260913/security_release.json),
[capture results](../../../benchmark/results/release_candidate_20260913/capture.json),
[update/rollback results](../../../benchmark/results/release_candidate_20260913/update_rollback.json).

## Real model results

Gemma 4 E4B Q4_K_M, 32,768-token worker context, Whisper large-v3-turbo, Kokoro
`af_heart`. The reference scorer evaluates raw answers. Recorded speech tests
start after endpoint detection and synthesize PCM without speaker playback.
They do not certify a live acoustic conversation or AEC.

| Run | Correct | Voice answers with audio | Speech WER | Median first generated voice audio |
| --- | --- | --- | --- | --- |
| Agentic, development environment | 19/19 | 12/12 | 2.90% | 1.957 s |
| Chatbot, fresh non-editable installation | 19/19 | 12/12 | 2.90% | 1.831 s |
| Agentic, final non-editable installation and packaged VAD | 19/19 | 12/12 | 2.90% | 1.801 s |

Agentic file creation/readback and agentic → chatbot → agentic recall passed.
All three recorded runs exited with status 0 and protocol `bye`. The final clean
agentic run also cancelled an active request: the attached caller returned in
16 ms, and a following same-session request answered `AFTER-CANCEL`. This measures
caller responsiveness and recovery, not immediate interruption inside native
model evaluation. An earlier run exposed a missing cancellation-scope handoff
in the attached client; the transport and socket regression tests were corrected.
An intermediate
agentic run answered correctly but spoke only 1/12 voice replies; the output
instruction was corrected, and spoken-audio coverage is now an explicit gate.

Latency parity is not certified. In the full agentic sequence the first image
after a memory case still took about 12 seconds; the next image took 1.53 seconds.
The small initial image-only probe's roughly 2-second timings must not be
presented as every image turn's latency. Bridge-plus-engine startup was about
42 seconds in the development agentic run, 48 seconds in the clean chatbot
run, and 44 seconds in the final clean agentic run. These are development measurements, not a controlled statistical study.

[Agentic results](../../../benchmark/results/release_candidate_20260913/agentic_voice_final.json),
[clean chatbot results](../../../benchmark/results/release_candidate_20260913/chatbot_clean_final.json),
[final clean agentic results](../../../benchmark/results/release_candidate_20260913/agentic_clean_release.json).

## Fresh installation and hardware boundary

A new Python 3.11 environment installed the application non-editably and fetched
all four dependencies from their published Git commits, with no sibling editable
overrides. Real model/Whisper/Kokoro execution passed both agentic and chatbot
suites; the final agentic run explicitly selected the installed VAD default.
The missing English language model discovered on the first attempt is now an
explicit dependency. The VAD default now resolves inside the installed package;
its bytes match the existing reference exactly and a real ONNX quiet-frame probe
passed. The clean environment has no need for the developer's VAD folder.

GGUF, matching vision projector, Whisper and Kokoro weights still require normal
model setup/cache access; the live tests reused this machine's configured model
files and model caches. This is a clean package installation on the same Mac,
not an untouched second-machine or offline-first installation certification.

The rebuilt embedded helper captured 316 microphone blocks and 476 camera frames.
All four phases passed: initial capture, unmute, camera off/on, and resource
restart. Mute stopped callbacks, audio arrived before the first camera frame,
and geometry remained stable. No camera images or microphone recordings were
saved. This probe did not run inference or play speech.

## Remaining shipment gates and scope

1. Run a human microphone-to-speaker conversation with this candidate: ordinary
   questions, camera reference, interruption/stop, reconnect, and error recovery.
   Full/quasi duplex additionally needs echo and double-talk acceptance; until
   then Half-Duplex remains the supported default.
2. For a distributable macOS binary, provide a Developer ID signing environment,
   complete packaging for the chosen installer format, notarize/staple, and test
   Gatekeeper on another Mac. This machine has no valid code-signing identity.
   `build-app.sh --distribution` correctly refuses ad-hoc signing.
3. Do not advertise all interfaces as one identical capture pipeline: the legacy
   TUI retains its AudioSession STT adapter and deliberately pauses capture during
   agent-owned speech. Native Chat/Avatar/Multimodal share the bridge's speech
   nodes. Reference-image gesture boxes, object tracking, and annotated video
   export are not implemented product claims.

No stable release/tag or public app download has been published by this work.
The candidate branches allow code review and reproducible source installation.

## Immutable dependency commits

- JaegerOS: `53d5ad61699b91a6b250a658456b8c45e78cc4ff`
- JaegerAgent: `88715a5dd4ed09706892ad270cc087bd8358972c`
- JaegerKokoroTTS: `e36f53223d70eff8fb6c828dc367ea49da6b77db`
- JaegerWhisperSTT: `816f78b5f48aa373d4a06616bfad7fd4b8d80b3e`

The dependency source candidates include the pre-existing coordinated host,
module-identity, and cancellation changes required by this working stack.
