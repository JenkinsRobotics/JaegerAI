# ROS 2 parity review — the five structural categories

> **Measured 2026-07-25** against JaegerOS 0.9 (`jaeger-animation` branch),
> prompted by building JaegerAnimation as the first out-of-tree engine
> module. Numbers below are from real runs on this machine, not estimates.
>
> Scope: the five categories that define "a framework other things build
> on", plus the one place JaegerOS deliberately **diverges** from ROS.
> Verdict per category, then improvements ranked by what they buy.

| # | Category | Verdict |
|---|---|---|
| 1 | Node declares its own I/O | **partial** — declarative, unenforced, no introspection, no remapping |
| 2 | Node owns its own health | **partial** — liveness yes, severity/aggregation no |
| 3 | Framework provides plumbing | **below parity** — one queue, one thread, no QoS |
| 4 | App wires it together | **partial** — no remapping, namespaces, or conditionals |
| 5 | App holds project-unique code | **at parity** |
| 6 | Agentic I/O | **beyond ROS** — no equivalent exists; ours to define |

---

## 1. Node declares its own I/O — *partial*

**At parity:** `module.yaml`'s `consumes:`/`produces:` is a genuine
declarative contract, and arguably cleaner than ROS's, where a node's
topics are discoverable only by reading code or running the node. Ours is
readable before anything boots — that is what let JaegerAnimation bind to
a slot without JaegerOS ever naming it.

**Gap 1a — the declaration is not enforced.** Nothing stops a node
publishing a topic absent from its `produces:`. The manifest becomes
documentation that silently drifts. *Fix:* a debug-mode bus that warns
when a publish's topic isn't in the publishing node's declared set. Cheap;
catches drift the day it happens rather than at integration.

**Gap 1b — no runtime introspection.** ROS 2 ships `ros2 topic list/info/
hz/echo`. JaegerOS has no way to ask a live system what is publishing
what, at what rate. Debugging is print statements. *Fix:* a bus-side
catalog (topic → publishers, subscribers, last-seen, rate) plus a
`jaeger topics` CLI. One bus means the catalog is nearly free — every
message already passes one point. Already named in `FRAMEWORK_GAPS.md`
as the "tag registry"; this review raises its priority: it is the single
biggest ergonomics gap versus ROS.

**Gap 1c — no remapping or namespaces.** ROS's most-used composition
feature. Two instances of the same node are made distinct by remapping
their topics at launch. JaegerOS has none: two animation nodes both
publish `/act/display/frame`, and a subscriber must receive *both*
and discard by `node_id`. It works, and it wastes the full cost of every
frame it throws away. This directly blocks the documented two-display
case (a unit with a face and a status panel). *Fix:* per-node
`remap = { "/act/display/frame" = "/sense/face_frame" }` in the
manifest, applied at subscribe/publish time.

## 2. Node owns its own health — *partial*

**At parity:** four-phase lifecycle maps 1:1 onto ROS 2 managed nodes,
`health()` is queryable, `NodeHealth` heartbeats on a topic.

**Gap 2a — no severity.** `NodeHealth` carries `state`, `detail`,
`link_connected`, `last_controller_rx_age_s`. ROS's `diagnostic_msgs`
carries a **level**: `OK` / `WARN` / `ERROR` / `STALE`. Without it, a
supervisor cannot distinguish "running, degraded" from "running, fine" —
a node dropping 40% of frames reports exactly what a healthy one does.
*Fix:* add `level: str = "OK"` to `NodeHealth`. Additive, no breakage.

**Gap 2b — no aggregation.** ROS's `diagnostic_aggregator` rolls
per-node diagnostics into a system view with a single top-level verdict.
JaegerOS has `HealthCache` but no rollup, so "is the robot healthy?" has
no single answer. *Fix:* a supervisor-side aggregator publishing
`/sense/system_health` with the worst level and the reason.

**Gap 2c — health is a pull, telemetry has no home.** `health()` returns
an opaque dict a supervisor may forward. Anything a *host* wants to
monitor continuously — framerate, drops, decode time — has nowhere to go.
JaegerAnimation hit this immediately and the fix was
`/act/display/stats`, a module-owned telemetry topic separate from
its pixel stream. **That pattern should be the convention:** a module
publishes its own telemetry topic; health stays liveness.

## 3. Framework provides plumbing — *below parity* ⚠

The weakest category, and the one with measurable cost.

**Gap 3a — one queue, one thread, head-of-line blocking across every
topic.** `InProcBus` runs all subscribers on a single delivery thread.
Its own docstring is honest about it: *"a blocking subscriber will
back-pressure the entire Bus."*

Measured: a subscriber taking 50 ms on `/act/display/state` delayed
an **unrelated** message on `/act/speech/spoken` by **541 ms**.

