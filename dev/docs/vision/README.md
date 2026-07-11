# Vision — where JROS is going (grounded)

> The long-term picture, stated plainly. Everything here is DIRECTION, not
> commitment — the [roadmap](../roadmap/) holds what's actually next, and
> [reality/](../reality/) holds what exists. When vision and reality disagree,
> reality wins and this file gets edited.

## The triad

Jenkins Robotics builds three things that meet in the middle:
**Hardware** (JP01 and successors) · **Software** (JROS, this repo) ·
**Agentic AI** (the agent pipeline inside JROS). A product is a slice through
all three — Mochi is "hardware-light" (software + agent, minimal body);
JP01 is body-heavy (hardware + software, agent joining in 4.0).

## Mind · Body · Soul

The architecture names three swappable pillars:

- **Mind** — the agent: loop, tools, skills, memory (Hermes lineage).
- **Body** — hardware: controllers, sensors, actuators (JP01 proves it standalone).
- **Soul** — the persona: identity + character + voice (the 0.7 persona filter).

The seams are the product: Mind↔Body is the **capability layer** (a body
declares capabilities; the mind's tool surface grows when one connects —
design: [roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md](../roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md));
Soul↔Mind is the **persona filter** (built 0.7). "A sound soul dwells within
a sound mind, and a sound body."

## A ROS-style module ecosystem

Proven in 0.8: **the module IS the engine** — `kokoro_tts/`, `whisper_stt/`,
`animation/`, `media/` are self-contained folders (node + engine + config +
module.yaml + tests) bound by SLOT; swapping an engine is flipping a module.
The trajectory, in order of increasing ambition:

1. every capability a module with a declared slot contract *(done for the
   software nodes; hardware packages join after the JP01 3.0 live walk)*;
2. modules runnable standalone (per-module CLI — `jaeger run <module>`);
3. modules loadable **out-of-tree** (separate repos, individually versioned
   and updatable — the ROS 2 package-ecosystem model);
4. one day, the **Mind itself as a module**: the agent is already
   bus-attached like a node; a `mind` slot lets a different brain flip in
   while Body and Soul stay put.

## Target platforms

JROS aims to run the same framework across: Mac (today's daily driver),
robot single-board computers (JP01's Mac mini / Jetson), and eventually
drones, humanoid arms, and embodied companions — one runtime, different
manifests, different hardware packages. The Studio/JROS split (authoring
tool sends a self-contained bundle; runtime runs standalone) is the
slicer/printer rule that keeps deployments independent of the desktop.

## The operator's test

Every step toward this vision must pass the same bar the 0.8 work did:
walked flows, fail-closed gates, benches that don't regress, docs that
tell the truth. Vision earns its keep one shipped, verified seam at a time.
