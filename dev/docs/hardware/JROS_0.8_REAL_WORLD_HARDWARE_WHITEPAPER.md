# JROS 0.8 Real-World Hardware White Paper

**Status:** planning document for 0.8 development
**Scope:** hardware integration, middleware, physical nodes, operator control, and agentic control
**Primary test bed:** humanoid audiovisual animatronics with local agentic AI

---

## 1. Purpose

JROS has reached the point where the agent can exist as a software product:
it can run locally, speak, listen, use tools, manage persona and memory, run
agentic pipelines, and present itself through built-in UI surfaces. The next
phase is turning that agent into a real-world agentic framework that can
operate physical systems.

The 0.8 development line should make hardware a first-class part of JROS
without turning JROS into a plain ROS clone. JROS should remain the layer where
an agent, a human operator, scripted sequences, and deterministic controllers
coordinate through one configured runtime.

The core question for 0.8 is:

> How does JROS safely connect an agentic AI brain to motors, cameras,
> microphones, displays, lights, middleware, external devices, and future robot
> bodies without hardcoding one robot into the framework?

This document defines the proposed answer.

---

## 2. Current State

### 2.1 What is solid today

JROS already has the foundation needed for embodied systems:

- A local-first agent loop with realtime and background runners.
- A Swift-first desktop application and tray/menu surfaces.
- Voice, TTS, STT, memory, persona, model, permissions, and skill pipelines.
- A node model where subsystems can run as long-lived units of work.
- A manifest model for app shape: core, bus, nodes, surfaces, event loop, and
  fused/split runtime modes.
- In-process and ZMQ bus concepts.
- Existing audio, TTS, animation/media, vision, motor, and light node areas.
- Hardware scaffolding under `jaeger_os/hardware/`.
- A system e-stop concept where hardware motion must fail closed when latched.
- Early hardware packages, most notably `jaeger_os/hardware/packages/jp01/`.

The most important design choice already present is the separation between:

- **Agent tools:** semantic requests from the brain.
- **Nodes:** long-running subsystem workers.
- **Adapters:** the implementation that speaks to a device or external system.
- **Bus topics:** the shared nervous system between those pieces.

That is the right direction and should be kept.

### 2.2 What is incomplete

The hardware path is not yet production-ready:

- Hardware packages exist, but the package contract is not yet the source of
  truth for real robot configuration.
- Some node declarations are parked because the app chassis and existing JROS
  runtime still have bus/supervision duality.
- Motor, light, and vision nodes are useful skeletons, but not yet a complete
  physical runtime.
- There is no single settings model that explains body package, devices,
  safety mode, operator controls, middleware links, telemetry, calibration, and
  simulation in one place.
- The system does not yet have a deterministic sequence runner for physical
  performances and rehearsed moves.
- Hardware telemetry needs a separate strategy from agent memory. High-volume
  sensor logs should not be stored like conversational memory.
- Middleware bridges such as ROS 2, MAVLink, CAN, serial device pools, camera
  streams, and microcontroller links need a unified integration policy.

### 2.3 Strategic reading

JROS is in a good position because it does not need to reinvent its identity.
It already says:

- One brain process can coordinate many hardware-bound peripheral nodes.
- The tool does the networking; the node does the execution.
- STT, TTS, vision, motors, and lights are nodes, not direct calls inside the
  agent loop.
- Real hardware should arrive as configured packages, not forks of the runtime.

0.8 should finish that promise.

---

## 3. 0.8 Thesis

JROS 0.8 should define a **real-world agentic agent framework**:

1. The agent never directly drives raw motors, PWM, serial frames, or GPIO.
2. The agent requests semantic capabilities such as `speak`, `look_at`,
   `play_expression`, `move_joint_pose`, `track_target`, or `open_gripper`.
3. Capability requests pass through permissions, safety envelopes, operational
   mode checks, and operator policy.
4. Hardware nodes execute approved actions through deterministic adapters.
5. Human operators can override, approve, script, teleoperate, pause, stop, and
   inspect the system at every level.
6. Hard-coded control loops keep ownership of reflexes, stabilization, limits,
   watchdogs, current protection, and emergency behavior.
7. Middleware bridges let JROS talk to ROS 2-style nodes and other robotics
   ecosystems without making JROS depend on one middleware everywhere.

