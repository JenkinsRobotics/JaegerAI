# JROS Hardware Integration — Planning Brief

> **Audience:** an LLM-driven planning agent.
> **Read this cold.** No prior context required. Source-of-truth quotes from
> the operator are reproduced verbatim in §2 so you do not have to infer intent.
>
> **Output:** a single design document — see §11 ("Output Spec").
> **Do not write production code.** Frameworks, class sketches, schemas, and
> diagrams are fine inside the design document. No edits to JROS source.
> No edits to JP01_Firmware source.
>
> **Sibling document:** [`JROS_DAEMON_ARCH_BRIEF.md`](./JROS_DAEMON_ARCH_BRIEF.md)
> covers the Tier 1–4 daemon split for the JROS process model. **This brief is
> narrower** — it covers Tier 3 (hardware nodes) specifically: how JROS reaches
> down to physical hardware, and how a robot platform (starting with JP01)
> declares its hardware to JROS.

---

## 1. Mission

JROS (**Jaeger Robotic Operating System**) has been built so far as a software
agent — LLM core, tool-use, voice IO, animation, conversational state. It runs
entirely in software today.

JROS is the OS for **Jaeger** robots. The first Jaeger is **JP01** — a
humanoid prototype whose central computer (**JP01-CC01**) currently exists as
a standalone Qt + ZMQ + serial application in a separate repo
(`JP01_Firmware`). It coordinates three subordinate microcontrollers /
SBC's: **JP01-AVC01** (audio/video, Arduino), **JP01-MC01** (motion, Arduino),
**JP01-VCC01** (vision/camera, Jetson).

**The convergence:** JROS becomes the production software running on
JP01-CC01. The agent that today moves a desktop avatar and speaks through
speakers must, in the JP01 deployment, drive servos, read IMUs, send LED
frames, ingest camera streams — through the existing JP01 hardware stack
**plus future Jaeger platforms** (other humanoids, cars, drones) which will
have *different* hardware but should integrate with JROS through *the same
abstraction*.

Your job:

> **Design the JROS hardware-integration framework — the abstract layer
> through which JROS reaches physical hardware — and the JP01 hardware
> package as its first concrete implementation. Specify (do not implement
> today) how JP01-CC01 would be re-shaped to live inside that framework when
> the time comes.**

Implementation happens on a separate turn, gated on operator approval of your
plan (§12).

---

## 2. Operator Statements (verbatim)

These are not paraphrased. The framing in your output should respect them.

> "jaeger os  (jros) is currenlty the agentic agent we have been planing... it
> now time to better demonstrait and plan out how the hardware side of this
> progect will work ... up to this part we developed an agentic agent.. with
> the ability to use software tools and have ways to interact with a user.....
> now how to we movve this agentic agent to the hardware level...."

> "we will be using Jros for any and all autonoumas system and robotics... the
> first being humanoid robots, cars, drones, etc...."

> "how is the hardware layer integrated to Jros stack to support this... here
> is JP01firmware.. it consist of a central computer primary code and sub
> devices that focus on specific hardware.... how should we design JROS to be
> able to accept this level of hardware integration...."

> "how should we adjust JP01-cc01 to follow a format for JROS.... we are not
> directly changing JP01-cc01 to jros today but want to identify the plan on
> how JROS would run and connect to the hardware of JP01-cc01 then we will
> write that framework now to the library...."

> "i would imagine we want a hardware package for Jaegers - JP01 (future
> jaegers would have different hardware options but i would imagine a unified
> consistent integration framework to JROS)"

> "JP01 is the robot that JROS is designed for ... it is the first humanoid
> robot... Jaeger prototype unit 01.... JP01 code has been hardware focused...
> JROS has been up to this point agentic ai focused but eventually we need it
> to connect to actual hardware, motors, actuators, sensors, etc that is what
> JP01-cc01 is... jaeger prototype 01 central computer...."

> "hardware nodes might be turned on, off, restarted, etc similar to mochi"
> (prior turn — Mochi's plugin lifecycle is the reference for hardware node
> lifecycle).

---

## 3. Where This Brief Fits

