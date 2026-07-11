# JROS Framework Review — 0.6 Alpha

**Date:** 2026-07-01  
**Reviewed version:** JROS 0.6 alpha  
**Scope:** Architecture/library review of `jaeger_os` as a framework that aims to combine a Hermes-class local AI agent with a ROS-like robotics runtime for humanoids, drones, UAVs, and desktop/digital agents.

## Executive Verdict

JROS is credibly moving toward **"Hermes-style AI agent + ROS-like robot runtime"**, but it is not yet a complete live robot operating system. The framework is strongest today as a local AI agent runtime with a promising early hardware layer: typed topics, node lifecycle primitives, a package-based hardware abstraction, simulation-first JP01 integration, permission gates, and e-stop coordination.

The correct near-term framing is:

> JROS is the local AI brain and operator OS that sits above firmware-grade, ROS2-grade, or flight-controller-grade control systems.

It should not try to replace real-time control stacks. It should orchestrate them.

Current rating:

| Area | Assessment |
|---|---|
| Agent/runtime layer | Strong |
| UI/operator surfaces | Active and improving |
| Hardware abstraction | Good early implementation |
| JP01 package | Simulation-grade, useful architecture proof |
| Live humanoid readiness | Not yet |
| Live drone/UAV readiness | Not yet |
| Architectural potential | High |

## What JROS Is Trying To Be

The ideal goal is ambitious and coherent:

- A local-first AI agent runtime with memory, tools, permissions, skills, and personality.
- A node/topic "nervous system" that lets the same brain drive multiple bodies.
- A robot package model where JP01, future humanoids, drones, cars, and desktop avatars can each declare their hardware and capabilities.
- A single operator experience for chat, voice, avatar, tool use, robot control, and diagnostics.

This is a valid product/architecture direction. The best mental model is not "JROS replaces ROS2." It is:

```text
JROS agent brain
  -> high-level intent, skill/tool orchestration, memory, permissions, UI

Robot package / hardware adapter layer
  -> maps JROS capabilities to body-specific commands

Firmware / ROS2 / PX4 / ArduPilot / microcontrollers
  -> hard real-time control, stabilization, actuator safety, sensor fusion
```

That layering is essential. A local LLM can choose goals and call tools; it must not be the control loop that keeps a drone level or a humanoid balanced.

## Evidence Of Real Framework Progress

The repo now contains more than a plan. There is a real early hardware framework in `jaeger_os/hardware/`.

Notable strengths:

- `jaeger_os/transport/topics.py` defines typed `/sense/*`, `/act/*`, and health/control topics with `msgspec`.
- `jaeger_os/nodes/base.py` defines a reusable node lifecycle: `setup`, `tick`, `teardown`, `health`, stop, restart, failed states.
- `jaeger_os/app/supervisor.py` provides thread/subprocess node supervision, restart policy, crash-loop detection, and child process cleanup.
- `jaeger_os/hardware/package.py` validates robot `topology.yaml` files strictly.
- `jaeger_os/hardware/link.py` implements `Transport x Protocol` links with optional relay fallback.
- `jaeger_os/hardware/transport.py` includes serial, ZMQ request, and mock transports.
- `jaeger_os/hardware/protocol.py` includes the JP01 ASCII bracket protocol and JSON-line protocol.
- `jaeger_os/hardware/safety.py` implements a process-local e-stop latch over `/act/estop`.
- `jaeger_os/hardware/capabilities.py` turns topology capabilities into beta-gated umbrella tools such as `motion`, `lights`, `robot_vision`, and `telemetry`.
- `jaeger_os/hardware/packages/jp01/` contains a concrete JP01 package with MC01, AVC01, and VCC01 adapters.

The JP01 package is especially useful because it proves the intended pattern:

- Controllers are declared in `topology.yaml`.
- Transport choice is per controller.
- Simulation is default.
- Capability schemas clamp unsafe/out-of-range arguments before they hit the wire.
- The e-stop latch blocks motion while allowing telemetry and lights.
- Shutdown neutralizes motors and blanks LEDs.

The hardware test set currently passes locally:

```text
56 passed in 3.07s
```

That matters. It means the framework seams are testable before hardware is attached.

## Main Architectural Concern: Integration Gap

The largest gap is not the hardware package code. It is runtime integration.

`jaeger.toml` documents that chassis integration is blocked by bus duality. The full topology is declared, but hardware nodes are disabled. The current system has overlapping runtime paths:

- Existing JROS runtime path.
- App/chassis runtime path.
- Hardware package boot path.
- Node singleton/runtime path.
- Windowed-app path.

That is survivable during development, but for a robot OS it becomes dangerous. A real robot needs one authoritative boot graph:

1. Acquire instance lock.
2. Build one bus.
3. Start core agent.
4. Start hardware package.
5. Start supervised nodes.
6. Start surfaces.
7. Register health, e-stop, permissions, and shutdown hooks.
8. Tear down in reverse order.

Until that exists, JROS should be described as "hardware-framework ready" rather than "robot-runtime ready."

## Main Robotics Concern: Control Granularity

The current command layer is useful for JP01 demos, but too coarse for humanoids and drones.

Current motion surfaces include:

- Generic `MotionCommand`: velocity or waypoint.
- JP01 capability tools: move two servo joints, drive two motors, stop.

This is not enough for:

- Humanoid gait.
- Balance.
- Whole-body control.
- Arm trajectories.
- Manipulation.
- Footstep planning.
- Collision avoidance.
- Drone attitude/rate control.
- UAV mission planning with failsafes.

JROS needs to separate **intent** from **control**:

| Layer | Example |
|---|---|
| Agent intent | "walk to the door", "look at the operator", "land now" |
| Capability/tool layer | `navigation.goto`, `head.look_at`, `flight.land` |
| Robot controller | ROS2 Nav2, gait engine, PX4, MCU firmware |
| Actuator loop | motor drivers, ESCs, servos, PID loops |

The LLM should only call bounded capabilities. It should not calculate raw actuator values except in simulation or developer tools.

## Safety Assessment

The safety model is directionally correct but not strict enough yet for live bodies.

Good:

- Six-tier permission ladder includes `HARDWARE`.
- Hardware tools are beta-gated.
- JP01 topology uses `simulated: true` by default.
- E-stop latch is latched and operator-only release.
- Motion refuses while e-stop is latched.
- Shutdown attempts to neutralize motors.
- The code explicitly states Python e-stop is best-effort and not hard real-time.

Concern:

`firmware_watchdog_required: true` currently produces a warning when live hardware lacks a watchdog. For real motors, this should be a hard boot refusal unless an explicit development override is set.

Required before live humanoid/drone operation:

- Firmware-level watchdog.
- Physical e-stop path independent of Python.
- Command timeout/lease on every motion command.
- Hardware heartbeat with enforced stale-state cutoff.
- Controller-level safe state on lost comms.
- Motion limits loaded from topology.
- Audit log for hardware commands.
- Clear operator arming/disarming state.
- Simulation/live mode visible in every surface.

## Humanoid Readiness

JROS can become the high-level brain for a humanoid, but it is not yet a humanoid control stack.

Missing pieces:

- Robot model: joints, limits, frames, links, sensors, actuator groups.
- Proprioception schema beyond basic list fields.
- Trajectory commands with timing, interpolation, and acknowledgements.
- Whole-body controller integration.
- Balance/fall detection.
- Manipulation/action primitives.
- Gait planner or bridge to a gait planner.
- Safety envelopes and workspace constraints.
- Sensor fusion boundary.

Recommended humanoid model:

- JROS issues semantic commands: `stand`, `sit`, `walk_to`, `turn_to`, `gesture`, `look_at`, `stop`.
- A lower controller owns gait, balance, and actuator timing.
- JROS observes state, selects goals, and handles operator interaction.

## Drone/UAV Readiness

JROS should not directly control drone motors. For UAVs, it should integrate with PX4, ArduPilot, or another flight stack through MAVLink or ROS2.

Missing pieces:

- MAVLink/PX4/ArduPilot hardware package.
- Flight mode state machine.
- Arming/disarming policy.
- Geofence support.
- Failsafe policy.
- Battery/RC/GPS/estimator health topics.
- Mission command abstraction.
- Takeoff/land/return-to-home capability gates.
- Simulator-first test path, likely SITL.

Recommended UAV model:

- JROS: mission reasoning, camera interpretation, operator chat, high-level commands.
- Flight stack: stabilization, navigation, failsafes, actuator control.
- Firmware/autopilot: hard real-time loops.

## Agent Layer Assessment

The agent layer is the mature part of the system. It has:

- Tool registry.
- Permission wrapping.
- Skill system.
- Memory.
- Local model path.
- UI bridges.
- Bus-backed permission confirmation.
- Trace/tool event surfaces.

