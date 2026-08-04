# Example — two-axis turret (JP01's head, subset)

**Verdict: mostly exists ✓ (JP01 patterns carry over directly) — gap:
no generalized servo/joint contract, so "pan/tilt" isn't a reusable
capability shape yet, only a JP01-specific one.**

A minimal body: one MCU driving two servos (pan, tilt), nothing else —
no drive motors, no lights, no vision. This is JP01's `mc01` subsystem
with the drive-motor half removed. Chosen because it's the smallest
real body that still needs the full capability-layer + safety story.

## Tiers used

NODE (a generic `motor` node, same class JP01 uses) + MODULE (none
needed beyond the built-in node type) + PACKAGE/WORKSPACE (this is the
whole point — a `topology.yaml` for one controller) + APP (whatever
face drives it — could be the same chatbot from example 2, extended
with this body's capabilities).

## Modules required

| Piece | Status | Notes |
|---|---|---|
| `jaeger_os.nodes.motor:MotorNode` (generic node class) | **EXISTS ✓** | Same class JP01's `mc01` binds to (`node: motor` in `topology.yaml`) — not a JP01-specific node, already generic. |
| An adapter translating this turret's wire protocol | **NEW**, small | JP01's own `adapters/mc01.py` is the pattern to copy — one class implementing the adapter contract for this board's specific bracket/serial protocol. |

No engine module (`module.yaml`/slot) is needed at all — this is a
pure hardware-package/workspace case, same as jp01 itself; hardware
packages don't go through `discover_modules()` today (see
`examples/jp01.md`'s framework-gaps section for the "hardware needs a
`module.yaml` too" item, which applies here identically).

## Topics

All existing — no new topic types needed for pan/tilt specifically.
`/act/motion` and `/sense/proprio` already carry joint-shaped data
(`ProprioReading.joints_rad`, `joints_vel_rps` — JP01's own MC01
proprioception schema is already multi-joint, not turret-specific).

## Capability declarations

This is where the honest gap lives. JP01's own `topology.yaml` already
proves the two-joint case — its `mc01` capability is literally:

```yaml
- name: motion.move_joints
  controller: mc01
  tier: HARDWARE
  schema: jp01.capabilities:MoveJointsArgs
  description: "Move both servo joints (MJ). Joint 1 40-150 deg, joint 2 70-105 deg, speed percent."
- name: motion.stop
  controller: mc01
  tier: HARDWARE
  schema: jp01.capabilities:EmptyArgs
  allow_when_latched: true
  description: "EMERGENCY STOP: neutralize motors (MM[0,0,0]) and latch the system e-stop."
- name: motion.status
  controller: mc01
  tier: READ_ONLY
  schema: jp01.capabilities:EmptyArgs
```

A turret-only workspace would copy this shape almost verbatim — same
umbrella name (`motion.move_joints`), same tiers, same
`allow_when_latched` pattern on stop. **But** `MoveJointsArgs` is a
**JP01-specific Pydantic model** (`jp01.capabilities:MoveJointsArgs`),
hardcoding JP01's own joint-range clamps (40-150°, 70-105°) as literal
schema bounds. A new turret project can't reuse it — it has to
redefine an equivalent model with its own ranges, under its own
package's `capabilities:` module, even though the *shape* (two named
joints, each with an angle + a shared speed) is identical. That
redefinition-per-body is the gap: there is no generic
`motion.pan`/`motion.tilt` (or a parameterized N-joint) contract type
in `jaeger_os.contract` that a body just fills in with its own ranges
— every body writes its own schema class from scratch, copy-pasting
the pattern instead of inheriting a shared one.

## App/workspace shape

WORKSPACE, exactly this template's `workspace/` shape:
`topology.yaml` (one controller, `motion.move_joints` +
`motion.stop` + `motion.status`), `manifest.toml` (`[[node]] factory =
"turret.bringup.boot:load"`), `unit.yaml` (one unit, `verified: false`
until live-walked), `SAFETY_CHECKLIST.md` walked before enabling.

## Framework gaps exposed

1. **No generalized servo/joint capability contract.** As above —
   `MoveJointsArgs`-shaped schemas get redefined per body instead of
   parameterized once (e.g. a `JointCommand` contract type taking
   `joints: dict[str, float]` against a body-supplied range table,
   rather than a bespoke Pydantic model per robot). This is the single
   biggest lever for making PACKAGE/WORKSPACE tier genuinely
   copy-paste-free for the common "N servos, some pan/tilt-shaped"
   body archetype.
2. **Hardware packages still aren't `module.yaml`-discoverable**
   (shared with `examples/jp01.md` — same underlying 0.9 roadmap item,
   Gap 1/capability-layer design). A turret workspace hits the exact
   same "not uniform with engine modules" friction jp01 does today.