```
                       JROS_DAEMON_ARCH_BRIEF.md         ← whole-system Tier 1-4
                       (operator daemon, agent loop,            split, daemon model
                        windows, identity, IPC)                 approved separately

                                    │
                                    │  Tier 3 = hardware nodes
                                    ▼
                       JROS_HARDWARE_INTEGRATION_BRIEF.md    ← THIS DOC
                       (hardware framework, JP01 package,    Tier 3 internals only,
                        alignment plan for JP01-CC01)        framework + package shape
```

The daemon-arch plan decides **how Tier 3 boots, dies, gets restarted, and
how it talks to Tier 1**. Your plan decides **what lives inside Tier 3** —
the abstractions, the per-robot package format, the device drivers, the wire
protocols, the capability surface exposed back up.

**You are not redesigning the daemon-arch.** Your plan must be compatible
with whatever the daemon-arch plan produces (PUSH/PULL ZMQ, file-socket,
named pipes, whatever — assume a generic request/response + telemetry stream
between Tier 1 and Tier 3 and design your APIs against that abstraction).
Read `JROS_DAEMON_ARCH_BRIEF.md` for context but treat its specifics as
assumptions you can rely on, not as constraints to redesign.

---

## 4. Background — JROS Today

**Repo:** `/Users/jonathanjenkins/GITHUB/JROS`

**What exists today (software-only agent):**

| Subsystem        | Location                                | What it does |
|------------------|------------------------------------------|---|
| Agent loop       | `jaeger_os/agent/`                       | LLM core, format → call → parse → dispatch |
| Tools            | `jaeger_os/tools/`                       | Software tools the agent invokes (memory, file edit, etc.) |
| Voice            | `jaeger_os/voice/`                       | STT + TTS + barge-in (PySide / sounddevice) |
| Animation        | `jaeger_os/animation/`                   | Avatar / mascot renderer (PySide widget) |
| Transport        | `jaeger_os/transport/`                   | Internal message bus (in-process today) |
| Operator surface | TUI, tray app, voice window, GUI window  | Multiple ways the operator interacts |
| Daemon attach    | `--attach` flags on tray / voice / msg   | Recent experimental work toward multi-process |
| Identity / state | Lives in the agent loop, single-process  | Conversation, memory, persona |

**What does NOT exist today:**

- Any concept of physical hardware
- Any node that runs in a separate process for lifecycle isolation (the
  `--attach` flag is the very first step toward this — see daemon-arch brief)
- Any way to declare "this robot has these joints / these sensors / these IO
  channels"
- Any device driver, serial protocol, or ZMQ-to-microcontroller bridge

You are designing the missing layer.

**Standing patterns to respect:**

- JROS uses `agent / nodes / transport / core` as its top-level naming.
  Hardware integration should fit naturally inside that vocabulary.
- Voice and animation are precedent for "subsystem with its own dir + entry
  point + lifecycle". Follow the same shape for hardware.
- The repo has memory + standing-rule documents under `docs/`. Use that
  format — markdown, headed sections, file-path links, no marketing voice.

---

## 5. Background — JP01 Today (the robot)

**Repo:** `/Users/jonathanjenkins/GITHUB/JP01_Firmware`
**Branch:** `2.0` (just created from `main`, 2026-06-12).

**Physical / logical architecture:**

```
                 ┌─────────────────────────────────────────────┐
                 │  JP01-CC01  — Central Computer              │
                 │  Mac / RPi / Jetson-class                   │
                 │  PySide6 Qt dashboard + plugin manager      │
                 │  Currently:  Jaeger Control Panel app       │
                 │  Talks down to all three sub-controllers    │
                 └──────────┬───────────┬───────────┬──────────┘
                            │           │           │
                  serial @  │   serial @│           │  ZMQ over network
                  115200    │   115200  │           │  (high bandwidth)
                            ▼           ▼           ▼
                 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                 │  JP01-AVC01  │  │  JP01-MC01   │  │  JP01-VCC01  │
                 │  Arduino     │  │  Arduino     │  │  Jetson      │
                 │  (Teensy/    │  │  (Teensy/    │  │  Python      │
                 │   ESP32)     │  │   ESP32)     │  │  main.py     │
                 │              │  │              │  │              │
                 │ LedMatrix    │  │ DockyMotor   │  │ Camera       │
                 │ NeoPixel     │  │ DockyServo   │  │ YOLO, etc.   │
                 └──────────────┘  └──────────────┘  └──────────────┘

                     "soft"           "hard"           "stream"
                     hardware         hardware         hardware
                  (LEDs / pixels)   (motors / IMU)   (video frames)
```