The key distinction:

> JROS should use ROS 2-style lifecycle, topic, and node discipline, but expose
> an agent-native capability layer above it.

---

## 4. Target Platforms

The framework must grow across multiple robot classes:

| Platform | First-class concerns |
|---|---|
| Humanoid robots | head, eyes, face display, arms, hands, torso, microphones, cameras, speech, safety zones, scripted performances |
| Audiovisual animatronics | lip sync, expressions, LEDs, gaze, gestures, timed sequences, human-authored shows |
| Aerial drones | flight controller bridge, MAVLink, GPS, camera, payload, autonomy limits, geofence, failsafe |
| Underwater drones | thrusters, tether or acoustic links, depth sensor, camera, lighting, low-bandwidth telemetry |
| Robotic dogs/quadrupeds | gait controller bridge, pose, balance, terrain mode, operator takeover |
| 2/3/4-axis turrets | pan, tilt, roll, trigger-safe payloads, tracking, hard aim limits |
| Robotic arms | joint limits, IK, end effectors, fixtures, guarded workspaces |
| Mobile bases | wheels/tracks, odometry, obstacle detection, docking, battery state |

The first major focus should be the humanoid/animatronic test bed because it
exercises the highest-value JROS identity:

- Local voice interaction.
- Face and expression rendering.
- Gaze, head movement, and gesture.
- Human-assisted scripting.
- Agent-authored plans with deterministic playback.
- Cameras and microphones as live perception.
- Safety without the immediate complexity of full locomotion.

---

## 5. Control Planes

Real robots need more than "agent calls tool." JROS should model three control
planes and one shared arbiter.

### 5.1 Agentic control

The agent proposes goals, plans, and capability requests. It can:

- Speak and listen.
- Ask for perception.
- Request a gesture, expression, or movement.
- Build or select a sequence.
- Monitor task state.
- Ask the operator for approval.
- Run background planning through Deep Think.

The agent cannot:

- Release e-stop.
- Bypass safety envelopes.
- Send raw motor frames.
- Change hardware calibration without explicit operator mode.
- Own low-level stabilization or reflex loops.

### 5.2 Human operation

The operator owns authority. Human controls should include:

- E-stop engage and release.
- Mode changes: sim, bench, teleop, assisted, autonomous, show.
- Hardware package selection.
- Node enable/disable/restart.
- Device connection and calibration.
- Script and sequence authoring.
- Approval queues for risky actions.
- Manual teleoperation.
- Live override of agent movement.
- Diagnostics and logs.

This must be available through both GUI and CUI/TUI paths.

### 5.3 Hard-coded controls

Hard-coded controllers own the physical invariants:

- Servo limits.
- Motor current and thermal limits.
- PID loops.
- Balance/stabilization.
- Watchdogs.
- Heartbeats.
- Collision and workspace constraints.
- Failsafe behavior on link loss.
- Queue-bypassing local stop.

These controls may live in firmware, microcontrollers, ROS 2 nodes, or JROS
hardware nodes, but they must not depend on LLM judgment.

### 5.4 Arbitration

Every action should resolve through a single arbitration policy:

```
agent request / human command / sequence frame
        |
        v
capability contract
        |
        v
permissions + mode + safety envelope + priority
        |
        v
node command
        |
        v
hardware adapter / middleware bridge / firmware
```

Priority should be:

1. E-stop and hard safety.
2. Human manual override.
3. Deterministic reflex/control loop.
4. Approved scripted sequence.
5. Agent-requested capability.
6. Background/autonomous suggestions.

---

## 6. Proposed Layered Architecture

```
JROS operator surfaces
  Swift app, tray, TUI/CUI, diagnostics, settings, sequence editor

Agent layer
  standard runner, Deep Think, skills, memory, persona, tool registry

Capability layer
  semantic actions, permissions, safety envelopes, source attribution

Node layer
  ROS-style lifecycle nodes: audio, TTS, vision, motor, light, display,
  sequence, teleop, middleware bridge, telemetry

Hardware package layer
  package topology, devices, links, adapters, calibration, limits, modes

Middleware/device layer
  ROS 2, MAVLink, CAN, serial, USB, ZMQ, RTSP/WebRTC, microcontrollers,
  cameras, microphones, motor drivers, LED controllers

Telemetry and audit layer
  health, events, blackbox logs, traces, high-volume time-series data
```

