# JROS Hardware Integration Framework — Design Plan

**Date:** 2026-06-12
**Status:** PLAN — nothing in this document is implemented. Every
path under `jaeger_os/hardware/` is `PROPOSED`. Implementation is
gated on operator approval (brief §12.2).
**Brief:** [`JROS_HARDWARE_INTEGRATION_BRIEF.md`](JROS_HARDWARE_INTEGRATION_BRIEF.md)
**Sibling:** [`JROS_DAEMON_ARCH_BRIEF.md`](JROS_DAEMON_ARCH_BRIEF.md)
(Tier 1–4 model assumed, not redesigned here)
**Repos read:** `/Users/jonathanjenkins/GITHUB/JROS` (working tree),
`/Users/jonathanjenkins/GITHUB/JP01_Firmware` (branch `2.0`,
HEAD `626c462`)

---

## 1. Executive summary

JROS already contains the *seed* of the hardware layer the brief asks
for: a `Node` base class with the exact lifecycle the operator wants
(setup / tick / teardown / health, restart signaling), generic
`motor` / `light` / `vision` nodes that subscribe to typed bus topics,
and an **adapter seam** whose docstrings already name JP01-MC01 as the
intended first implementation. This plan does not invent a parallel
hardware system — it **formalizes the adapter seam into a framework**:
a `Transport × Protocol` composition underneath the adapters, a
per-robot **HardwarePackage** (topology YAML + adapters + device
builders + capability surface) that tells JROS what a specific robot
is, and a **capability registry** that turns a package's declared
abilities into ordinary JROS agent tools with the existing permission
tiers and availability machinery. JP01 becomes the first package,
built from the protocols already running in `JP01_Firmware` (the
`MN[…]`/`MJ[…]` ASCII bracket protocol, the VCC01 ZMQ telemetry/command
sockets). Safety is addressed at the contract level with a three-layer
e-stop design whose hard guarantees live in firmware — because the
survey shows today's only "emergency stop" is an ordinary `MM[0,0,0]`
command on the ordinary queue, and that is not acceptable for a
humanoid.

---

## 2. Framework overview

### 2.0 What exists today (verified)

The plan builds on these. Citations are to files read on 2026-06-12.

| Existing piece | Path | What it gives the framework |
|---|---|---|
| Node lifecycle | `jaeger_os/nodes/base.py` (241 lines) | `setup/tick/teardown/health`, `NodeState` enum (`INIT…RUNNING…RESTARTING…FAILED`), SIGTERM = graceful stop, SIGUSR1 = request-restart, thread-or-process agnostic `run()` |
| Generic motor node | `jaeger_os/nodes/motor/node.py` | SUB `/act/motion` → `MotorAdapter`; docstring: "Per-instance hardware adapter (JP01-MC01 ESP32, etc.) plugs in via the constructor" |
| Motor adapter seam | `jaeger_os/nodes/motor/adapters.py` | `MotorAdapter` Protocol (`start/stop/send_velocity/send_waypoint`) + `SerialMotorAdapter` reference with overridable `_format_*` line builders |
| Generic light node | `jaeger_os/nodes/light/{node,adapters}.py` | Same shape — `LightAdapter` Protocol, ASCII-line reference impl |
| Generic vision node | `jaeger_os/nodes/vision/{node,adapters}.py` | Same shape — `FrameEnvelope`, adapter Protocol; docstring: "hardware integrations (JP01-VCC01 Jetson) land at INSTANCE level" |
| Typed topics | `jaeger_os/topics.py` | msgspec `TopicMessage` structs; `MotionCommand` (`/act/motion`) already documents "Brain → motor_ctrl (JP01-MC01 ESP32)" |
| Bus | `jaeger_os/transport/zmq_bus.py`, `transport/broker.py` | Real pub/sub, per-subscriber queues, slow-joiner guard, in-proc + ZMQ variants behind one `Bus` interface |
| Node boot singleton | `jaeger_os/nodes/runtime.py` | Lazy `ensure_*_node()` pattern; notes Track A.7 will add the multi-process broker variant |
| Permission tiers | `jaeger_os/core/safety/permissions.py` | `READ_ONLY / WRITE_LOCAL / EXTERNAL_EFFECT / HARDWARE / PRIVILEGED` — a HARDWARE tier already exists for exactly this |
| Tool registry + availability | `jaeger_os/agent/schemas/tool_registry.py`, `agent/tools/availability.py` | `ToolDef(side_effect=, check_fn=)` — capabilities can degrade cleanly when a node is down |
| Per-turn catalog refresh | `jaeger_os/agent/loop/jaeger_agent.py` (`_refresh_tool_catalog`) | Tools registered mid-session become dispatchable next turn — hardware capabilities can appear/disappear without agent rebuild |
| Beta gating | `ToolDef.beta` + `JAEGER_DEV_MODE` | Half-tested hardware capabilities can ship dev-only |

Corrections to the brief's "JROS today" table (§4 of the brief), so the
record is truthful: tools live at `jaeger_os/agent/tools/` (not
`jaeger_os/tools/`); voice lives at `jaeger_os/plugins/voice_loop.py`
+ `jaeger_os/plugins/whisper_stt/` + `jaeger_os/nodes/audio_session/`
(not `jaeger_os/voice/`); animation lives at
`jaeger_os/nodes/animation/` (not `jaeger_os/animation/`). The brief's
claim "any concept of physical hardware … does NOT exist" is ~80%
right but the adapter seam above is real, shipped, and is the
foundation this plan builds on.