**Three different IPC choices, deliberate:**

| Link            | Protocol  | Why |
|-----------------|-----------|---|
| CC01 ↔ AVC01    | serial    | low-bandwidth, low-latency, simple Arduino firmware |
| CC01 ↔ MC01     | serial    | same — motor / servo command rate fits in 115200 baud |
| CC01 ↔ VCC01    | ZMQ       | high-bandwidth video frames + structured detections need network IPC |

Your framework must accommodate **all three** transport flavors per robot
package. JP01 happens to need serial + ZMQ; a future drone might need CAN +
USB-HID + UART. Make transport pluggable.

---

## 6. JP01-CC01 — Patterns to Study (file paths)

Read these files. They are the working reference for what hardware
coordination looks like today.

| File                                                                          | What it tells you |
|-------------------------------------------------------------------------------|---|
| `controllers/JP01-CC01/main.py`                                               | Entry point — instantiates managers, builds Qt tabs, ZMQ + serial bring-up |
| `controllers/JP01-CC01/config.json`                                           | Declares `enabled_plugins` — `Core.MotionControl`, `Core.AudioVideoControl`, `Advanced.AIProcessing` |
| `controllers/JP01-CC01/plugins/Core/main_controller.py`                       | Cognitive coordinator — orchestrates the subsystem managers |
| `controllers/JP01-CC01/plugins/Core/motion_control.py`                        | Subsystem manager for motors / servos — talks to MC01 over serial |
| `controllers/JP01-CC01/plugins/Core/audio_video_controls.py`                  | Subsystem manager for LEDs + audio — talks to AVC01 over serial |
| `controllers/JP01-CC01/plugins/Core/vision_control.py`                        | Subsystem manager for camera + vision — talks to VCC01 over ZMQ |
| `controllers/JP01-CC01/plugins/Core/serial_handler.py`                        | Lifecycle abstraction — `connect / disconnect / is_connected / monitor / log` |
| `controllers/JP01-CC01/plugins/Core/zmq_client.py`                            | ZMQ-side abstraction |
| `controllers/JP01-CC01/plugins/Core/speech_to_text.py`                        | Vosk-based STT (subagent-flavored ML worker) |
| `controllers/JP01-CC01/plugins/Core/text_to_speech.py`                        | OpenVoice-based TTS |
| `controllers/JP01-CC01/devices/neopixel.py`                                   | Tiny command builder — `MN[1]`, `FN[wrgb...]` |
| `controllers/JP01-CC01/devices/led_matrix.py`                                 | Tiny command builder — `MM[1]`, `BM[128]`, `FM[rgb...]` |
| `controllers/JP01-CC01/tabs/`                                                 | Qt UI surface — `motion_tab`, `vision_tab`, `av_tab`, `audio_tab`, `system_tab` |
| `controllers/JP01-AVC01/JP01-AVC01.ino`                                       | Arduino firmware actually running on AVC01 |
| `controllers/JP01-AVC01/NeoPixelHandler.h` / `LedMatrixHandler.h`             | Firmware-side handler classes (mirror of CC01's command builders) |
| `controllers/JP01-MC01/JP01-MC01.ino`                                         | Arduino firmware actually running on MC01 |
| `controllers/JP01-MC01/DockyMotor.h` / `DockyServo.h`                         | Firmware-side motor / servo control classes |
| `controllers/JP01-VCC01/main.py`                                              | Jetson-side Python — vision pipeline, ZMQ publisher |

**Five patterns to lift into the JROS framework (do not reinvent):**

1. **Plugin enable / disable via config file.** `config.json` declares which
   subsystems start. JROS Tier 3 should declare which hardware nodes start
   the same way, per robot package.

2. **Compact ASCII command protocol over serial.** `MN[1]` = NeoPixel
   Mode 1. `FN[wrgb…]` = NeoPixel Frame. `MM`, `BM`, `FM` for matrix. The
   protocol is human-readable, debuggable in a serial monitor, and trivial
   to parse on both sides. JROS framework should support this style as a
   first-class option (alongside binary protocols for high-rate streams).

3. **Tiny device builders.** `devices/neopixel.py` is ~20 lines of pure
   command builders. No state, no IO. Easy to test, easy to share between
   the host-side node and any tools / dashboards. JROS framework should
   encourage device modules that small.

4. **Lifecycle on `SerialHandler`.** `connect / disconnect / is_connected /
   monitor`. This is exactly the lifecycle a hardware node needs: start,
   stop, restart, health-check, telemetry. Mirror this on the JROS
   `HardwareNode` base.

5. **Transport choice is per-link, not global.** CC01 uses serial for
   Arduino sub-controllers and ZMQ for the Jetson. Don't force a single
   transport. Let each hardware node declare its transport.

---

## 6.5 The Animation Node — Your In-Tree Tier-3 Reference

**Read this section after §6.** This is the most important section for
calibrating what your framework should look like.

Operator framing (2026-06-12): **Mochi is "hardware light."** The animation
node is not an analogy for a hardware node — it is **the same problem**:
render frames to a surface at a tick rate, with lifecycle, crash isolation,
and health reporting. The only things that distinguish it from a JP01
LED-matrix hardware node are:

1. **The wire** — a screen surface instead of a serial cable to a NeoPixel
   ring. (Transport × Protocol.)
2. **The safety contract** — screens can't hurt anyone, so e-stop reduces to
   "stop rendering." Motors can; e-stop is real.
3. **Simulation mode** — N/A, because the animation node *is* the
   simulation, in a sense.

Everything else — lifecycle (start / stop / restart / health), capabilities
becoming agent-callable tools, telemetry, supervisor semantics — is shared.

**Practical implication for your plan:** when the framework lands, the
animation node should be the **first thing migrated onto it.** It exercises
the full Tier-3 contract with zero physical risk. Validates the design
before a single servo moves. (LEDs-before-motors, taken one step earlier.)

Your plan should reflect this in §4 (alignment plan) and §5
(future-Jaeger interface) — note the animation node as a migration target
and a contract-validation case, not just JP01-CC01.

**JROS files to study as the working Tier-3 reference:**

| File                                                                 | What it tells you |
|----------------------------------------------------------------------|---|
| `jaeger_os/animation/` (whole subsystem)                             | The closest thing JROS has today to a "node with a lifecycle, a renderer, a tick rate, and a capability surface". Pattern-match against your `HardwareNode` contract. |
| `jaeger_os/animation/` entry point + any supervisor / lifecycle code | What "start / stop / restart" looks like in JROS terms today. |
| The animation node's tool-registration surface                       | How a node's capabilities become agent-callable tools — this is the precedent your `HardwarePackage` capability surface should match. |
| Telemetry / event emission from animation                            | Pattern for how Tier 3 reports state up to Tier 1. |

Don't redesign from scratch what the animation node already does well.
**Find what it does, name those primitives in your `HardwareNode` contract,
and the migration becomes "the animation node already implements
HardwareNode; here's the rename pass."**

The convergence case worth keeping in mind: "**Lilith's face on a chest LED
matrix**" is the same animation node pointed at a different surface. If the
contract is designed right, this is a transport swap, not a rewrite.
Bandwidth budget for streaming animation frames to a hardware LED matrix is
a risk worth flagging in §9 (risks) of your output.

---

## 7. Sub-Controllers — What They Are

Brief, so you don't have to dig:

| Controller | Hardware class | Firmware language | Talks to CC01 via | What it owns |
|------------|----------------|-------------------|-------------------|---|
| AVC01      | Arduino MCU    | C++ (`.ino`)      | Serial @ 115200   | LED matrix, NeoPixel rings |
| MC01       | Arduino MCU    | C++ (`.ino`)      | Serial @ 115200   | DC motors, servos |
| VCC01      | Jetson SBC     | Python            | ZMQ over network  | Camera streams, vision inference |

**Two distinct kinds of "hardware node" from JROS's perspective:**

- **Firmware-backed nodes** (AVC01, MC01): JROS speaks to them through a
  host-side proxy that knows the wire protocol. The firmware itself is not
  Python and is updated through a separate flash process.
- **Host-side hardware nodes** (VCC01): JROS speaks to them as a peer Python
  process over network IPC. They may themselves talk to lower-level
  hardware drivers (CSI camera, GPU inference).

Your framework should make this distinction explicit. The JROS-facing
abstraction can be the same; the *implementation* under the hood will
differ.

---

## 8. The Design Question

> **What does the JROS hardware integration framework look like?**

Concretely, you must design:

**A. The framework layer (`jaeger_os/hardware/` or similar — pick the name).**

- The `HardwareNode` base class / protocol. What lifecycle methods? What
  capability declaration? What telemetry shape?
- The `HardwarePackage` concept. A package describes a robot's hardware
  topology. How is it declared? (yaml? Python class? json schema?)
- The transport abstraction. How does a node declare its transport (serial
  / ZMQ / CAN / USB-HID / custom)? How is the transport itself plugged in?
- The capability surface. How does Tier 1 (the agent) discover what a robot
  can DO? Names like `move_arm`, `set_led_frame`, `read_imu`. Where do these
  live? (declared on the node? declared in the package? both?)
- The command / telemetry contract. How does a tool call from the agent
  become a wire-format command on the right transport? How does sensor data
  bubble up?

**B. The JP01 hardware package — the first concrete instance.**

- Directory layout for `jaeger_os/hardware/jp01/` (or
  `hardware_packages/jp01/`, pick the convention).
- Per-controller node modules (`cc01.py`, `avc01.py`, `mc01.py`,
  `vcc01.py`).
- Per-device modules (lift / port the patterns from
  `JP01-CC01/devices/neopixel.py`, `led_matrix.py`).
- Topology declaration file. What ports, what baud, what ZMQ endpoints,
  what capabilities exposed.
- Capabilities the JP01 package exposes to the JROS agent (the operator's
  list will grow — start with: LED frame write, motor command, servo angle,
  IMU read (if MC01 has one — check), camera frame subscribe, vision
  detection subscribe, TTS speak, STT listen).

**C. The JP01-CC01 alignment plan (NOT EXECUTED TODAY).**

- How would the existing `JP01_Firmware/controllers/JP01-CC01/` repo be
  re-shaped to live inside the JROS framework when the convergence happens?
- Which existing files map to which framework concepts?
- What stays in `JP01_Firmware` (firmware sources, Arduino .ino, Jetson
  Python) vs what moves into JROS (the host-side coordination, the
  capability surface, the agent integration)?
- Migration sequence — what's first, what's last, what's reversible.

**D. The future-Jaeger interface.**

- Show, with a sketch (no code), how a second hardware package
  (`jaeger_os/hardware/jp_drone_01/` or similar) would slot in without
  touching the framework.
- The minimum a new package must declare. The maximum it may override.
- Where the framework draws the line between "robot-agnostic JROS code"
  and "robot-specific package code."

---

## 9. Specific Design Questions You Must Answer

Pick a position on each. Brief rationale per answer (1–3 sentences). If you
genuinely cannot decide without operator input, list the choice as an Open
Question (§10) — but try to take a position first.

1. **One process per hardware node? Or one process per controller? Or one
   process per package?** What's the right granularity for crash isolation
   vs. cost?
2. **Where does the hardware package live in the JROS repo?**
   `jaeger_os/hardware/<pkg>/` vs `hardware_packages/<pkg>/` vs
   external repo entirely (pip-installable).
3. **Topology declaration format.** YAML, JSON, Python class, TOML? Why?
4. **How does Tier 1 discover capabilities?** Static registration at boot vs.
   runtime introspection vs. both.
5. **Capability naming convention.** `motion.set_joint_angle` vs
   `set_joint_angle` vs `JP01.motion.set_joint_angle`. How does the agent
   tell which robot's capability it's calling when multiple robots are
   connected? (Not a JP01-today problem, but a JROS-future problem.)
6. **Command schema.** Free-form dict, typed via Pydantic, protobuf? What's
   the contract between Tier 1 and Tier 3?
7. **Telemetry schema.** Push (broadcast) vs pull (poll) vs both?
   Subscription model?
8. **Wire protocol abstraction.** Should the framework provide a `Protocol`
   base (with concrete `ASCIIProtocol`, `BinaryProtocol`, `ZMQProtocol`
   implementations)? Or each node carries its own protocol logic?
9. **Hot-reload / restart-without-restarting-JROS.** Operator wants Mochi-
   style on/off/restart per node. What's the lifecycle API?
10. **Health / heartbeat / failure semantics.** How does Tier 1 know
    something is wrong? What happens on transport disconnect?
11. **Simulation / mock backends.** A hardware node should have a "no
    hardware attached" mode for desktop dev. How is this declared?
12. **Where does the firmware repo (`JP01_Firmware`) end and the JROS
    package begin?** Two-repo model vs absorb-firmware-into-JROS vs
    submodule.
13. **Versioning.** A package declares it works with JROS framework version
    X. How is the compatibility expressed? What breaks?
14. **Operator-facing UI for hardware (the Qt tabs in CC01 today).** Does
    a hardware package ship its own UI surfaces? Where do they live in the
    Tier 4 model (per daemon-arch brief)?
15. **Safety / e-stop.** Motors and servos can hurt people. How does the
    framework guarantee that an e-stop signal terminates motion within X
    milliseconds, regardless of agent loop state? (This is **non-optional**
    for humanoid hardware.)

---

## 10. Open Questions to Surface

Things you'll discover in design that need operator input. Don't guess —
list them. Examples of the kind of thing that probably IS an open question:

- Real-time guarantees: does JROS Tier 1 need real-time? Or only Tier 3?
- Multiple robots simultaneously: is this a v1 concern or a future
  concern?
- ROS / ROS2 interop: should the JROS framework speak ROS topics? Or stay
  fully independent?
- License / openness of hardware packages: are third parties expected to
  write packages for their own robots?

Frame each open question as a single sentence the operator can answer
yes / no / "do X" on.

---

## 11. Output Spec

**One markdown document.** Save as
`dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md` in
`/Users/jonathanjenkins/GITHUB/JROS/`.

Structure:

```
1.  Executive summary (5–10 lines — what you designed, why)
2.  Framework overview (the abstraction)
    2.1  Module layout and naming
    2.2  HardwareNode contract (lifecycle, capabilities, telemetry)
    2.3  HardwarePackage contract (topology, capability surface)
    2.4  Transport abstraction
    2.5  Wire protocol abstraction
    2.6  Command + telemetry schemas
    2.7  Lifecycle (start / stop / restart / health)
    2.8  Safety / e-stop
3.  JP01 hardware package — the first concrete instance
    3.1  Directory layout
    3.2  Per-controller nodes (CC01 / AVC01 / MC01 / VCC01)
    3.3  Per-device modules (NeoPixel, LedMatrix, Motor, Servo, Camera, etc.)
    3.4  Topology declaration (full example)
    3.5  Capability surface exposed to the agent
4.  JP01-CC01 alignment plan (NOT EXECUTED TODAY)
    4.1  Current state → target state file map
    4.2  Migration sequence (phased, reversible)
    4.3  What stays in JP01_Firmware vs moves into JROS
5.  Future-Jaeger interface
    5.1  Hypothetical second package sketch (drone? car?)
    5.2  Minimum required, maximum overridable
6.  Position taken on §9 design questions (table — question / your choice / 1-line why)
7.  Open questions (numbered, single-sentence each)
8.  What I did NOT design (explicit non-goals)
9.  Risks + unknowns
```

**Hard rules for the output:**

- No production code in the JROS repo. Sketches, diagrams, class outlines
  inside the doc are fine.
- File paths cited in the doc must actually exist (verify before writing).
- Where you make a claim ("JROS today has X"), cite the file. Where you
  recommend a pattern ("JP01-CC01 does Y, JROS should adopt that"), cite
  the JP01_Firmware file.
- Where you cannot verify a claim, label it `[UNVERIFIED]` and move on.
  Do not invent.
- Do not promise behavior you have not designed. If safety (§9.15) is too
  big to design in this pass, say so and scope it as a separate brief.
- Keep the doc under 1200 lines. Tighter is better.

---

## 12. Standing Rules (must be honored)

These are operator standing rules, refreshed for this brief:

1. **No production code today.** Your output is a design document. JROS
   source files and JP01_Firmware source files are read-only for you.
2. **Plan + approval before implementation.** This applies to the
   hardware-integration framework just as it applies to the daemon-arch.
   The framework lands in JROS only after operator OKs your plan.
3. **No back-compat shims pre-1.0.** Design for the right answer; do not
   carry legacy CC01 conventions for "just in case." Anything kept from
   CC01 should be kept because it's the *right* design, not because it
   already exists.
4. **No convention ahead of code.** Do not invent file paths, module
   names, or class names that don't currently exist and then describe them
   as if they do. Mark proposed names clearly (`PROPOSED: jaeger_os/hardware/...`).
5. **Truthful claims.** If you cite a JROS or JP01 file, you have read it.
   If you describe current behavior, it's what the code actually does. If
   you're guessing, say so.
6. **Never push, never tag.** Local edits + commits to JROS are fine if
   operator asks; pushing remotes or applying tags requires explicit OK
   in the same turn. Default is local-only.
7. **No Claude co-author trailer on commits.** Solo authorship.
8. **Commit at milestones, not after every pass.** When you commit the
   plan doc, one commit for the whole doc.
9. **Mochi parallels are reference only, not gospel.** Mochi's plugin
   subprocess model is a reference for lifecycle. Don't copy Mochi's
   ZMQ broker design verbatim if a different design fits hardware better.
10. **Safety is non-optional for humanoid hardware.** §9.15 (e-stop) is
    required content. You may scope its full design to a separate brief
    but it must be addressed in this plan at least at the contract level.

---

## 13. How to Start

1. **Read this brief end to end first.** Especially §2 (operator quotes)
   and §11 (output spec).
2. **Read [`JROS_DAEMON_ARCH_BRIEF.md`](./JROS_DAEMON_ARCH_BRIEF.md).** You
   need to understand the daemon-arch context. Treat its Tier 1-4 model as
   a working assumption (not a constraint to redesign).
3. **Survey JROS as it is today.** Walk
   `/Users/jonathanjenkins/GITHUB/JROS/` — at minimum `jaeger_os/agent/`,
   `jaeger_os/tools/`, `jaeger_os/transport/`, the existing top-level
   directory layout. Know what already exists before you propose where
   hardware fits.
4. **Survey JP01_Firmware on branch `2.0`.** Read the files listed in §6
   above. Spend extra time on `plugins/Core/serial_handler.py`,
   `plugins/Core/main_controller.py`, `devices/neopixel.py`, and
   `controllers/JP01-CC01/config.json` — these are the patterns to absorb.
5. **Spend a pass reasoning before drafting.** Take a position on the
   structural questions (§9) before you start writing. The doc reads
   better when it's clearly an opinion, not a survey.
6. **Draft the doc.** Save to
   `/Users/jonathanjenkins/GITHUB/JROS/dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md`.
   Operator will review. Iterate as requested.
7. **Stop. Do not implement anything.** Hand back the doc.

---

## 14. Final Notes

- This is the **second** of two strategic briefs. The first (daemon-arch)
  covers the JROS process model. This one covers the hardware tier. They
  are siblings, not duplicates. Read both, design for the intersection.
- The operator has emphasized: JROS is the OS for **all** Jaeger
  autonomous systems — humanoid first, but cars and drones later. Your
  framework should not bake in humanoid-only assumptions (e.g., don't
  hardcode "arms" or "head" as first-class — let the JP01 package declare
  those).
- The operator has also emphasized: JP01-CC01 will not be edited in this
  turn. The alignment plan (§8.C) is **specification only** — what it
  would look like, not a delta to apply. Be clear in your doc that this
  section is forward-looking.
- When in doubt, design for the JP01 case first and then check that the
  abstraction generalizes. A clean JP01 solution that doesn't generalize
  is better than a generic framework that doesn't solve JP01.

End of brief.