The framework should keep the current JROS pattern:

- The app manifest declares the runtime shape.
- Instance config declares operator choices.
- Hardware package topology declares the physical body.
- Capabilities expose safe semantic control to the agent.

---

## 7. Hardware Packages

Hardware packages should become the main unit of embodiment.

A package answers:

- What body is this?
- Which devices exist?
- Which nodes should run?
- Which links connect to which controllers?
- Which capabilities are exposed?
- What are the safety limits?
- What calibration is active?
- Which sensors produce telemetry?
- Which controls are available to humans?
- Which simulation profile mirrors this body?

### 7.1 Package layout

Recommended package shape:

```text
jaeger_os/hardware/packages/<package_name>/
  package.yaml
  topology.yaml
  capabilities.py
  adapters/
  devices/
  nodes/
  calibration/
  sequences/
  tests/
  README.md
```

`package.yaml` should identify the package:

```yaml
name: humanoid_av_01
display_name: Humanoid AV Test Bed 01
kind: humanoid_animatronic
requires_jros: ">=0.8"
default_mode: bench
simulation_profile: humanoid_av_01_sim
```

`topology.yaml` should describe devices, links, frames, and nodes:

```yaml
links:
  head_mcu:
    transport: serial
    port: /dev/cu.usbmodem-head
    baud: 115200
    protocol: json_line

  face_display:
    transport: tcp
    host: 192.168.1.42
    port: 7777
    protocol: msgpack

devices:
  neck_pan:
    kind: servo
    link: head_mcu
    joint: neck_pan
    limits: { min_deg: -70, max_deg: 70, max_speed_deg_s: 90 }

  neck_tilt:
    kind: servo
    link: head_mcu
    joint: neck_tilt
    limits: { min_deg: -35, max_deg: 45, max_speed_deg_s: 70 }

  face:
    kind: led_display
    link: face_display
    resolution: [64, 32]

nodes:
  motor_head:
    factory: jaeger_os.nodes.motor:make_motor_node
    backend: thread
    devices: [neck_pan, neck_tilt]

  face_display:
    factory: jaeger_os.nodes.light:make_light_node
    backend: thread
    devices: [face]
```

`capabilities.py` and `capabilities.yaml` should expose semantic actions:

```yaml
capabilities:
  speak:
    node: tts
    tier: external_effect
    modes: [bench, teleop, assisted, show, autonomous]

  look_at:
    node: motor_head
    tier: hardware
    devices: [neck_pan, neck_tilt]
    requires: [head_clearance]
    modes: [bench, teleop, assisted, show]

  play_expression:
    node: face_display
    tier: external_effect
    devices: [face]
    modes: [bench, teleop, assisted, show, autonomous]
```

### 7.2 Static versus runtime config

JROS should separate three kinds of configuration:

| Layer | File/UI area | Purpose |
|---|---|---|
| Manifest | `jaeger.toml` family | What process shape exists: core, bus, nodes, surfaces |
| Hardware package | `hardware/packages/<name>/` | What the body physically is |
| Instance settings | config store, GUI, CUI | Which package, mode, devices, models, limits, and operator preferences are active |

The manifest should not contain per-robot joint limits. The hardware package
should not contain the user's current audio model. Instance settings should
not redefine the package's physical topology.

---

## 8. Capability Taxonomy

The capability layer is the bridge between agent language and physical work.

### 8.1 Audiovisual humanoid capabilities

These should be first:

- `speak(text, voice, priority)`
- `listen(mode, timeout, source)`
- `play_expression(expression, intensity, duration)`
- `set_face_scene(scene, parameters)`
- `set_led_pattern(pattern, color, duration)`
- `look_at(target, speed, blend)`
- `set_gaze(yaw, pitch, duration)`
- `nod(style, intensity)`
- `gesture(name, side, intensity)`
- `play_sequence(sequence_id, parameters)`
- `stop_sequence(reason)`
- `track_person(person_id, mode)`
- `capture_image(camera, reason)`
- `describe_scene(camera, mode)`

### 8.2 General robot capabilities

These should be designed as stable contracts even if not all are implemented
in 0.8:

- `move_joint_pose(joints, duration, constraints)`
- `move_joint_velocity(joints, velocities, duration)`
- `move_base(linear, angular, duration)`
- `move_to_pose(frame, pose, constraints)`
- `open_gripper(hand, amount)`
- `close_gripper(hand, force_limit)`
- `set_turret_angle(pan, tilt, roll)`
- `track_target(target, constraints)`
- `takeoff(altitude)` for aerial packages only.
- `land(reason)` for aerial packages only.
- `hold_depth(depth)` for underwater packages only.
- `set_thrusters(vector)` for underwater packages only.
- `dock(target)` for mobile/charging systems.

### 8.3 Capability command envelope

Every hardware capability request should carry:

```yaml
command_id: uuid
source: agent | human | sequence | reflex | test
source_detail: session id, user id, sequence id, or node id
capability: look_at
package: humanoid_av_01
mode: assisted
requested_at: timestamp
deadline_ms: 500
safety_context:
  estop_latched: false
  workspace: bench
  human_approved: true
limits:
  max_speed: package_default
  max_force: package_default
payload:
  target: operator_face
```

The node should reply with:

```yaml
command_id: uuid
accepted: true
status: queued | running | complete | refused | failed | preempted
reason: optional string
node: motor_head
started_at: timestamp
completed_at: timestamp
telemetry_ref: optional trace id
```

---

## 9. Topics and Message Areas

JROS should keep topic families readable and stable:

| Family | Purpose |
|---|---|
| `/act/*` | Commands to act on the world |
| `/sense/*` | Sensor and perception outputs |
| `/sys/*` | lifecycle, health, node status, boot state |
| `/control/*` | operator commands, mode changes, approvals |
| `/telemetry/*` | high-rate or structured robot telemetry |
| `/safety/*` | e-stop, safety envelope, fault events |
| `/sequence/*` | sequence playback, timeline state, cue events |
| `/middleware/*` | bridge status and external node discovery |

Recommended first hardware topics:

- `/act/speech`
- `/act/motion`
- `/act/light`
- `/act/display`
- `/act/sequence`
- `/sense/audio_in`
- `/sense/transcript`
- `/sense/camera_frame`
- `/sense/vision_analysis`
- `/sense/joint_state`
- `/sense/device_state`
- `/sys/node_health`
- `/sys/package_health`
- `/safety/estop`
- `/telemetry/power`
- `/telemetry/thermal`
- `/telemetry/link`

---

## 10. Safety Model

The 0.8 hardware system should be fail-closed by design.

### 10.1 Safety layers

| Layer | Owner | Responsibility |
|---|---|---|
| L0 mechanical/electrical | hardware/firmware | fuses, current limits, power cutoff, physical stops |
| L1 node local stop | hardware node/firmware | queue-bypassing immediate stop |
| L2 system e-stop | JROS safety bus | global latch, stop all registered motion nodes |
| L3 capability envelope | capability layer | limits, modes, workspace, body-specific constraints |
| L4 permission gate | agent/operator policy | approve or refuse risky actions |
| L5 operational mode | operator/runtime | sim, bench, teleop, assisted, autonomous, show |
| L6 audit/blackbox | telemetry/logging | reconstruct what happened and who requested it |

The existing JROS e-stop idea is correct: a confused node or agent must not be
able to un-stop the robot. Release should remain human-owned.

### 10.2 Modes

JROS should make mode explicit:

| Mode | Meaning |
|---|---|
| `sim` | no physical hardware, simulated nodes only |
| `bench` | hardware connected, low-speed, low-risk, local test mode |
| `teleop` | human controls motion directly |
| `assisted` | agent may propose/execute bounded actions with human oversight |
| `show` | deterministic sequence playback with live safety monitoring |
| `autonomous` | agent can execute approved capability classes without per-action approval |
| `maintenance` | calibration, firmware, device tests, high-risk manual operations |

The first humanoid work should stay in `sim`, `bench`, `teleop`, `assisted`,
and `show`. Full `autonomous` should be treated as a later milestone.

---

## 11. Middleware Integration

JROS should not make one middleware mandatory. It should define its own
agent-native capability and node contracts, then bridge to external systems
where useful.

### 11.1 Bridge targets

