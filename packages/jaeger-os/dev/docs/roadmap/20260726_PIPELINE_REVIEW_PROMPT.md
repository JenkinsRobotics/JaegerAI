# Independent pipeline review — JaegerOS + its modules

You are reviewing a robotics/AI framework and the three modules built
on it. **Be adversarial.** The work below was done in one long session
by a single agent with no second opinion, and the operator wants to
know what it got wrong before more is built on top.

Prefer "this specific thing is broken, here is the file and line" over
general impressions. If you think a decision is wrong, say so plainly
and say what you would do instead. If you think it is right, say that
too — but only after checking, not from the description.

---

## The repos

All on local disk, all committed, **nothing pushed**. Read the git log
in each; the commit messages carry the reasoning.

| Repo | Branch | Suite |
|---|---|---|
| `~/GITHUB/JaegerOS` | `jaeger-animation` | `.venv/bin/python -m pytest dev/tests -q` → 420 |
| `~/GITHUB/JaegerWhisperSTT` | master | `.venv/bin/python -m pytest jaeger_whisper_stt -q` → 22 |
| `~/GITHUB/JaegerKokoroTTS` | master | `.venv/bin/python -m pytest jaeger_kokoro_tts -q` → 20 |
| `~/GITHUB/JaegerAnimation` | master | `.venv/bin/python -m pytest jaeger_animation/tests -q` → 107 |
| `~/GITHUB/Jaeger-Template` | master | (docs + scaffolding only) |

**Do not modify `~/GITHUB/JaegerAI`.** It is a shipped product pinned
to `jaeger-os@0.9.0` by git tag and is deliberately outside this work.
Read it if useful.

Each module repo has its own `.venv` with the local framework installed
editable. Use those, not each other's.

---

## What changed, in order

1. **A topic path grammar** (`jaeger_os/contract/paths.py`) —
   `/<category>/<class>/<instance>/<message>`, subscribable by prefix
   at any level, with the transport doing the filtering.
2. **The contract migrated onto it** — 31 topics, three categories
   (`/sense/` inputs, `/act/` outputs, `/sys/` framework), split by
   direction relative to the brain.
3. **Animation and media message sets merged** — six classes became
   three (`DisplayCommand`/`DisplayFrame`/`DisplayState`).
4. **An audio driver** (`jaeger_os/nodes/audio_io/`) — one node owning
   the mic, the speaker and echo cancellation. Whisper, Kokoro and the
   chimes all stopped opening devices.
5. **Framework-standard module gates**
   (`Jaeger-Template/dev/tests/test_framework_standards.py.example`,
   copied into each module).

---

## The claims to attack

Each of these was asserted during the work. Verify or refute.

1. **"A subscriber to `/sense/camera/cam0/` never receives `cam1`."**
   Check both transports. The in-process bus and the ZMQ bus must agree
   exactly — if they diverge, code that works fused breaks the moment a
   node moves to its own process.

2. **"Instance paths inherit their canonical topic's QoS and
   binary-ness."** This was a live bug found and fixed
   (`jaeger_os/contract/qos.py`). Are there other resolvers that
   *don't* canonicalize? Grep for `TOPIC_QOS`, `BINARY_TOPICS`,
   `TOPIC_TO_CLASS` and any other dict keyed by topic.

3. **"Dropping `topic: Literal[...]` for `topic: str` lost no
   validation."** The claim is that `codec.decode` comparing canonical
   forms is *strictly stronger*. Construct a payload that the old
   `Literal` would have rejected and the new check accepts.

4. **"One node owning mic + speaker is required, because AEC needs
   both signals per frame."** Is that actually true, or would two
   drivers plus a far-end topic work? Note `speexdsp` is NOT installed
   on this machine, so the speexdsp path is dormant — echo cancellation
   currently comes from Apple's `voice_processing` inside
   `avaudio_io/input_stream.py`. Does the driver preserve that
   correctly? See the `vp = self._aec is None` resolution.

5. **"Capture is 16 kHz, playback 24 kHz, and the AEC reference must be
   at the capture rate."** Check the resampling in
   `nodes/audio_io/node.py::_resample` — including the scipy-absent
   fallback. Is the linear interpolation acceptable for an AEC
   reference, or does it need proper filtering?

6. **"Publishing from the audio callback is safe because the bus never
   blocks."** Audit every path out of `_on_captured` and
   `_fill_playback` for anything that can block, allocate
   unboundedly, or take a lock held elsewhere. A blocked audio thread
   is an audible glitch.

7. **"~1.6% overhead per mic frame."** Measured in-process only
   (0.011 ms bus hop, 0.149 ms `tobytes()`, against a 10 ms frame).
   Re-measure. Then measure the ZMQ path, which was NOT measured.