### 2.1 Module layout and naming (PROPOSED)

```
jaeger_os/
├── hardware/                        PROPOSED — the framework
│   ├── __init__.py                  public surface pin (like agent/__init__.py)
│   ├── transport.py                 Transport ABC + SerialTransport,
│   │                                ZmqReqTransport, MockTransport
│   ├── protocol.py                  Protocol ABC + AsciiBracketProtocol,
│   │                                JsonLineProtocol, MsgpackProtocol
│   ├── link.py                      Link = Transport × Protocol composition
│   │                                (+ reconnect policy, RX reader thread)
│   ├── package.py                   HardwarePackage loader: topology.yaml →
│   │                                validated PackageSpec (msgspec schema)
│   ├── capabilities.py              capability declaration → ToolDef
│   │                                registration (umbrella tools, tiers,
│   │                                availability bound to node health)
│   ├── safety.py                    e-stop contract: EStop topic handling,
│   │                                latch state, motion-refusal helpers
│   └── packages/
│       └── jp01/                    PROPOSED — first concrete package (§3)
└── nodes/                           EXISTS — generic nodes stay here
    ├── base.py                      (unchanged — HardwareNode = Node)
    ├── motor/  light/  vision/      (unchanged contracts; adapters get
    │                                 a Link under the hood via packages)
    └── …
```

Naming positions:

- **Framework at `jaeger_os/hardware/`** — sits beside `agent /
  nodes / transport / core`, matching the repo's vocabulary rule.
- **Packages under `jaeger_os/hardware/packages/<robot>/`** — first-
  party packages in-repo (JP01 is co-developed with the framework);
  the loader reads a directory, so an external pip package exposing
  the same layout can be added later via an entry-point hook
  (`(planned)`, not designed in this pass).
- **There is no new node base class.** "HardwareNode" in the brief's
  vocabulary *is* `jaeger_os/nodes/base.Node`. Inventing a second
  lifecycle would split the world; the existing one already matches
  Mochi's on/off/restart semantics (SIGUSR1 = `RESTARTING`).

### 2.2 The node contract (lifecycle, capabilities, telemetry)

A hardware node is `nodes/base.Node` plus three framework additions
(mixin or convention — sketch, not code):

```
HardwareNode (= nodes.base.Node + hardware conventions)
│
├─ lifecycle      setup() opens its Link(s); teardown() closes them;
│                 health() embeds link state {connected, last_rx_age_s,
│                 reconnects, protocol_version}
├─ capabilities   declares NOTHING itself — capabilities live in the
│                 package topology (§2.3); the node merely SERVES the
│                 topics those capabilities map to
└─ telemetry      publishes its controller's heartbeat/telemetry as
                  typed topics (§2.6) at the rate the wire provides;
                  publishes /sense/node_health on a fixed cadence
```

Why capabilities do **not** live on the node class: the generic
`MotorNode` is robot-agnostic ("subscribe `/act/motion`, forward to
adapter"). What JP01's motors can *do* (two drive motors, two servo
joints, 40–150° limits) is robot knowledge — it belongs in the JP01
package, next to the adapter that encodes it. A future quadruped
reuses `MotorNode` unchanged with a different adapter + different
capability declaration.

### 2.3 The HardwarePackage contract

A package is a directory with one required file and three
conventional ones:

```
jaeger_os/hardware/packages/<robot>/        PROPOSED
├── topology.yaml          REQUIRED — what the robot IS (below)
├── adapters/              per-controller adapters (subclass the
│                          generic node adapters, compose a Link)
├── devices/               tiny stateless command builders
│                          (JP01: ports of JP01-CC01/devices/*.py)
└── capabilities.py        capability → topic/handler glue that
                           topology.yaml entries reference
```

**`topology.yaml` (illustrative sketch — full JP01 example in §3.4):**

```yaml
package: jp01
requires_framework: ">=0.6"        # checked at load; refuse, don't degrade
controllers:                       # physical/logical endpoints
  mc01:
    node: motor                    # which GENERIC node serves it
    adapter: jp01.adapters.mc01:Mc01MotorAdapter
    link:
      transport: serial            # serial | zmq_req | mock
      port: /dev/cu.usbserial-110
      baud: 115200
      protocol: ascii_bracket
    enabled: true
    simulated: false               # true → MockTransport, same node
capabilities:                      # what the AGENT sees (§2.6)
  - name: motion.move_joints
    controller: mc01
    tier: HARDWARE
    schema: jp01.capabilities:MoveJointsArgs
safety:
  estop_scope: [mc01]              # nodes that must honor /act/estop
```

Loader behavior (`hardware/package.py`): parse + validate against a
msgspec schema **the same week the field lands** (standing rule: no
schema without validator); refuse to load on unknown fields, missing
adapters, or framework-version mismatch — loudly, at boot, with the
file:line of the offending entry.

### 2.4 Transport abstraction

