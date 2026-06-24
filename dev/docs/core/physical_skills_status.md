# Physical skills — status

Cognitive skills (everything the agent does in software — research,
code, memory, web, scheduling, Deep Think) are built and benchmarked.
**Physical skills are not, and can't be finished in software.** This
doc states exactly where they stand so the gap isn't a surprise.

## What exists today (scaffolding)

- **`embodiment/_interface.py`** — the `Embodiment` protocol every body
  class implements: `ActuatorCommand`, `ActuatorResult`, sensor
  `Subscription`, a `capabilities` set, `actuator_dispatch()`,
  `sensor_subscribe()`, `shutdown()`.
- **Four embodiment stubs** — `desktop/`, `humanoid/`, `ground_wheeled/`,
  `uav_quadcopter/`. Each declares a `CAPABILITIES` set; none has a
  real hardware adapter behind it.
- **The skill loader's `embodiment_requires:`** field — a skill's
  manifest can already gate it to bodies that have the needed
  capability. The gating logic is in place; there are no physical
  skills to gate yet.

## What's missing — and why it's hardware-gated

A real physical skill (walk, grasp, navigate, take off) needs three
things that don't exist in software:

1. **The robot.** Motor controllers, sensors, an IMU, power. Physical
   skills can only be written and tested against actual actuators —
   there's no meaningful way to unit-test "grasp the cup" without a
   gripper and a cup.
2. **A hardware driver / bridge.** The `Embodiment` protocol is the
   contract; behind it has to sit a real adapter — JROS or a direct
   ROS2 bridge to the motor/sensor drivers. See
   `docs/lilith/JROS_INTEGRATION.md` and `unified_architecture.md`
   §10.6 for the placement decision.
3. **A test rig.** Physical skills need a safe way to exercise them —
   a bench setup, e-stop, recorded sensor playback — before they run
   on a live robot near people.

None of that is software a coding session can produce. Building
fake/untested physical skills now would be worse than the honest gap.

## The path, when the robot is in hand

1. **Pick the body class** — `config.yaml`'s `embodiment.kind`
   (humanoid / ground_wheeled / uav_quadcopter).
2. **Write the hardware adapter** — implement the `Embodiment` protocol
   for that body: `actuator_dispatch` to the real motor driver,
   `sensor_subscribe` to the real sensor topics. This is firmware-level
   work done with the device on the bench.
3. **Author physical skills** — once the adapter works, physical skills
   are authored like cognitive ones: a folder under
   `<instance>/skills/`, `embodiment_requires:` set to the capabilities
   they need, a smoke test, a `tests/benchmark.py`. The same
   build → benchmark → revise loop applies.
4. **Safety first** — physical skills must land *after* the
   Three-Laws / safeguard stack (see the project memory). An agent
   that can move actuators needs the independent safety-review layer,
   not just the permission tiers.

## Summary

Everything software-side that supports physical skills — the protocol,
the embodiment stubs, the capability-gated loader, the benchmark
harness — is ready. The skills themselves are blocked on hardware and
should not be faked. They're the first work item once a robot is on
the bench, and they come *after* the safety stack.
