# {{REPO_NAME}} — workspace (project-tier)

> ## Replace-these checklist (delete this block once done)
>
> - [ ] `{{REPO_NAME}}` — this file
> - [ ] `{{package_name}}` — this project's own identity (used as the
>       `[app] name` in `manifest.toml.example` and the package id in
>       `requirements.txt.example`'s comments) — pick something distinct
>       from any module you depend on
> - [ ] Fill in `topology.yaml.example`'s controllers/capabilities/safety
>       to describe YOUR body, then drop the `.example` suffix
> - [ ] Fill in `manifest.toml.example`'s `[[node]]` blocks (slot bindings
>       + the hardware factory), then drop the `.example` suffix
> - [ ] Fill in `unit.yaml.example` for every physical (or simulated) unit
>       this workspace brings up, then drop the `.example` suffix —
>       `verified` stays `false` until the live walk (see
>       `SAFETY_CHECKLIST.md`)
> - [ ] Pin real tags in `requirements.txt.example`, then drop `.example`
> - [ ] Fill in `bringup/boot.py.example`'s TODOs, then drop `.example`
> - [ ] Walk `SAFETY_CHECKLIST.md` start to finish before the first live
>       (non-simulated) run

## What a workspace repo is

This is the **project tier** of the Jaeger ecosystem (see the root
[`README.md`](../README.md) and [`CONVENTIONS.md`](../CONVENTIONS.md) for
the full three-shape picture). A workspace repo:

- **pulls in** JaegerOS + whichever engine modules and hardware packages
  it needs (pinned versions — see `requirements.txt.example`);
- **owns bringup** — the topology (what controllers/capabilities exist),
  the manifest (what actually boots, and how), and the unit identity
  (which physical/simulated thing this is, and whether it's been
  live-verified);
- **never forks the framework.** If something here needs a JaegerOS
  change, that change belongs upstream in JaegerOS, pinned forward —
  not patched locally.

The reference shape this mirrors is JP01 (JaegerOS's own
`jaeger_os/hardware/packages/jp01/`) — a desk-scale robot with three
controllers (motors, lights, vision) declared in a `topology.yaml`,
bootstrapped by a `boot.py`, and consumed by the Mind through the
capability layer. A workspace repo is what JP01 looks like **outside**
JaegerOS's own tree, once a project has its own repo instead of living
inside the framework's dev workshop.

## Files in this directory

```
workspace/
├── README.md                  ← this file
├── topology.yaml.example      ← controllers, capabilities, safety —
│                                 the Body's capability declaration
├── manifest.toml.example      ← [[node]] graph: what boots, by slot=
│                                 binding, and how (tier/restart/enabled)
├── unit.yaml.example          ← the identity record for ONE physical/
│                                 simulated unit (serial, model, verified)
├── requirements.txt.example   ← the pinned-stack pattern: JaegerOS +
│                                 modules @ tag, one version truth
├── bringup/
│   └── boot.py.example        ← package-load skeleton: links → adapters
│                                 → e-stop → capabilities → runtime
└── SAFETY_CHECKLIST.md        ← walk this before any live (non-sim) run
```

## Why these five pieces, and in this order

1. **`topology.yaml`** answers "what can this body physically do, and
   under what permission tier." It's the one source the capability
   layer reads to materialize tools at boot — nothing else in this repo
   should restate a capability name, a controller port, or a tier.
2. **`manifest.toml`** answers "what actually runs in THIS process, and
   how." Same node graph shape as `jaeger.toml`/`jaeger.windowed.toml`
   in JROS — engine modules bind by `slot=`, the hardware package binds
   by a factory that loads `topology.yaml` (see Gap 1 in
   `dev/docs/roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md` upstream for
   why hardware isn't slot-bound yet).
3. **`unit.yaml`** answers "which actual unit is this, and has anyone
   walked it live." The `verified` flag is the real safety gate: an
   unverified unit's capabilities stay beta (dev-mode-only); verifying
   flips them visible to the agent for real. See `SAFETY_CHECKLIST.md`.
4. **`requirements.txt`** answers "which JaegerOS + module versions does
   this workspace actually run against." One version truth, pinned —
   never a fork.
5. **`bringup/boot.py`** is the glue: reads `topology.yaml` (and
   `unit.yaml`, once the handshake lands upstream), builds the links and
   adapters, wires the e-stop, registers capabilities, and hands back a
   runtime object the manifest's `[[node]]` factory can call and later
   shut down cleanly.

## Standalone use

A workspace boots on its own — no Studio, no external orchestrator:

```bash
python -m {{package_name}}.bringup.boot --smoke   # once boot.py is real
```

Studio (or any other tool) may author and hand over a workspace bundle,
but this repo runs it — the slicer/printer split ("Studio authors, JROS
runs") applies here too: this directory has zero dependency on anything
outside JaegerOS + its own pinned modules.

Also standard: `local_modules/` (project-unique modules — see its README; promotion path to marketplace) and `content/` (scenes/assets — data, not code).