The risk is not that the agent cannot call tools. The risk is that an unconstrained agent can call too-powerful tools. For robotics, every hardware tool must be:

- Small.
- Bounded.
- Validated.
- Audited.
- Reversible where possible.
- Refused when safety state is unknown.

The current umbrella-tool design is good because it prevents a giant list of one-off robot functions from overwhelming the model. Keep that pattern.

## Framework Strengths

1. **Correct abstraction direction.** Hardware packages make future bodies additive rather than forks.
2. **Simulation-first posture.** JP01 defaults to mock transport and testable fake firmware responses.
3. **Typed transport.** `msgspec` topics are better than ad hoc dicts for a robot bus.
4. **Capability gating.** Hardware commands are tools with permission tiers, not hidden side effects.
5. **Good shutdown instincts.** Motor neutralization and LED blanking on shutdown are present.
6. **Good honesty in safety comments.** The code does not pretend Python is hard real-time.
7. **Adapter pattern is appropriate.** Generic nodes stay generic; robot-specific knowledge lives in packages.

## Framework Weaknesses

1. **Boot/runtime fragmentation.** There are too many partially overlapping runtime paths.
2. **Hardware nodes not fully integrated into manifest boot.** They are declared but disabled in the descriptive topology.
3. **No real hardware-in-loop proof yet.** Simulation tests are good, but not enough.
4. **Control schemas are early.** Motion/light/vision are still basic.
5. **Safety gates warn instead of refusing in some live-risk situations.**
6. **No ROS2/PX4 bridge package yet.** This limits credibility for serious humanoid/UAV claims.
7. **No full robot state model.** Topics exist, but no unified world/body state abstraction is apparent yet.

## Recommended Roadmap

### Phase 1 — Make The Runtime Coherent

- Resolve bus duality.
- Make `JaegerApp`/manifest boot the active runtime path.
- Enable hardware package boot through the supervisor.
- Ensure one bus owns core, nodes, surfaces, health, and hardware.
- Add a `jaeger hardware status` or equivalent operator verb.

### Phase 2 — Harden Live Hardware Mode

- Make watchdog requirement a hard gate for live motion.
- Add explicit arming/disarming state.
- Add hardware command audit logging.
- Add command leases/timeouts.
- Add motion ack/result topics.
- Add stale heartbeat refusal.
- Add visible sim/live indicators in TUI/window/tray.

### Phase 3 — Improve Robot Capability Model

- Add topology fields for joints, frames, limits, sensors, actuator groups.
- Add standard capabilities:
  - `motion.stop`
  - `motion.hold`
  - `motion.move_joint`
  - `motion.play_trajectory`
  - `navigation.goto`
  - `head.look_at`
  - `lights.signal`
  - `vision.snapshot`
  - `telemetry.read`
- Keep capabilities small and strongly validated.

### Phase 4 — Prove JP01 Live

- Walk MC01 live with motors physically disabled first.
- Then servo-only with limits.
- Then motor command with wheels off-ground.
- Then controlled ground test.
- Record latency, command loss, shutdown, e-stop behavior.
- Add hardware-in-loop test fixtures and runbooks.

### Phase 5 — Add Drone/UAV Package

- Build `jaeger_os/hardware/packages/mavlink/` or similar.
- Target PX4/ArduPilot SITL first.
- Expose high-level capabilities only:
  - `flight.status`
  - `flight.arm`
  - `flight.takeoff`
  - `flight.land`
  - `flight.rtl`
  - `mission.upload`
  - `mission.start`
- Never expose raw motor control to the agent.

### Phase 6 — Add ROS2 Bridge

- Add a ROS2 bridge package rather than reimplementing ROS2.
- Map JROS topics/capabilities to ROS2 topics/actions/services.
- Treat ROS2 actions as long-running capabilities with feedback.
- Use ROS2 for motion/planning stacks where it is already strong.

## Final Position

JROS has the right bones. The current framework demonstrates a serious architecture:

- Local AI brain.
- Typed nervous system.
- Robot package abstraction.
- Simulation-first hardware package.
- Permission and e-stop coordination.
- Operator surfaces.

It does not yet meet the full ideal of "one OS to fully control humanoids, drones, UAVs, and agents." It can meet that ideal if "control" means high-level embodied autonomy and operator orchestration, with real-time control delegated to firmware, ROS2, PX4, or equivalent controllers.

The next important work is not more marketing language. It is making the boot path coherent, hardening live hardware gates, and proving one physical controller path safely from agent command to wire to hardware and back.

