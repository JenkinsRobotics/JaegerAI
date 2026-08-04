# Framework gaps — deduped, from the six concept examples

> Actionable input for the 1.0 roadmap. Each gap is tagged with which
> example(s) exposed it and the tier where the fix belongs:
> **contract** (a `jaeger_os/contract/` schema/topic addition — imports
> nothing, needs cross-team sign-off per `CONVENTIONS.md`'s versioning
> rule), **framework** (a `jaeger_os` mechanism/behavior change), or
> **module** (a new module/slot convention, no framework code change
> needed). A few of these are already tracked upstream in JaegerOS's
> own roadmap docs — marked accordingly, not claimed as new discoveries.

## 1. No generalized servo/joint-motion contract

**Tier: contract.** **Exposed by:** `two_axis_turret.md`,
`six_axis_arm.md`.

JP01's `MoveJointsArgs` hardcodes its own joint-range clamps into a
JP01-specific Pydantic model. A turret project or an arm project can't
reuse it — each redefines an equivalent schema from scratch, copying
the *pattern* (named joints, angle + speed) instead of inheriting a
shared one. Two flavors of the same underlying gap:

- **Single-target joint motion** (turret): a parameterized `JointCommand`
  contract type (`joints: dict[str, float]` against a body-supplied
  range table) instead of one bespoke schema per robot.
- **Multi-waypoint timed motion** (arm): `/act/motion`'s
  velocity/single-waypoint shape doesn't generalize to a six-joint
  timed path at all — needs a new `/act/trajectory` +
  `/sense/trajectory_status` topic pair, not just a parameterized
  version of the existing one.

## 2. No spatial-sensing topic vocabulary (scan / map / pose)

**Tier: contract.** **Exposed by:** `lidar_map.md`.

`jaeger_os/contract/topics.py` has voice-shaped, motion-shaped, and
animation-shaped topics — nothing range/spatial-shaped. Three new
`msgspec.Struct` types are needed before this example is even
stubbable: `/sense/scan` (range data), `/sense/map` (SLAM output), and
a pose topic (world-frame position estimate — currently no topic, and
no coordinate-frame/transform convention at all, plays this role).

## 3. No QoS / rate-budget story on the bus

**Tier: framework.** **Exposed by:** `lidar_map.md` (sensing side),
`six_axis_arm.md` (actuation side).

`TopicMessage`'s envelope (`topic`, `topic_v`, `t_emit_ns`, `seq`,
`node_id`, `correlation_id`) declares no reliability, ordering, or
drop-under-load semantics — every topic today is implicitly "whatever
the bus backend happens to do." A raw lidar scan (high-rate, fine to
drop-and-replace) and a map (low-rate, must-not-drop) have genuinely
different delivery needs the contract can't express. A trajectory
(actuation) is meaningless without some timing guarantee relative to
its waypoint timestamps — same underlying missing piece, opposite
direction on the bus.

## 4. Hardware packages aren't `module.yaml`-discoverable

**Tier: framework.** **Exposed by:** `two_axis_turret.md`, `jp01.md`.
**Already tracked upstream** — this is Gap 1 of
`dev/docs/roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md` (JaegerOS repo),
restated here because both a hypothetical (turret) and the real body
(JP01) hit it identically: hardware packages go through the
hardware-package loader, not `discover_modules()`, so they're not
uniform with engine modules for discovery/availability/manifest
binding. `topology.yaml`'s `capabilities:` block stays the right
source of truth either way (richer than `module.yaml` `tools:` —
tiers, e-stop scope, arg schemas) — the fix is giving the package a
`module.yaml` too (slot `hardware`, multi-module slot), not replacing
`topology.yaml`.

## 5. Mind-as-module isn't built yet

**Tier: module** (extraction) **+ framework** (the slot mechanism it
would ride). **Exposed by:** `simple_chatbot.md`. **Already tracked
upstream** — `THREE_TIER_STRUCTURE.md`'s 0.9 work item 3
("mind-as-module, in-repo first"). Restated here because the chatbot
example makes the practical consequence concrete: today "a chatbot
with no voice" works only because JaegerAI is a monolithic
DISTRIBUTION where voice modules happen to be disableable — not
because the mind is a swappable MODULE the way `kokoro_tts` is. You
can't point a manifest at a *different* mind implementation the way
you can point `slot: tts` at a different TTS engine.

