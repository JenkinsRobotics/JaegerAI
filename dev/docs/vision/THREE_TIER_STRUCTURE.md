# The three-tier structure — JaegerOS · modules · projects

> Operator-ratified 2026-07-11. This is the structural north star. Every
> "where does this code/repo/boundary go" question gets tested against it.
> When this doc and reality disagree, reality wins and this doc gets edited.

## The model (the ROS analogy, applied whole)

```
JaegerOS            ← the FRAMEWORK. Like ROS: libraries + standards + tooling.
                      Bus · Node · modules/slots · supervisor · safety ·
                      contract · capability layer. You don't edit it to build
                      something — you BUILD ON it, pinned to a release.

Ecosystem modules   ← things that plug into any JaegerOS project:
                      · Jaeger AI (the Mind — the flagship module)
                      · engines (kokoro_tts, whisper_stt, …)
                      · hardware packages (jp01, future bodies)
                      · characters (souls) and module-shipped skills

Projects            ← the assembled THINGS. Each its own repo; pulls in
                      JaegerOS + whichever modules it needs; owns its bringup
                      (topology, config, instance):
                      · JP01 — the robot
                      · Jaeger Animate (future) — animatronics rigging app
                      · the desktop companion — Lilith on a Mac
```

Projects update their JaegerOS *pin*; they never fork the framework. A body,
an app, and a desktop are all just projects — "one mind, many bodies" as an
engineering claim.

## The two laws

1. **Modularize CONTRACTS early; modularize IMPLEMENTATIONS late.**
   One copy of every truth (topic names, ports, wire formats, dependency
   direction) from now — that class of drift compounds (the JP01 field week:
   every bug was two copies of one truth). Separate repos and frozen
   interfaces only when a second real consumer exists — boundaries drawn
   before two consumers are usually wrong boundaries (Phase U existed
   because two parallel "modular" stacks were the same thing).

2. **The nervous-system rule, enforced not promised.**
   Lower layers never wait on higher ones; higher layers cannot bypass lower
   safety. Concretely: `contract/` imports nothing; runtime/hardware NEVER
   import `agent/` (CI-checked); the e-stop lives below the Mind (already
   true: EStopLatch at the capability dispatcher + transport chokepoint).

## Where we are vs the model

Today's JROS repo is all three tiers stacked in one box — framework + the AI
module + one project (the desktop companion; the Mac is the first body).
That is how the tiers were DISCOVERED, not a mistake. New capabilities
already enter as modules (module.yaml + own config + tests since M1) — the
mono-repo is a shared workshop of pre-split modules, kept fast by the
pre-1.0 no-back-compat rule.

## 0.9 structural work (in order; each correct under any future)

1. **`jaeger_os/contract/`** — the ONE wire truth: topics, ports, formats,
   protocol. Depends on nothing. JP01_Firmware (Mac + Jetson sides) imports
   or vendors it — retires the drift-bug factory.
2. **CI dependency rule** — runtime/hardware/surfaces never import agent/;
   contract imports nothing. Audit + fix the handful of glue violations
   (bringup code in main.py is project-tier and exempt by definition).
3. **Out-of-tree module loading** — jp01's hardware package loads from the
   JP01_Firmware repo (the first external module; body repos are the
   template engine repos copy later). Capability layer connects Mind↔Body.
4. **Tier visibility** — the repo's layout makes framework / AI module /
   project legible so tiers can step into their own repos without surgery.

## Split triggers (repo splits happen on these, not on anxiety)

- **Jaeger AI → own repo:** a second host exists (e.g. Jaeger Animate wants
  the Mind without the desktop project), or an AI-less JaegerOS consumer.
- **Engine modules → own repos:** contracts frozen at 1.0 ("JROS 1.0 — the
  module ecosystem opens"); the slot contracts must first survive a real
  body (jp01) and one real engine swap.
- **JaegerOS rename/extraction:** when the first non-Jenkins project pins it.

## Acceptance scenario (the test the whole design must pass)

The animation rigging app: a new project repo declares its rig as a hardware
package ("rig.set_pose, timeline.play, servo.calibrate"), pins JaegerOS,
installs Jaeger AI + zero other modules. The Mind discovers the rig through
the capability layer and drives it in character. The app's dependencies
never enter the Mind's tree; the Mind's never enter the app's — they meet at
the contract. The day this works with no framework edits, the structure is
proven.