That is not a corner case. It means one slow renderer stalls e-stop
delivery. ROS 2 solves it with executors and callback groups —
single-threaded by default, multi-threaded when you ask, with explicit
mutual-exclusion groups.

*Fix, in ascending order:* (i) a thread pool for delivery, (ii)
per-subscriber queues so a slow consumer only starves itself, (iii)
callback groups so the operator declares what may run concurrently.
**(ii) is the highest value-per-line change in this document.**

**Gap 3b — no QoS.** Every topic gets identical best-effort treatment.
A 3.6 MB video frame and a 200-byte e-stop share one queue at one
priority. A dropped frame is fine; a dropped e-stop is not, and the bus
cannot tell them apart. On overflow `publish()` *raises*, where ROS drops
per the topic's declared policy. Already `FRAMEWORK_GAPS.md` #3; this
review confirms it with the frame sizes that make it concrete.
*Fix:* per-topic `reliability` + `depth` in the contract, honoured by the
bus.

**Gap 3c — cross-process frames pay full serialization.** In-process
publishing passes **references** — no copy, effectively free (a good
design nobody should change). The cost lands at the process boundary:

| Geometry | Per frame | Encode | Decode | At 30 fps |
|---|---|---|---|---|
| 64×64 (LED matrix) | 16 KB | 0.00 ms | 0.01 ms | 0.5 MB/s |
| 480×320 (desktop face) | 600 KB | 0.01 ms | 0.01 ms | 17.6 MB/s |
| 1280×720 | 3.6 MB | 0.14 ms | 0.11 ms | 105 MB/s |

105 MB/s through msgpack for one 720p stream is where a multi-camera or
multi-face system falls over. ROS 2 has loaned messages and shared-memory
transport (iceoryx) for exactly this. *Fix (cheap):* let the codec pass
large `bytes` payloads out-of-band rather than inside the msgpack body.
*Fix (real):* shared-memory transport for same-host, cross-process
frames. Only worth building when a second process actually needs frames —
JP01 renders centrally, so this is not urgent, but it is the ceiling.

**Gap 3d — no intra-process composition.** ROS 2 lets you load several
nodes into one process specifically to get zero-copy between them.
JaegerOS's `fused` mode achieves the same thing by default and is
arguably ahead here — worth noting as a *strength*, not a gap.

## 4. App wires it together — *partial*

**At parity:** `jaeger.toml` is a launch file: declares nodes, tiers,
backends, restart policy, enablement, surfaces. `slot=` binding is
genuinely better than ROS launch — swapping a TTS engine means installing
a different package, with **zero manifest edits**. ROS has no equivalent;
you would edit the launch file.

**Gap 4a — no remapping / namespaces** (the manifest half of 1c).
Confirmed absent: zero occurrences in `manifest.py`. This is what blocks
running two instances of one module cleanly.

**Gap 4b — no conditionals or substitutions.** ROS launch has
`IfCondition`, `LaunchConfiguration`, argument passing, includes.
JaegerOS's answer is "a different shape is a different manifest" —
defensible, and it avoids launch-file spaghetti, but it means
`jaeger.toml` and `jaeger.windowed.toml` duplicate everything that is
common between them. *Fix:* manifest includes/inheritance — one base,
thin overlays. Not conditionals; just composition.

**Gap 4c — no lifecycle transitions in the manifest.** Nodes have a
four-phase lifecycle, but the manifest can only say `enabled`. ROS 2
launch can drive configure → activate. *Fix:* `initial_state = "configured"`
so a node can be loaded-but-inactive — the shape a hot-standby or
operator-armed node needs.

## 5. App holds project-unique code — *at parity*

The workspace/project tier matches a ROS application package. No gap
found. `Jaeger-Template`'s `workspace/` shape is if anything more
prescriptive than ROS's, which is a virtue for a young ecosystem.

## 6. Agentic I/O — *beyond ROS, and the point*

ROS has no equivalent of `tools:`. Services and actions are the closest
analogue, but they exist for other *nodes*, not for a model.

The operator's framing (2026-07-25) is the design intent worth writing
down: **a module exposes two audiences over one capability.** The general
I/O — topics — serves any consumer, exactly as ROS would. The `tools:`
declaration serves an *agent*, and can be shaped for what a model is good
at: coarse-grained, named, described, permission-tiered, with results
phrased for a language model rather than a control loop.

You might use JaegerKokoroTTS from a plain Python project and drive
`/act/speech` directly. An agent instead calls `text_to_speech`, and
gets an interface designed for it. Same engine, two pipelines.

This is not ROS parity and should never be measured against it. It is
the ecosystem's own contribution, and how it evolves is an open question
the roadmap should own rather than settle now.

**This convention already shipped — it is not a proposal.** Both 0.9
engine modules declare all three surfaces, and `module.yaml.example`
documents the pattern:

| Module | topics | tools | config |
|---|---|---|---|
| `kokoro_tts` | `/act/speech`, `/act/speech/stop` → `/act/speech/spoken`, `/act/speech/chunk` | `text_to_speech` | `kokoro_tts` |
| `whisper_stt` | → `/sense/stt/transcript`, `/sense/stt/speech_start` | `listen` | `whisper_stt` |

JaegerAnimation shipped with `tools: []` and no `config:`, which broke a
convention that already existed rather than exposing a gap in it. The
reasoning was that driving a face means knowing what "happy" maps to —
but that conflated the *mechanism* (`play_animation(asset, adapter)`,
persona-free, same vocabulary already on the bus) with the *policy*
(`set_avatar_state(emotion)`, which needs a character's emotion→asset
table). Only the second belongs to the consumer. Corrected in the module.

The one genuinely new part is **telemetry**: neither sibling publishes a
stats topic, because neither is a continuous-rate producer. An engine
emitting 30 frames/second needs a way to report whether it is keeping up,
and `/act/display/stats` is the first instance. Worth generalizing
into the convention as modules get rate-sensitive, not before.

---

## Prior art — Mochi 3.0 already solved three of these

Reviewed 2026-07-26 (`Mochi/archive/mochi-3.0/`, and
`Mochi/dev/docs/20260726_mochi_3.0_review.md`). A standalone node-based
animation middleware whose entire core is **997 lines**. It is not a
better framework than JaegerOS — no slots, a hardcoded plugin registry,
schemaless byte-prefixed topics — but it shipped three things this
review lists as gaps, and shipped them cheaply:

- **Node META announcement** (gap 1b, ranked #2 here). Every node
  publishes `{"schema": "mochi.node.meta.v1", "node_id", "required_topics",
  "optional_topics", "addresses"}` at startup. That IS the bus catalog.
  It cost ~10 lines because every node already knows its own topics.
- **Telemetry in the node BASE** (gap 2c). `fps_target`, `memory_mb`,
  `tx_rate_mbps`, `sequence` — every node, automatically. JaegerAnimation
  hand-built `/act/display/stats` for one module; the base class is
  the right home, and it generalizes to every rate-producing node.
- **Schema-versioned health/meta payloads** (gap 2a's neighbour), so a
  consumer can refuse a payload it does not understand.

The lesson is that 1b and 2c are cheaper than their rank suggests: the
information already exists inside each node, and only needs a declared
shape to leave on.

## Ranked improvements

| Rank | Change | Status |
|---|---|---|
| 1 | Per-subscriber queues | ✅ `469a85a` — **534 ms → 0.1 ms** |
| 2 | Bus catalog + external query | ✅ `b9b3d5c` + `a73c777` |
| 3 | Topic remapping | ✅ `06c69d0` + `40b091f` — solved WITHOUT the wire change, see below |
| 4 | `level` on `NodeHealth` + aggregator | ✅ `7c237ef` |
| 5 | Per-topic QoS | ✅ `92cd519` |
| 6 | Module telemetry convention | ✅ `7c237ef` — landed BETTER than proposed: in the `Node` base, so every node gets it rather than each module reinventing it |
| 7 | Manifest includes/inheritance | ⬜ open — convenience |
| 8 | Out-of-band bytes in the codec | ⬜ open — only matters when a 2nd process needs frames |

Five of eight, including every one ranked high-value. Also shipped and
not on the original list: the `[bus] backend` wiring (`c3d7a05`), which
made `backend = "subprocess"` reachable at all and fixed a zmq shutdown
deadlock.

---

## Gap 3 — why remapping is not a small change

Investigated 2026-07-26 and **deliberately not built**: it is a wire
change, and the wire is the one thing with a downstream consumer that
pins it.

In ROS the topic NAME and the message TYPE are separate, which is what
makes `-r /old:=/new` cheap. Here they are **fused**:

```python
# zmq_bus.publish — frame 0 of the wire IS msg.topic
self._pub.send_multipart([msg.topic.encode("utf-8"), wire])

# and the receive side picks the class BY that name
msg = decode(payload, topic)
```

`msg.topic` is a pinned `Literal`, so it cannot honestly say anything
else. Publishing under a remapped name therefore breaks decoding —
verified:

```
decode under its real topic : DisplayFrame
decode under a remapped name: KeyError: '/sense/face_matrix_frame'
```

Three ways out, none of them small:

1. **Carry the type separately** — three wire frames
   (`[routing_name, type_name, payload]`) instead of two. Clean, and
   what ROS effectively does. But it is a wire-format change, and
   JP01's VCC01 **vendors** the wire contract with a drift-hash test;
   this breaks that on both sides at once.
2. **In-process remapping only.** Small and would serve the two-display
   case today, since both instances share a process. Rejected as a
   trap: it would work until someone set `backend = "subprocess"`, then
   fail in a way that looks like a bus bug.
3. **Register remapped names in the contract.** Defeats the point —
   remapping exists precisely so an app can name topics the contract
   never anticipated.

**Recommendation: option 1, at a wire-version bump, coordinated with
JP01.** Not urgent: nothing today runs two instances of one module. The
documented two-display case in JaegerAnimation's design is the trigger,
and it can be met in-process meanwhile by two node instances publishing
to two already-declared topics.

Until then, `node_id` on the envelope distinguishes instances. A
subscriber must receive and discard, which is the waste this gap
describes — real, and cheaper than a premature wire change.

### Resolution — the analysis above asked the wrong question

Built 2026-07-26 as `06c69d0` (grammar) + `40b091f` (migration), and
**no wire change was needed**. Three frames were never required, the
drift-hash test never broke, and JP01 needed no coordination.

The mistake was equating the NEED with ROS's *mechanism*. What was
actually wanted is "two instances of one module, without collision."
ROS meets that with arbitrary rename (`-r /old:=/new`), which genuinely
does require the name and the type to travel separately. But arbitrary
rename is a much stronger property than the need, and it was the only
part that forced the wire change.

A hierarchy with a canonicalization rule meets the real need inside the
existing two frames:

```
/act/display/face0/frame  ─┐
/act/display/media0/frame ─┼─▶ canonical: /act/display/frame ─▶ DisplayFrame
/act/display/matrix7/frame ┘
```

`msg.topic` still names the routing key AND still resolves the type —
fusion intact, so frame 0 is unchanged. What changed is that resolution
now *drops the instance segment first*, so an instance id can be runtime
data the contract has never seen. One registration serves every
instance, forever.

The `Literal` pin on `msg.topic` did have to go — it cannot express
"this value or any instance of it." That validation moved to
`codec.decode`, comparing canonical forms, and came out strictly
stronger: it still refuses a payload whose topic belongs to another
class, and now permits instances.

**Still not supported:** arbitrary remapping — pointing a subscriber at
a name with no relationship to the contract. That remains a wire change
(option 1) and remains unbuilt, because nothing needs it. The
two-display case, which was the only cited trigger, is now served.

**Cost, paid:** every module repo's `module.yaml` names flat topics and
must be migrated when its `jaeger-os` pin is bumped. See the migration
ledger below.

---

## Migration ledger — who is on which contract

The framework migrated on branch `0.9.0`. Nothing else has, and how
each repo pins `jaeger-os` decides whether that matters.

| Repo | Pin | State |
|---|---|---|
| JaegerOS | — | ✅ migrated, 389 passing |
| JaegerAnimation | `jaeger-os@0.9.0` (tag) | ✅ migrated, 106 passing |
| JaegerAI | `jaeger-os@0.9.0` (tag) | ⬜ flat names, insulated by the tag |
| JaegerKokoroTTS | `jaeger-os@0.9.0` (tag) | ⬜ flat names, insulated by the tag |
| JaegerWhisperSTT | `jaeger-os@0.9.0` (tag) | ⬜ flat names, insulated by the tag |
| JP01_Firmware | **`-e ../JaegerOS`** (editable) | ⚠ tracks this branch LIVE |

The tag-pinned repos are not stale and not broken — they target the
pinned contract and keep working until someone bumps the pin
deliberately. That is the migration being schedulable rather than
accidental.

JP01 is the exception, and it surfaced a real defect.

### JP01-CC01 duplicates the e-stop topic

`controllers/JP01-CC01/core/topics.py` declares its own
`ACT_ESTOP = "/act/estop"` and its own `EStop` message, rather than
importing them from `jaeger_os.contract`. Both copies read `/act/estop`
before this migration, so the duplication was invisible.

Now the framework's `EStopLatch` subscribes to `/act/estop/trigger`
while CC01 publishes on `/act/estop`, and **the latch never fires** —
3 failures in `tests/test_estop.py` and `tests/test_node_formation.py`
(236 still pass).

This is CONVENTIONS law 1 — two copies of one truth — on the safety
path. The rename did not cause it; it revealed it.

Two fixes, in preference order:

1. **CC01 imports the framework's e-stop** (`ACT_ESTOP_TRIGGER` and
   `EStop` from `jaeger_os.contract.topics`), deleting its local copies.
   This is exactly the contract-adoption swap JP01 4.0 P1 already
   performs for `contract.ports` and `contract.wire`, extended to
   `contract.topics`. Removes the failure class permanently.
2. **One-line resync** — `ACT_ESTOP = "/act/estop/trigger"` in CC01's
   `core/topics.py`. Restores green immediately; leaves the duplication,
   so the next contract change desyncs it again.

Owner: JP01 4.0. Not applied here — it is a safety-path change on
another branch.