8. **"Pause is local now, and that is strictly better."** Whisper's
   `_MicStream.set_paused()` used to stop the device; it now drops
   frames on arrival. Is there a case where the old behaviour mattered
   (power, thermal, privacy — a mic LED that stays lit)?

---

## Specific areas of low confidence

**The audio refactor is untested against real hardware.** Everything
is headless with fake streams. Nobody has heard it. Barge-in, echo
cancellation, and device selection are all unverified in a real room.

**`AudioSession.barge_in_live`** now reports what the operator
*configured*, not whether cancellation is actually happening — the
driver's `health()` is authoritative. Is that a regression in
observability? Should the session query the driver?

**Two silent-failure guards were added** (whisper's mic liveness
timeout, kokoro's drain timeout) because subscribing to an unpublished
topic *succeeds*. Are there other places in this design with the same
shape? `BusCatalog.orphan_topics()` computes this at runtime and
nothing calls it at boot.

**`jaeger_os/nodes/testing.py` publishes `/act/display/play`.** A test
helper is currently the only producer of a production topic. Check
whether that masks a missing real producer.

---

## The wiring picture, as of this review

Generated by walking module manifests + framework source. `fw:` = a
framework node.

```
CLOSED LOOP (10)
  /sense/mic/pcm          audio_io          -> whisper_stt
  /sense/stt/transcript   whisper_stt       -> fw:nodes/base
  /act/display/play       fw:nodes/testing  -> animation      (test helper!)
  /act/speech/say         fw:nodes/base     -> kokoro_tts
  /act/speaker/pcm        kokoro_tts,chimes -> audio_io
  /act/speaker/stop       kokoro_tts        -> audio_io
  /act/speaker/state      audio_io          -> kokoro_tts
  /act/estop/trigger      fw:hardware/safety-> fw:hardware/safety
  /sys/node/health        fw:nodes/base     -> fw:app/health
  /sys/node/meta          fw:nodes/base     -> fw:app/catalog

HALF-WIRED (11) — mostly the Mind↔Body seam; JaegerAI is the
missing end for several, and it is pinned to 0.9.0
  /sense/camera/image_raw   vision      -> (nobody)
  /sense/stt/speech_start   whisper_stt -> (nobody)
  /act/display/{stop}       (nobody)    -> animation
  /act/display/{frame,state,stats}  animation -> (nobody — no renderer)
  /act/speech/stop          (nobody)    -> kokoro_tts
  /act/speech/{spoken,chunk} kokoro_tts -> (nobody)
  /act/motor/command        (nobody)    -> fw:nodes/motor
  /act/light/set            (nobody)    -> fw:nodes/light

ORPHAN (10) — neither end
  /sense/touch/event        /sense/proprio/state
  /act/timeline/run         /act/timeline/progress
  /sys/trace/step           /sys/gate/decision
  /sys/skill/{xp_awarded,level_up,unlocked,mastered}
```

**Question worth answering:** 6 of the 10 orphans
(`trace`, `gate`, `skill`×4) exist only because JaegerAI emits them.
Should product-tier events be in a framework contract at all? They are
evictable — JaegerAI's tag pin means removing them breaks nothing until
someone bumps it.

`/act/timeline/*` is declared with message classes and no
implementation anywhere. The repo has a stated rule against "spec ahead
of code" — does this violate it, and should it be deleted?

---

## Conventions this work is supposed to obey

Read these first; they are the standard to judge against.

- `Jaeger-Template/CONVENTIONS.md` — especially law 1 (one copy of
  every truth), "Declare three surfaces", and the new "Naming a topic"
- `Jaeger-Template/TAXONOMY.md` — the five tiers and Module KINDS
  (driver / processing / engine / mind)
- `JaegerOS/dev/docs/roadmap/20260726_ros_parity_review.md` — the
  ROS-parity gaps and the migration ledger
- `JaegerOS/jaeger_os/contract/paths.py` — the grammar's own rationale

Two rules that were applied and are worth checking were applied
*consistently*:

- **No back-compat shims pre-1.0.** Legacy paths should have been
  deleted, not kept. Find any that survived.
- **No spec ahead of code.** A declared topic with no implementation
  is a violation.

---

## What to deliver

1. **Defects**, most severe first: file, line, what breaks, and the
   concrete input or sequence that triggers it.
2. **Design decisions you would reverse**, with reasoning.
3. **Things the tests assert that are vacuous** — a test that cannot
   fail is worse than no test, because it reads as coverage. Several
   were found and fixed during this work (`ALL_TOPICS` was compared
   against the registry it is derived from); assume more remain.
4. **What is missing** — the gate nobody wrote, the failure mode
   nobody guarded.

Do not fix anything. Report.