`Transport` is a byte-channel with lifecycle — deliberately the same
verbs as `JP01-CC01/plugins/Core/serial_handler.py` (`connect /
disconnect / is_connected / write / read`), which is the proven shape:

```
Transport (ABC)
  open() / close() / is_open()
  write(bytes) -> None
  read() -> bytes | None          # one frame/line; non-blocking
  descriptor() -> str             # "/dev/cu.usbserial-110 @115200"

SerialTransport(port, baud)       pyserial; line-framed
ZmqReqTransport(endpoint)         REQ/REP command channel (VCC01 :5556)
MockTransport(script|echo)        desktop dev + tests + bench
```

Per-link choice, never global (brief §5): JP01 declares serial for
MC01/AVC01 and ZMQ for VCC01 in the same topology file. A future
drone adds `CanTransport` without touching existing packages.
Telemetry *streams* (VCC01's PUB :5555/:5558, the UDP video ports)
are **not** squeezed through this ABC — high-rate streams go straight
onto the JROS bus via the node's own subscriber thread (the vision
node's `FrameEnvelope` path already models this). `Transport` is for
command/response links; streams are bus-native.

One JP01 reality the framework must hold: on branch 2.0 the **Jetson
owns the serial links** — `JP01-VCC01/core/motion_bridge.py` and
`core/av_bridge.py` run the serial watchdogs, and CC01-on-Mac relays
commands over ZMQ (`main_controller.py:_has_live_zmq()` →
`zmq_client.send_command("motion", cmd)`); direct Mac-serial is the
fallback when no ZMQ link is live. The brief's §5 diagram (CC01 owns
serial) describes the fallback, not the live topology. The framework
expresses this naturally: the *same* `Mc01MotorAdapter` composes
either `SerialTransport` (direct) or `ZmqReqTransport` (relayed),
selected in topology — the dual-path stays a configuration, not code.

### 2.5 Wire protocol abstraction

`Protocol` turns structured commands into wire frames and parses
inbound frames into events. Separate axis from Transport — JP01's
ASCII bracket protocol could ride serial *or* the ZMQ relay:

```
Protocol (ABC)
  encode(command: dict|Struct) -> bytes
  feed(raw: bytes) -> list[Event]      # stateful framing; partial-line safe

AsciiBracketProtocol     the JP01 dialect, FIRST-CLASS:
                         HEADER[payload]\n   (MN[1], MJ[90,100,10], FN[wrgb…])
                         + bare commands (CN, DC, GT, HLP)
                         + telemetry/heartbeat line parsing
JsonLineProtocol         newline-delimited JSON (VCC01 REP payloads)
MsgpackProtocol          binary, for high-rate links (planned, drone-era)
```

The ASCII bracket style is kept first-class deliberately (brief §6.2):
human-readable in a serial monitor, trivially parsed by
`Serial.readStringUntil('\n')` on the Arduino side
(`JP01-AVC01/JP01-AVC01.ino`, `JP01-MC01/JP01-MC01.ino` both parse
exactly this), and already implemented on three boards.

Device builders stay tiny and pure (brief §6.3):
`JP01-CC01/devices/neopixel.py` is two functions returning strings
(`build_neopixel_mode`, `build_neopixel_frame`); the JP01 package
ports these as-is into `packages/jp01/devices/`. Builders never touch
IO — adapters compose `builder → protocol.encode → transport.write`.

### 2.6 Command + telemetry schemas

Three explicit boundaries, each with its existing JROS idiom:

```
agent tool boundary      Pydantic (ToolDef.args_model — existing contract,
                         arg-coercion + validation already battle-tested)
        │
bus boundary             msgspec TopicMessage structs (topics.py — existing;
                         MotionCommand, Transcript, SpeechCommand precedent)
        │
wire boundary            Protocol.encode → bytes (package-owned)
```

**Commands (down):** agent tool call → typed topic publish → node
subscriber → adapter → builder → wire. `MotionCommand` on
`/act/motion` already exists (`topics.py:286`); the framework adds
the missing act topics as packages need them (`/act/lights`,
`/act/servo`), each a msgspec struct with a validator-backed schema.
Request/response capabilities (e.g. `GT` telemetry pull) use the
bus's existing `request(…, ack_topic=…)` correlation pattern
(`SpeechCommand`/`SpokenAck` precedent in `nodes/tts/node.py`).

