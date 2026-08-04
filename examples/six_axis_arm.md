# Example — six-axis arm (body package)

**Verdict: needs building — the example that stresses motion safety at
scale. Joint-trajectory contract is NEW, a kinematics module is NEW,
and the safety envelope needs a workspace-limits concept the schema
doesn't have yet.**

A six-DOF arm: pick-and-place-shaped motion, not JP01's two-servo
head. Chosen to stress-test the capability layer's HARDWARE tier at
the point where "wrong command" means something can actually hit
something — six joints moving together need trajectory semantics, not
JP01's single-shot "move both joints to X, Y" call.

## Tiers used

MODULE (kinematics — mind-independent, computes joint targets from a
Cartesian goal) + PACKAGE/WORKSPACE (the arm's controller, capabilities,
workspace safety limits) + capability tiers doing real work (this is
the example where `HARDWARE` tier's confirmation flow + e-stop
coupling earns its keep, not just formally applies).

## Modules required

| Module | Status | Slot | Notes |
|---|---|---|---|
| Kinematics (IK/FK solver) | **NEW module** | `motion_planning` (**NEW slot** — proposed) | Mind-independent by design: it converts a Cartesian/joint goal into a validated trajectory, and doesn't care which mind (or none) requested it — the same separation JP01 already has between "the agent calls `motion.move_joints`" and "MC01 firmware clamps the actual angles." |
| Arm driver (the controller-facing node) | **NEW**, JP01-adapter-shaped | none (hardware-package tier, like `mc01`) | Same pattern as JP01's `adapters/mc01.py` — one adapter class per real controller. |

Kinematics `module.yaml` sketch (**NEW**):

```yaml
module: arm_kinematics
slot: motion_planning        # NEW slot — proposed
version: 0.1.0
consumes: [/act/trajectory]   # NEW topic — see below
produces: [/sense/trajectory_status]  # NEW topic — see below
tools: []                      # planning is invoked via the capability layer, not a direct tool
factory: arm_kinematics:make_planning_node
config: arm_kinematics
requires_libraries: []          # or whatever IK library is used
```

## Topics

| Topic | Status | Notes |
|---|---|---|
| `/act/trajectory` | **NEW — needed** | JP01's `MotionCommand` (`/act/motion`) is velocity-or-single-waypoint shaped (`linear_x_mps`, `target_xy`) — fine for a mobile base, wrong shape entirely for "move six joints through a timed path." A trajectory needs a sequence of joint-space (or Cartesian) waypoints with timing, not one target. |
| `/sense/trajectory_status` | **NEW — needed** | Progress/completion feedback for an in-flight trajectory (which waypoint, ETA, aborted-early flag) — nothing today plays this role; `AnimationState`/`TimelineProgress` are the closest existing *shape* (adapter + asset + progress float) but are animation-domain, not motion-domain, and carry no joint-space semantics. |
| `/sense/proprio` (consumed, not new) | **EXISTS ✓** | Already generic enough (`joints_rad`, `joints_vel_rps`) to serve as the arm's joint-feedback topic as-is — this one genuinely doesn't need a gap filled. |

## Capability declarations

This is the example where tiering has to do real work, not just be
formally present. A plausible `topology.yaml` capabilities block:

```yaml
- name: motion.execute_trajectory
  controller: arm_ctrl
  tier: HARDWARE
  schema: sixaxis.capabilities:TrajectoryArgs   # NEW schema type
  description: "Execute a validated joint trajectory within the workspace envelope."
- name: motion.stop
  controller: arm_ctrl
  tier: HARDWARE
  schema: sixaxis.capabilities:EmptyArgs
  allow_when_latched: true
  description: "EMERGENCY STOP: abort trajectory, hold position, latch e-stop."
- name: motion.status
  controller: arm_ctrl
  tier: READ_ONLY
  schema: sixaxis.capabilities:EmptyArgs
```

The tier machinery (`HARDWARE` → confirmation + e-stop fail-closed +
beta gate, same dispatch order as JP01's) carries over with **zero
framework changes** — this part of the capability layer is already
body-agnostic. What's missing is upstream of the tier check: **there's
no workspace-limits concept in the `safety:` block.** JP01's `safety:`
today is just `estop_scope` + `firmware_watchdog_required` — it says
*which controllers* stop on latch, not *what physical envelope* is
safe to move within. A six-axis arm's real safety requirement (joint
limits, a Cartesian keep-out box, self-collision avoidance) has no
home in the schema yet — today that logic would have to live inside
the kinematics module's own code with no framework-enforced,
declaratively-checked envelope, which is exactly the kind of "two
copies of one truth" `CONVENTIONS.md` law 1 warns against (the
envelope would live once in the module's Python and never be
independently checked against a declared limit).

## App/workspace shape

WORKSPACE — `topology.yaml` per above, `manifest.toml` binding both the
hardware node (factory-bound, like jp01) and the kinematics module
(slot-bound, `slot = "motion_planning"`), `unit.yaml` per unit,
`SAFETY_CHECKLIST.md` extended with a workspace-envelope walk step
(doesn't exist in the template today — see gaps).

## Framework gaps exposed

1. **No trajectory contract.** `/act/trajectory` and
   `/sense/trajectory_status` don't exist; `/act/motion`'s
   velocity/single-waypoint shape doesn't generalize to multi-joint
   timed paths.
2. **No `motion_planning` slot precedent.** This would be the first
   engine module that's mind-independent by design (JP01's tools are
   thin umbrellas over direct hardware calls; a planner is a
   nontrivial compute stage in between) — worth confirming the slot
   system's assumptions (one factory per slot, config-catalog binding)
   hold for a module that's more "algorithm" than "driver."
3. **No declared workspace/safety envelope in the schema.** `safety:`
   needs a field for physical limits (joint ranges, a keep-out
   volume, self-collision rules) that the framework can check
   independently of the module's own code — today that check, if it
   exists at all, is undeclared and unenforced at the framework level.
4. **No rate/timing guarantee for trajectory execution.** A trajectory
   is meaningless without some guarantee about how promptly the
   controller executes waypoints relative to their timestamps — the
   bus has no rate contract today (same underlying gap
   `examples/lidar_map.md` finds from the sensing side; this is its
   actuation-side twin).