| Middleware/link | Use |
|---|---|
| ROS 2 / DDS | existing robotics packages, joint state, transforms, navigation, perception |
| MAVLink | aerial drones, flight controllers, telemetry, mission commands |
| CAN / CAN-FD | motor controllers, battery systems, embedded networks |
| Serial/UART | microcontrollers, simple motor/light/display controllers |
| ZMQ | existing JROS bus, JP01-style controllers, fast local IPC |
| TCP/UDP | custom embedded devices, cameras, stream side channels |
| RTSP/WebRTC | camera and remote video streams |
| USB/HID | gamepads, custom controllers, sensors |

### 11.2 Integration rule

External middleware should appear to JROS as a node or adapter:

```
ROS 2 joint state topic -> ros2_bridge node -> /sense/joint_state
JROS /act/motion -> ros2_bridge node -> ROS 2 command topic
MAVLink telemetry -> mavlink_bridge node -> /telemetry/flight
JROS takeoff capability -> mavlink_bridge node -> flight controller command
```

The agent should still call JROS capabilities, not ROS 2 topics directly.

### 11.3 ROS 2 style without ROS 2 lock-in

JROS should adopt:

- Managed lifecycle states.
- Topic discipline.
- Health and heartbeat messages.
- Node restart policy.
- Message schema versioning.
- Transform/frame naming where useful.

JROS should not require:

- A full ROS 2 install for every desktop agent.
- Raw ROS topic names in agent prompts.
- ROS as the only hardware integration path.

---

## 12. Configuration and Settings

The settings system should expose hardware as a first-class group. Every
setting should be adjustable through a GUI and a CUI/TUI method.

### 12.1 Hardware settings groups

Recommended settings organization:

- **Instance**
  - active instance name
  - body package
  - simulation profile
  - startup mode
  - autostart hardware nodes
  - environment label: desk, bench, lab, field

- **Hardware Package**
  - selected package
  - package version
  - package health
  - enabled devices
  - disabled devices
  - calibration profile
  - firmware compatibility

- **Operational Mode**
  - sim/bench/teleop/assisted/show/autonomous/maintenance
  - max speed scale
  - max force scale
  - movement approval policy
  - sequence approval policy
  - autonomous capability allowlist

- **Safety**
  - e-stop status
  - e-stop release control
  - safety envelope profile
  - workspace limits
  - joint limit overrides in maintenance mode
  - watchdog timeout
  - link-loss behavior
  - power/thermal thresholds

- **Nodes**
  - node list
  - enabled/disabled
  - backend: thread/subprocess/external
  - restart policy
  - health state
  - last heartbeat
  - log level
  - node-specific config

- **Middleware**
  - ROS 2 bridge enabled
  - ROS domain id
  - ROS namespace
  - MAVLink endpoint
  - CAN interface
  - serial device mappings
  - camera stream endpoints
  - ZMQ endpoints

- **Devices**
  - motors
  - servos
  - cameras
  - microphones
  - speakers
  - LED displays
  - LED strips
  - IMUs
  - battery/power monitors
  - gamepads/controllers

- **Teleoperation**
  - input device mapping
  - deadman switch
  - speed scale
  - per-axis inversion
  - camera view
  - operator priority
  - handoff policy between human and agent

- **Sequences**
  - sequence folder
  - sequence playback mode
  - allowed sequence capabilities
  - rehearsal mode
  - timeline FPS
  - preflight checks
  - cue sources: human, agent, sensor, timer

- **Telemetry**
  - telemetry store enabled
  - sample rates
  - retention
  - blackbox logging
  - exported traces
  - diagnostics dashboard

- **Simulation**
  - simulated package
  - recorded playback source
  - sensor replay
  - fake device latency
  - fault injection
  - visualizer endpoint

### 12.2 CUI commands

JROS should gain simple operator commands:

```text
jaeger hardware list
jaeger hardware use humanoid_av_01
jaeger hardware status
jaeger hardware health
jaeger hardware nodes
jaeger hardware node restart motor_head
jaeger hardware mode bench
jaeger hardware estop engage "operator test"
jaeger hardware estop release
jaeger hardware calibrate neck_pan
jaeger sequence list
jaeger sequence play greeting_01 --mode rehearsal
jaeger telemetry tail --node motor_head
```

The Swift UI should call the same underlying config and control APIs.

---

## 13. Humanoid/Animatronic First Roadmap

The first hardware test bed should be humanoid audiovisual animatronics, not
full locomotion. This gives JROS the clearest path to visible, useful demos
while keeping risk manageable.