**Telemetry (up):** push-primary. Nodes parse controller heartbeats
(AVC01/MC01 emit a status line every 30 s per their `.ino` files;
VCC01 publishes `telemetry.*` ZMQ topics at ~5 Hz) and republish as
typed bus topics (`/sense/motor_state`, `/sense/controller_health`).
Pull exists only as cached-last-value: each node's `health()` embeds
the latest telemetry snapshot, and the Tier-3 supervisor's status
surface (daemon-arch plan's HostMonitor analog) serves "current
state" queries without touching the wire. No polling protocol to the
boards beyond what their firmware already supports (`GT`).

**Capability discovery — both static and live (§9 Q4):** topology
declares the capability set (names, schemas, tiers) at load;
on node connect the adapter performs the existing JP01 handshake
(`CN` → "JP01-AVC01 Connected") plus a protocol-version query
(`(planned)` — firmware addition, see §4.3) and reports what the
board actually is. Tier 1 registers tools for declared capabilities;
a capability whose controller is absent registers anyway but its
`check_fn` (bound to node health) reports unavailable — the existing
`wire_availability_checks` pattern hides it from the model's schema
view and the tool returns a clean "controller offline" error if
called. Mid-session node recovery surfaces automatically via the
per-turn catalog refresh.

**Capability naming (§9 Q5):** fully qualified internally —
`jp01.motion.move_joints` — but the AGENT sees per-subsystem
umbrella tools: `motion(action=…)`, `lights(action=…)`,
`robot_vision(action=…)`, following the repo's umbrella precedent
(`kanban`, `memory`, `skill`) and the bench-proven rule that routing
accuracy degrades as the visible tool count grows. Single-robot
deployments (JP01 today) drop the robot prefix from tool names; if a
second robot ever connects concurrently, the registry prefixes
(`jp01_motion`, `drone_motion`) — collision behavior is specified
now, implemented when multi-robot becomes real (Open Question 2).

### 2.7 Lifecycle (start / stop / restart / health)

Owned by the daemon-arch plan's Tier-3 supervisor; this plan defines
what each node guarantees so that supervisor can be generic:

- **Config-driven enable/disable** — `enabled:` per controller in
  topology.yaml (Mochi pattern; note today's
  `JP01-CC01/config.json:enabled_plugins` is declared but *unused* —
  `main.py` hardcodes instantiation. The framework makes the config
  real, with a loader + validator, rather than repeating the
  declared-but-unwired pattern).
- **ON/OFF/RESTART** — supervisor sends SIGTERM/SIGUSR1; `Node`
  already maps these to `STOPPING`/`RESTARTING` states
  (`nodes/base.py`). On stop, adapters MUST leave hardware safe:
  lights blanked (the `LightAdapter.stop()` docstring already
  mandates this), motors stopped (`DC` already de-activates MC01 and
  its firmware neutralizes motors).
- **Health** — `/sense/node_health` heartbeat per node (cadence
  configurable, default 1 s) carrying `NodeState` + link state +
  last controller-heartbeat age. Supervisor distinguishes
  crashed (heartbeat stale, process dead) from intentionally-off
  (config disabled) from degraded (process alive, link down).
- **Graceful Tier-1 degradation** — a dead node never raises into
  the agent loop: capability tools fail closed with a typed
  `{"ok": false, "error": "mc01 offline", "retryable": true}` result
  the model can reason about (the loop's existing error-result
  contract).
- **Restart mid-turn** — in-flight `bus.request` to a restarting
  node times out → tool returns the offline error → the agent's
  existing semantic-failure backstop prevents retry-spinning.
  No pause-the-turn machinery in v1.

### 2.8 Safety / e-stop (contract level — full design is its own brief)

**Today's truth (survey, 2026-06-12):** there is **no hardware e-stop
button**; MC01/AVC01 firmware has **no watchdog**; the only "e-stop"
is `MM[0,0,0]` — an ordinary command on the ordinary serial queue
(`JP01-CC01/plugins/Core/motion_control.py:382` comments it
"Emergency stop"; `JP01-MC01/DockyMotor.h:161` prints "Emergency Stop
Executed"). The genuine passive failsafes that DO exist: MC01 clamps
motor commands to ≤2 s duration and auto-neutralizes on expiry, and
clamps servo angles to joint limits in `parseCommand`; VCC01's
bridges auto-send `DC` after 300 s of heartbeat silence. 300 seconds
is a link-hygiene timeout, not a safety system.

**Three-layer contract (the framework's position):**

| Layer | Where | Guarantee | Status |
|---|---|---|---|
| **L0 — firmware watchdog** | MC01 (and any motion firmware) | If no valid command/heartbeat within N ms (proposed 250 ms while activated), firmware AUTONOMOUSLY neutralizes all actuators. The ONLY layer that can promise a hard latency bound — it survives host crash, Python GC, cable pull. | **Absent today — required firmware work**, tracked in `JP01_Firmware` (§4.3). The existing 2 s motor-duration clamp is the embryo of this. |
| **L1 — node-local e-stop** | Each motion-capable Tier-3 node | `estop()` writes the stop command on a path that BYPASSES the normal command queue (dedicated immediate write on the open transport). Never routes through Tier 1, never waits on the agent loop. | Framework contract (`hardware/safety.py`, PROPOSED). |
| **L2 — system e-stop** | Bus topic `/act/estop` (PROPOSED) | Any publisher (hardware button node, operator UI, agent tool, supervisor) latches system e-stop; every node in `safety.estop_scope` executes L1 on receipt; the latch state is itself a topic; motion capabilities refuse (`fail closed`) while latched; un-latch is an explicit operator action, never automatic. | Framework contract. |

What the framework explicitly does **not** promise: millisecond-bound
e-stop latency through Python tiers. Honest budget statement: L2 → L1
through the bus is best-effort (~tens of ms in-process, unbounded
under GC/load); the hard bound lives at L0, which is why L0 is
non-optional before any actuator stronger than the current desk-scale
servos ships. The agent loop's state is irrelevant to all three
layers by construction — that is the design's central safety property.

---

## 3. The JP01 hardware package — first concrete instance

### 3.1 Directory layout (PROPOSED)

```
jaeger_os/hardware/packages/jp01/
├── topology.yaml
├── adapters/
│   ├── mc01.py        Mc01MotorAdapter   (extends nodes/motor SerialMotorAdapter
│   │                                       pattern; MJ/MM bracket commands)
│   ├── avc01.py       Avc01LightAdapter  (MN/FN/MM/BM/FM; CN/DC/GT handshake)
│   └── vcc01.py       Vcc01VisionAdapter (ZMQ REP :5556/:5560 commands;
│                                           SUB telemetry.* :5555/:5558;
│                                           UDP H.264 ingest → FrameEnvelope)
├── devices/
│   ├── neopixel.py    port of JP01-CC01/devices/neopixel.py (verbatim shape)
│   ├── led_matrix.py  port of JP01-CC01/devices/led_matrix.py
│   ├── motor.py       MJ/MM builders (extracted from motion_control.py's
│   │                   inline f-strings — same ~20-line pure-builder style)
│   └── servo.py
└── capabilities.py    args schemas + topic glue for §3.5
```

There is no `cc01.py` node: **CC01's coordination role IS Tier 1 +
the framework.** What `main_controller.py` does today (registry of
managers, dual-path command routing, connect/disconnect orchestration)
maps onto the package loader + Link dual-path + the Tier-3 supervisor.
CC01 the *machine* remains the host JROS runs on.

### 3.2 Per-controller nodes

No new node classes for motor/light. The package instantiates the
existing generic nodes with JP01 adapters via topology:

| Controller | Generic node (exists) | JP01 adapter (proposed) | Link |
|---|---|---|---|
| MC01 | `nodes/motor/node.py:MotorNode` | `Mc01MotorAdapter` | serial `/dev/cu.usbserial-110` @115200 OR zmq-relay via VCC01 |
| AVC01 | `nodes/light/node.py:LightNode` | `Avc01LightAdapter` | serial (Teensy USB-CDC; `main_controller.py` configures 921600, firmware declares 115200 — USB-CDC is baud-agnostic on Teensy, but topology will record the firmware value) |
| VCC01 | `nodes/vision/node.py:VisionNode` | `Vcc01VisionAdapter` | ZMQ REP :5556 (+ :5560 vision), SUB :5555/:5558, UDP :5001/:5003 video |

AVC01's audio half (USB audio / UDP audio paths in
`tabs/audio_tab.py`, `audio_udp_tab.py`) is deliberately **out of the
v1 package** — JROS already owns voice I/O through its own pipeline
(`plugins/voice_loop.py`); reconciling robot-mounted mic/speaker with
the existing voice stack is its own piece of work (Open Question 6).

### 3.3 Per-device modules

Ports of the existing builders, kept stateless and IO-free
(brief §6.3). The AVC01 frame formats are non-trivial sizes worth
recording in the builders' docstrings: `FN[…]` carries 24 LEDs ×
8 WRGB hex chars = 192 chars; `FM[…]` carries 64×64 px × 6 RGB hex =
24,576 chars per frame (from `JP01-AVC01.ino` parsing — full-matrix
streaming over 115200-baud serial is ~3.5 s/frame theoretical; the
relay path through VCC01's network link is the realistic streaming
route, which is presumably why CC01 grew the dual-path).

### 3.4 Topology declaration (full example, PROPOSED)

```yaml
package: jp01
display_name: "Jaeger Prototype 01"
requires_framework: ">=0.6"

controllers:
  mc01:
    node: motor
    adapter: jp01.adapters.mc01:Mc01MotorAdapter
    link:
      transport: serial
      port: /dev/cu.usbserial-110
      baud: 115200
      protocol: ascii_bracket
      relay:                       # optional dual-path (CC01 pattern)
        transport: zmq_req
        endpoint: tcp://192.168.2.2:5556
        target: motion             # zmq_client.send_command("motion", …)
    enabled: true
    simulated: false
    heartbeat_expect_s: 30         # firmware status-update cadence
  avc01:
    node: light
    adapter: jp01.adapters.avc01:Avc01LightAdapter
    link:
      transport: serial
      port: /dev/cu.usbmodem85938301
      baud: 115200
      protocol: ascii_bracket
      relay: {transport: zmq_req, endpoint: "tcp://192.168.2.2:5556", target: av}
    enabled: true
  vcc01:
    node: vision
    adapter: jp01.adapters.vcc01:Vcc01VisionAdapter
    link:
      transport: zmq_req
      endpoint: tcp://192.168.2.2:5556
      protocol: json_line
    streams:
      telemetry: tcp://192.168.2.2:5555
      vision_telemetry: tcp://192.168.2.2:5558
      video_udp: [5001, 5003]
    enabled: true

capabilities:
  - {name: motion.move_joints,  controller: mc01,  tier: HARDWARE,
     schema: jp01.capabilities:MoveJointsArgs}      # MJ[a1,a2,speed]
  - {name: motion.drive,        controller: mc01,  tier: HARDWARE,
     schema: jp01.capabilities:DriveArgs}           # MM[s1,s2,dur≤2]
  - {name: motion.stop,         controller: mc01,  tier: HARDWARE,
     schema: jp01.capabilities:EmptyArgs}           # MM[0,0,0] + L1 path
  - {name: lights.set_mode,     controller: avc01, tier: WRITE_LOCAL,
     schema: jp01.capabilities:LedModeArgs}         # MN[x] / MM[x]
  - {name: lights.set_frame,    controller: avc01, tier: WRITE_LOCAL,
     schema: jp01.capabilities:LedFrameArgs}        # FN[…] / FM[…] / BM[x]
  - {name: vision.subscribe,    controller: vcc01, tier: READ_ONLY,
     schema: jp01.capabilities:VisionSubArgs}       # camera/detection stream
  - {name: telemetry.read,      controller: "*",   tier: READ_ONLY,
     schema: jp01.capabilities:TelemetryArgs}       # cached GT snapshot

safety:
  estop_scope: [mc01]
  firmware_watchdog_required: true   # boot warning until MC01 ships L0
```

Note what is **absent**: no IMU capability. The survey confirmed MC01
has no IMU — feedback is servo-angle readback + motor PWM only. The
brief's suggested capability list included "IMU read (if MC01 has
one — check)"; checked, absent. It enters the topology the day the
hardware exists, not before.

### 3.5 Capability surface exposed to the agent

Three umbrella tools (plus the always-on telemetry reader), all
registered through the existing `ToolDef` machinery with
`side_effect="hardware"` (motion) and node-health-bound `check_fn`:

- `motion(action=…)` — `move_joints | drive | stop | status`. Tier
  HARDWARE → routes through the existing permission confirmation
  flow. `stop` doubles as the agent-reachable e-stop trigger (L2
  publish), but the agent is never the only path to it.
- `lights(action=…)` — `set_mode | set_frame | brightness | status`.
- `robot_vision(action=…)` — `snapshot | detections | stream_info`.
- All marked `beta=True` initially — visible only under
  `JAEGER_DEV_MODE=1` until each capability is hardware-walked
  (existing gate, built for exactly this).

---

## 4. JP01-CC01 alignment plan (NOT EXECUTED TODAY)

Forward-looking specification only. No JP01_Firmware edits are part
of this plan's implementation either.

### 4.1 Current state → target state file map

| JP01-CC01 today (verified paths) | Maps to | Notes |
|---|---|---|
| `plugins/Core/serial_handler.py` | `hardware/transport.py:SerialTransport` | Same verbs; monitor/logging becomes node-level logging + `/sense/node_health` |
| `comms/zmq_client.py` (note: brief said `plugins/Core/zmq_client.py` — actual location is `comms/`) | `hardware/transport.py:ZmqReqTransport` + VCC01 adapter streams | Qt signals → bus topics |
| `plugins/Core/main_controller.py` | package loader + Link dual-path + Tier-3 supervisor | The relay logic (`_has_live_zmq()`) becomes the `relay:` topology block |
| `plugins/Core/motion_control.py` | `packages/jp01/adapters/mc01.py` + `devices/motor.py` + `motion(…)` tool | Waypoint/jog/sequence UI logic → agent capabilities + Tier-4 panel |
| `plugins/Core/audio_video_controls.py` | `packages/jp01/adapters/avc01.py` + `devices/{neopixel,led_matrix}.py` + `lights(…)` tool | Image→matrix conversion utilities move into devices/ helpers |
| `plugins/Core/vision_control.py` | `packages/jp01/adapters/vcc01.py` | YOLO display logic stays operator-UI (Tier 4); the stream ingest is the adapter |
| `devices/neopixel.py`, `devices/led_matrix.py` | `packages/jp01/devices/` | Near-verbatim port |
| `plugins/Core/speech_to_text.py` (Vosk), `text_to_speech.py` (pyttsx3) | **retired** | JROS's whisper/Kokoro voice stack supersedes both; robot-mounted audio is Open Question 6 |
| `tabs/*.py` (Qt) | Tier-4 panels (daemon-arch plan's window model) | v1: generic node-status panel + agent tools; bespoke panels later |
| `config.json:enabled_plugins` | `topology.yaml:controllers.*.enabled` | Today it's declared-but-unread; the framework makes it real |
| `main.py` | retired as production entry; kept as standalone diagnostic app in JP01_Firmware | As read on 2.0 it references undefined names (`SpeechToTextManager`, `QTimer`, `signal`, `HEARTBEAT_INTERVAL_MS`, `self.test_system_tab`) — mid-refactor; another reason the convergence target is JROS, not a CC01 cleanup |

### 4.2 Migration sequence (phased, reversible)

1. **Framework lands in JROS** (transport/protocol/link/package/
   capabilities/safety + MockTransport tests). No JP01 hardware
   needed; fully reversible (new directory, nothing rewired).
2. **JP01 package in simulation** — topology with `simulated: true`
   everywhere; capabilities appear behind `JAEGER_DEV_MODE`; bench
   cases drive `lights`/`motion` against mocks. Reversible.
3. **AVC01 live first** (lowest risk: LEDs can't hurt anyone).
   Direct-serial link on the bench. Walk: agent sets LED modes/frames
   by voice. Reversible (unplug).
4. **VCC01 live** — telemetry + vision streams into the bus; relay
   path validated (MC01/AVC01 commands via Jetson). Reversible.
5. **MC01 live, gated on L0** — firmware watchdog ships in
   JP01_Firmware FIRST (§4.3); only then do motion capabilities leave
   beta. This is the one deliberate one-way gate in the sequence.
6. **CC01 app retirement decision** — once JROS covers daily
   operation, the Qt panel stays in JP01_Firmware as a maintenance/
   diagnostic tool (its serial monitors and jog UI remain genuinely
   useful for bring-up).

### 4.3 What stays in JP01_Firmware vs moves into JROS

**Stays (two-repo model, §9 Q12):** all firmware sources
(`JP01-AVC01.ino`, `JP01-MC01.ino`, handler headers), the Jetson-side
pipeline internals (`JP01-VCC01/` — GStreamer/encoder/bridges), flash
tooling, hardware docs (`doc/`, `docs/` payload schemas), and the
retired-but-kept CC01 diagnostic app. **Moves into JROS:** host-side
coordination, adapters, device builders, topology, capability
surface, agent integration. **The contract between repos is the wire
protocol**, versioned: a `protocol_version` field added to the
firmware handshake/telemetry (`(planned)` firmware change, alongside
the L0 watchdog) lets the JROS adapter refuse-or-warn on mismatch.
Long-term, VCC01's Python could itself become a JROS hardware node
running on the Jetson (same framework, remote bus) — that is a
daemon-arch (multi-host) question, explicitly deferred.

---

## 5. Future-Jaeger interface

### 5.1 Hypothetical second package (sketch: `jp_drone_01`)

```
jaeger_os/hardware/packages/jp_drone_01/
├── topology.yaml      controllers: fc (flight controller, transport: serial,
│                      protocol: mavlink_shim → NEW Protocol subclass),
│                      gimbal (transport: can → NEW CanTransport),
│                      cam (zmq, reuses generic vision node)
├── adapters/          FcMotorAdapter implements the SAME MotorAdapter
│                      Protocol the JP01 package implements
├── devices/           mavlink frame builders
└── capabilities.py    motion.takeoff / motion.land / motion.goto —
                       capability NAMES are package-chosen; the framework
                       never hardcodes "arms", "head", or "wheels"
```

Framework untouched except possibly *adding* (not modifying) a
transport/protocol subclass — which is the test of the abstraction:
new package = new directory + maybe new leaf classes, zero edits to
existing files.

### 5.2 Minimum required / maximum overridable

**Minimum a package must declare:** `topology.yaml` with ≥1
controller (node + adapter + link) and ≥0 capabilities; adapters
implementing the generic node's adapter Protocol; schemas for every
capability. **May override:** transports, protocols, device builders,
capability naming below the subsystem level, telemetry topic shapes
(by contributing new TopicMessage structs). **May never override:**
the Node lifecycle contract, the safety layer contract
(`/act/estop` semantics, latch behavior), the capability→ToolDef
registration path (tiers, availability, beta gating), and the rule
that all state-of-record lives in Tier 1 (nodes are stateless
drivers — daemon brief Rule 2).

---

## 6. Positions on §9 design questions

| # | Question | Position | Why |
|---|---|---|---|
| 1 | Process granularity | One process per controller-node (mc01, avc01, vcc01 proxy each its own) | Crash domain = physical link domain; a wedged serial port must not stall the camera; matches Node's process-agnostic design and keeps the future Rust motor node a drop-in |
| 2 | Package location | `jaeger_os/hardware/packages/<robot>/` in-repo; pip entry-point discovery `(planned)` | JP01 co-develops with the framework; external packages are real but not a v1 problem |
| 3 | Topology format | YAML + msgspec validator | Matches Mochi reference, JROS config.yaml habit, operator-editable; validator same week per standing rule |
| 4 | Capability discovery | Both: static topology declaration + connect-time handshake; tools register always, availability tracks node health | Mirrors existing `check_fn`/availability machinery; declared-but-absent degrades visibly instead of vanishing |
| 5 | Naming | `robot.subsystem.verb` internally; per-subsystem umbrella tools to the agent; robot prefix elided when single-robot | Bench-proven routing penalty for big tool surfaces; umbrella precedent (kanban/memory/skill) |
| 6 | Command schema | Pydantic at tool boundary → msgspec structs on bus → Protocol bytes on wire | Each boundary keeps its existing JROS idiom; no protobuf dependency for three boards speaking ASCII |
| 7 | Telemetry | Push-primary (typed bus topics from controller heartbeats/streams) + cached-last-value pull via node health | Wire already pushes (30 s firmware heartbeats, 5 Hz VCC01 telemetry); polling adds nothing |
| 8 | Wire protocol abstraction | Yes — `Protocol` ABC with `AsciiBracketProtocol` first-class, separate from `Transport` | JP01's dual-path proves protocol and transport are independent axes (same brackets over serial or ZMQ relay) |
| 9 | Hot-reload lifecycle | Defer to daemon-arch supervisor; nodes already speak SIGTERM/SIGUSR1 + NodeState; topology `enabled:` is the config surface | The lifecycle API exists in `nodes/base.py`; this plan adds only the hardware-safe teardown guarantees |
| 10 | Health/failure | `/sense/node_health` heartbeat + link state in `health()`; tools fail closed with typed retryable errors; backstops prevent retry-spin | Reuses loop error-result contract + existing guardrails |
| 11 | Simulation | `simulated: true` per controller → MockTransport behind the same adapter; whole-package sim for desktop dev + bench | The seam already exists (`write_line` injection in `SerialMotorAdapter`); MockTransport formalizes it |
| 12 | Repo boundary | Two repos; wire protocol is the versioned contract; host-side moves to JROS, firmware + Jetson internals + diagnostic app stay | Firmware is flashed, hardware-versioned, and non-Python; absorbing it buys nothing |
| 13 | Versioning | `requires_framework` in topology (load-time refusal) + `protocol_version` in firmware handshake `(planned)` | Refuse loudly beats degrade silently |
| 14 | Operator UI | Tier 4 owns it; v1 = generic node-status panel + agent tools; package-shipped panels later; CC01 Qt app survives as standalone diagnostic | Don't rebuild five Qt tabs before the headless path works |
| 15 | Safety/e-stop | Three-layer contract (§2.8): firmware watchdog (hard bound, REQUIRED before live motors), node-local bypass stop, latched bus e-stop; full design = separate brief | Honest physics: only firmware can promise milliseconds; today's `MM[0,0,0]`-on-the-queue is named as inadequate |

---

## 7. Open questions (operator can answer yes/no/"do X")

1. **L0 firmware watchdog mandate:** OK to make a ≤250 ms MC01
   command-watchdog a hard prerequisite for live motor capabilities
   (firmware work in JP01_Firmware before JROS motion leaves beta)?
2. **Multi-robot:** confirm multi-robot-simultaneous is a future
   concern, not v1 (this plan reserves naming for it but builds
   single-robot)?
3. **ROS/ROS2 interop:** stay fully independent for v1, with a
   possible `ros2_bridge` node later — agreed, or is ROS interop a
   nearer-term need?
4. **Hardware e-stop button:** should JP01 get a physical e-stop
   input (wired to MC01 and/or a dedicated node) as part of the L0
   firmware work?
5. **Dual-path relay:** keep CC01's serial-over-ZMQ relay mode as a
   first-class topology feature (this plan says yes — it's how 2.0
   actually runs), or simplify to direct-serial-only for v1?
6. **Robot-mounted audio:** when JP01's mic/speaker come online,
   should they become inputs to the EXISTING JROS voice pipeline
   (audio_session node with a network-audio backend), replacing the
   CC01 Vosk/pyttsx3 stack entirely?
7. **VCC01's future:** eventually run JROS-framework code on the
   Jetson itself (remote hardware node over the bus), or keep it a
   peer application behind the ZMQ contract indefinitely?
8. **Third-party packages:** are external authors expected to write
   hardware packages eventually (affects how soon the pip
   entry-point discovery and package docs matter)?

---

## 8. What I did NOT design (explicit non-goals)

- The Tier-3 supervisor itself (process spawn, restart policy,
  operator CLI) — that is the daemon-arch plan's deliverable; this
  plan only guarantees nodes are supervisable.
- The full e-stop system (button hardware, firmware watchdog
  implementation, latency verification harness) — contract only;
  separate safety brief before any live-motor milestone.
- Multi-host JROS (running framework nodes ON the Jetson) — flagged
  as future daemon-arch work.
- Robot-mounted audio integration with the voice pipeline (OQ 6).
- pip-distributed external packages (hook reserved, not built).
- Binary/high-rate protocol implementations (`MsgpackProtocol`,
  `CanTransport` are named as future leaf classes, not designed).
- Any firmware changes — `protocol_version` handshake and L0
  watchdog are *specified as required* but their implementation
  belongs to JP01_Firmware.

## 9. Risks + unknowns

- **CC01 `main.py` is mid-refactor on 2.0** (undefined names as
  read) — the "current state" this plan aligns against is partly in
  motion; re-verify §4.1 mappings when implementation starts.
- **Serial bandwidth vs ambition:** full 64×64 matrix frames are
  ~24.5 KB of ASCII per frame; animation-rate streaming requires the
  relay path or a binary protocol — the framework allows both, but
  expectations for "Lilith's face on the chest matrix" need a
  latency/rate budget before promising it.
- **The dual-path relay doubles the test matrix** (every MC01/AVC01
  capability × {direct, relayed}) — bench/sim coverage must include
  both or the untested path will rot.
- **Firmware co-evolution risk:** the wire protocol is the contract,
  but today it has no version field — until the handshake ships,
  adapter and firmware can drift silently (the exact bug class JROS
  reviews keep finding in software-only form).
- **Safety scope creep:** desk-scale servos today, humanoid actuators
  tomorrow; the L0-before-live-motors gate (§4.2 step 5) is the
  control point, and it requires operator discipline to not bypass
  when demo pressure hits.
- **Unverified at design time:** actual serial port stability under
  the relay topology, VCC01 REP-socket behavior under concurrent
  clients (CC01 app + JROS both connected), and Teensy USB-CDC
  throughput at frame sizes — all `[UNVERIFIED]`, to be measured in
  migration step 2–3.

---

*End of plan. Implementation gated on operator approval; first
implementation slice on approval would be §4.2 step 1 (framework +
mocks + tests), which touches no hardware and no JP01_Firmware code.*