## 6. No workspace/safety envelope in the schema

**Tier: contract.** **Exposed by:** `six_axis_arm.md`.

`topology.yaml`'s `safety:` block today is `estop_scope` +
`firmware_watchdog_required` — which controllers stop on latch, not
what physical envelope is safe to move within. A six-axis arm's real
safety need (joint limits, a Cartesian keep-out volume,
self-collision rules) has no declarative home — today it would live
only inside a module's own code, unchecked by the framework
independently, which is exactly the "two copies of one truth" pattern
`CONVENTIONS.md` law 1 warns against.

## 7. No precedent for a mind-independent compute module (`motion_planning` slot)

**Tier: module.** **Exposed by:** `six_axis_arm.md`.

Every slot today is either a driver (`tts`, `stt`, `vision`,
`ranging`) or a thin bridge (`messaging`) — nothing today is a
nontrivial algorithmic stage (IK/trajectory planning) sitting between
a capability call and a hardware driver. Untested assumption: does the
one-factory-per-slot, config-catalog-binding model hold for a module
that's more "algorithm" than "driver"? Worth confirming before a real
`motion_planning` slot ships.

## 8. No suite-app template shape

**Tier: framework** (template, not runtime). **Exposed by:**
`simple_chatbot.md`. Already named in `CONVENTIONS.md` ("the three
repo shapes" — suite app is **(planned)**); restated here because this
exercise is the first concrete case that actually needed one and had
to hand-assemble instead of starting from a scaffold.

---

## Top-line priority (my read, not operator-ratified)

For 1.0 readiness, in rough order of how many examples each unblocks:

1. **#4 (hardware package `module.yaml`)** and **#5 (mind-as-module)**
   — both already on the 0.9 roadmap; this exercise just confirms
   they're load-bearing for more than JP01 alone.
2. **#1 (joint/trajectory contract)** — blocks both hardware examples
   (turret, arm) cold; highest-leverage NEW contract work.
3. **#3 (QoS/rate story)** — blocks lidar and arm; the least glamorous
   but most foundational gap (it's a transport-layer claim, not a
   topic list).
4. **#2 (spatial topics)** — blocks lidar specifically; scoped and
   additive once #3's rate story exists to hang it on.
5. **#6, #7, #8** — real but narrower; each blocks one example, none
   are prerequisites for the others.

## ROS-parity sweep additions (full conceptual audit, 2026-07-13)
Tier 1 — frame in the whitepaper NOW, contract-tier at/before 1.0:
- ACTIONS primitive: long-running goals w/ feedback + cancel (bus tier;
  trajectory contract is a special case). Every real robot needs cancel.
- TF / transform tree: named coordinate frames, static+dynamic transforms,
  time-aware queries (world→base→head→camera). Prereq for vision↔motion.
- Robot description (URDF analog): geometry/kinematics/joint limits beside
  topology.yaml's controllers+capabilities. Prereq for sim/viz/planning.
Tier 2 — operational muscle:
- Bag record/replay (unify JP01 blackbox + Atropos lineage → `jaeger bag`;
  doubles as Jaeger Train data capture).
- Multi-machine node discovery (or explicitly: topology-declared by design —
  the whitepaper must choose and say so).
- REAL-TIME FRAMING (doc, not code): hard real-time = MCU firmware tier;
  framework = command/supervision tier. True today; must be stated.
Partial: dynamic per-node parameter reconfigure semantics; 3D robot-state
viz (Studio's RViz-shaped job).
- TAG REGISTRY / introspection (operator, 2026-07-14): live bus catalog
  (topic→type/publisher/rate/last-value) + `jaeger topics` CLI + protocol
  catalog frames — the Grafana/FANUC bind-anything property; prereq for
  the GUI-builder Suite app. Cheap: one bus = free catalog point.