### Phase A: audiovisual body skeleton

Build:

- Face or LED display node.
- Speaker/TTS node connected to the physical output path.
- Microphone/STT node connected to the physical input path.
- Camera node.
- Head pan/tilt motor node.
- Basic light node.
- Package topology for the humanoid AV test bed.
- Bench and simulation modes.

Demonstration:

- Agent speaks through the robot.
- Robot shows expressions.
- Robot looks toward a target or operator.
- Operator can e-stop and manually override motion.

### Phase B: deterministic sequence runner

Build:

- Timeline/sequence schema.
- Sequence player node.
- Cue system.
- Human-authored sequence folder.
- Rehearsal mode.
- Safety preflight.
- UI for play/pause/stop.

Demonstration:

- Human scripts a greeting sequence.
- Agent can request an approved sequence.
- Sequence runs with face, speech, lights, and head motion.

### Phase C: perception-informed behavior

Build:

- Camera frame ingestion.
- Basic person/face target tracking.
- Gaze target selection.
- Scene description capability.
- Sensor replay tests.

Demonstration:

- Robot looks toward a detected person.
- Agent can ask what the robot sees.
- Agent can combine speech, gaze, and expression.

### Phase D: arms and gestures

Build:

- Arm/hand joint package entries.
- Joint state telemetry.
- Gesture capability.
- Workspace constraints.
- Sequence blending.

Demonstration:

- Robot waves, points, gestures, and performs simple choreographed motions.

### Phase E: advanced embodiment

Only after earlier phases are stable:

- Locomotion.
- Balance.
- Object manipulation.
- Navigation.
- More autonomous physical tasks.

---

## 14. Sequence System

Humanoid performance needs a deterministic layer between agent planning and
physical motion.

The sequence system should support:

- Timeline tracks for speech, face, LEDs, head, arms, sounds, and cues.
- Parameterized sequences.
- Dry-run validation.
- Rehearsal mode with reduced speed.
- Operator-authored scripts.
- Agent-selected but policy-approved playback.
- Sensor and human cues.
- Interrupt and recovery behavior.

Example sequence:

```yaml
id: greeting_01
title: Greeting Sequence 01
requires:
  mode: [bench, show]
  capabilities: [speak, look_at, play_expression, gesture]
tracks:
  - at: 0.0
    capability: play_expression
    payload: { expression: smile, intensity: 0.8 }
  - at: 0.2
    capability: look_at
    payload: { target: operator, speed: gentle }
  - at: 0.4
    capability: speak
    payload: { text: "System online. Ready for operator input." }
  - at: 1.2
    capability: gesture
    payload: { name: small_wave, side: right }
```

The agent may generate draft sequences, but live execution should require
validation and, in early 0.8, human approval.

---

## 15. Telemetry and Diagnostics

Physical systems need observability beyond chat logs.

JROS should separate:

- **Agent memory:** facts, reflections, user preferences, conversation state.
- **Operational logs:** command history, approvals, node lifecycle events.
- **Telemetry:** high-volume time-series data from motors, sensors, links,
  cameras, power, and thermal systems.
- **Blackbox logs:** compact, durable records around faults and e-stop events.

Recommended telemetry categories:

- Node heartbeat.
- Link latency and reconnects.
- Motor position, velocity, current, temperature.
- Servo commanded versus actual state.
- Battery voltage/current.
- Camera FPS and dropped frames.
- Audio device status.
- Middleware bridge health.
- E-stop transitions.
- Command acceptance/refusal/failure.

0.8 should decide whether to use a lightweight local time-series store,
SQLite tables with retention, or an external TSDB for field deployments. The
important rule is that raw hardware telemetry should not pollute agent memory.

---

## 16. 0.8 Implementation Plan

### 0.8.0: runtime unification

Goal: make the app chassis able to own the real node topology.

Deliverables:

- Resolve bus/supervision duality between existing runtime and app chassis.
- Make hardware node declarations bootable from manifest/config.
- Standardize node health and lifecycle reporting.
- Add a hardware status API consumed by Swift and CUI.
- Add simulation mode as a first-class runtime option.

### 0.8.1: hardware package spec v1

Goal: make hardware packages authoritative.

Deliverables:

- `package.yaml` and `topology.yaml` schema.
- Package loader validation.
- Device/link/capability declaration.
- Calibration profile support.
- Package health summary.
- Mock/sim adapters for package tests.

### 0.8.2: humanoid AV package v0

Goal: bring up the first physical animatronic package.

Deliverables:

- Face/display node.
- Light node path.
- Head pan/tilt motor node.
- Camera node path.
- Mic/speaker physical device selection.
- Safety limits for head and display.
- Operator settings panel for package, devices, and mode.

### 0.8.3: sequence runner

Goal: make human-authored and agent-requested performances deterministic.

Deliverables:

- Sequence schema.
- Sequence player node.
- Rehearsal/dry-run mode.
- Preflight validation.
- Timeline status topics.
- Swift/TUI sequence controls.
- Agent capability: request approved sequence.

### 0.8.4: teleop and arbitration

Goal: make human operation and agent operation coexist safely.

Deliverables:

- Teleop node.
- Gamepad/keyboard mapping.
- Deadman switch.
- Manual override priority.
- Mode-aware arbitration.
- Operator approval queue.
- E-stop UX in GUI and CUI.

### 0.8.5: middleware bridges

Goal: connect JROS to broader robotics ecosystems.

Deliverables:

- ROS 2 bridge proof of concept.
- MAVLink bridge proof of concept for drones.
- Serial/CAN device mapping policy.
- Camera stream bridge pattern.
- Bridge health and telemetry.

### 0.8.6: hardening

Goal: move from demo to reliable lab platform.

Deliverables:

- Hardware-in-loop tests.
- Fault injection.
- Recorded sensor playback.
- Latency budgets.
- Blackbox logs.
- Safety regression tests.
- Scenario test suite expansion for physical workflows.

---

## 17. Validation Strategy

Every hardware feature should have four levels of validation:

1. **Schema tests:** config and package files reject invalid shape.
2. **Simulation tests:** capability calls run against mock devices.
3. **Recorded replay:** sensor and telemetry recordings reproduce bugs.
4. **Hardware-in-loop:** real devices run controlled test scripts.

Required test classes:

- E-stop engage stops all motion nodes.
- E-stop release is human-only.
- Link loss causes safe behavior.
- Node crash is reported and restarted according to policy.
- Agent cannot call a disabled capability.
- Agent cannot exceed package speed/force limits.
- Sequence preflight refuses missing devices.
- Teleop overrides agent motion.
- Simulation and hardware package expose the same capability names.

---

## 18. Open Decisions

These need explicit decisions during 0.8 design:

- Should hardware package schemas use YAML only, or TOML where aligned with
  `jaeger.toml`?
- What is the canonical telemetry store for local-first JROS?
- Which bridge comes first: ROS 2, MAVLink, or serial/CAN hardening?
- Should transforms/frames follow ROS naming exactly?
- How much sequence editing belongs in the Swift app versus files/CUI first?
- Should package capabilities be declared in YAML, Python, or both?
- What is the minimum safety certification target for public demos?
- Which humanoid AV hardware is the first physical reference package?
- Should external hardware packages be Python packages, git submodules, or
  folders loaded from a package path?

---

## 19. Immediate Next Steps

1. Pick the first humanoid AV hardware package name and physical component
   list.
2. Write hardware package schema v1.
3. Unify the runtime path so manifest-declared nodes can supervise real
   hardware nodes.
4. Add GUI/CUI settings for hardware package, mode, node status, and e-stop.
5. Build a simulator/mock device harness before live motors.
6. Bring up face/display, speech, microphone, camera, and head pan/tilt first.
7. Add deterministic sequence playback before freeform agent motion.
8. Add telemetry and blackbox logging around every hardware command.

---

## 20. Final Position

JROS 0.8 should make the physical body configurable, observable, and safe.
The agent should become a capable planner and performer, not a raw motor
controller. Humans should remain first-class operators. Hard-coded controls
should own low-level safety and timing. Hardware packages should let JROS grow
from one humanoid animatronic test bed into drones, underwater vehicles,
robotic dogs, turrets, arms, and future Jaegers without rewriting the core.

The near-term target is clear: build the humanoid audiovisual animatronic
stack first, prove speech, expression, gaze, scripted performance, perception,
operator override, and safety. Then expand the same framework outward to more
dangerous and more mobile bodies.
