# Conventions

Every repo in the Jaeger ecosystem (JaegerOS, Jaeger-AI, modules, hardware
packages, projects) follows these rules. They're condensed from
`JaegerOS/dev/docs/vision/THREE_TIER_STRUCTURE.md` — read that doc for the
full reasoning; this file is the operating checklist.

## The two laws

1. **Modularize CONTRACTS early; modularize IMPLEMENTATIONS late.**
   One copy of every truth — topic names, ports, wire formats, dependency
   direction — from day one. That class of drift compounds (a two-copies-
   of-one-truth bug is the worst kind: both copies look right in
   isolation). Don't split a boundary into a separate repo or a frozen
   interface until a *second real consumer* exists — boundaries drawn
   before two consumers are usually wrong boundaries.
   **Units are part of the contract:** every contract-type field is SI,
   with a unit-suffixed name (`_s`/`_ms`/`_m`/`_rad`/`_hz`/`_pct`) — no
   bare numeric field ships without one (see the JaegerOS vault's
   `Interfaces_And_Conventions.md` for the full convention and its one
   known gap, `sample_rate`).

2. **The nervous-system rule, enforced not promised.**
   Lower layers never wait on higher ones; higher layers cannot bypass
   lower safety. Concretely, in any repo that has both a runtime/hardware
   layer and an agent/Mind layer: the runtime/hardware layer never imports
   the agent layer, and any contract package imports nothing. This is a
   CI-checked rule, not a code-review reminder — see `.github/workflows/ci.yml`'s
   NERVOUS-SYSTEM CHECK step.

## The connection rule

Bodies **provide capabilities** · the Mind **consumes them** · the
runtime is **where they meet** · the protocol is **how outside apps reach
in**. Three connection mechanisms, pick the one that matches what you're
building:

- **Capability layer (Mind ↔ Body)** — a hardware package declares
  `capabilities:` in its topology manifest (name, controller, permission
  tier, arg schema); the framework materializes them into tools at boot.
- **Slots + `module.yaml` (Mind ↔ engine modules)** — a module directory
  declares a `slot`, its bus topics (`consumes`/`produces`), the tools it
  serves, its factory, and `requires_libraries`/`requires_platform`. This
  is what `{{package_name}}/module.yaml.example` in this template is.
- **The NDJSON protocol (outside apps ↔ the Mind)** — one wire contract,
  many transports. Never pip-dissect the agent to embed it; speak the
  protocol instead.

A simulator is a body made of math — same capability names as a real
body, so you teach in sim and deploy real with no code-path changes.

## The three repo shapes

This template scaffolds two of these; the third is documented here so
you pick the right home for new work even when this repo isn't it.

- **Module repo** — one swappable engine capability (`module.yaml` +
  `config.py` + `node.py` + tests), consumed by MANY projects through a
  **slot**. This template's `{{package_name}}/` directory is this shape.
  Reach for it when you're building something reusable across more than
  one project — a TTS/STT engine, a messaging bridge, a media backend.
- **Workspace repo** — a project that owns ONE Body's bringup:
  `topology.yaml` (capabilities + safety), `manifest.toml` (the node
  graph), `unit.yaml` (this unit's identity + live-verified gate), and
  `bringup/boot.py`. This template's `workspace/` directory is this
  shape, mirroring JaegerOS's own reference hardware package
  (`jaeger_os/hardware/packages/jp01/`). Reach for it when you're
  standing up a robot, a rig, or any other physical/simulated body —
  even a one-off, never reused by another project.
- **Suite app** — a project that owns a Mind-facing product surface
  (chat window, tray, voice), assembling JaegerOS + Jaeger AI + whichever
  modules it needs. The `jaeger.toml` / `jaeger.windowed.toml` manifest
  shapes in Jaeger-AI are the reference. **(planned)** — this template
  doesn't scaffold this shape yet; start from Jaeger-AI itself and pin
  forward rather than improvising one from a module or workspace repo.

A repo can need more than one shape as it grows (a workspace that later
extracts a reusable module), but start from whichever shape matches
today's actual need — don't scaffold a module repo for a one-off body,
and don't scaffold a workspace for something meant to be reused.

## Versioning & pinning

- Projects and modules **pin** a JaegerOS release range
  (`pyproject.toml.example`'s `dependencies`); they never fork the
  framework to make a local change.
- A **contract change** (a topic name, a `module.yaml` field's meaning, a
  wire format, the capability-layer API) is a **version bump**, not a
  patch — and needs sign-off from every affected team/repo before it
  merges. Contract packages import nothing, so they're cheap to review in
  isolation.
- Inside a repo's own boundary, delete-freely applies — no back-compat
  shims for internal refactors. At the seam between repos, the version
  bump *is* the compat guarantee.

## No spec ahead of code

A doc — README, module docs, a `module.yaml` comment — never describes
behavior the code doesn't implement yet. If it's designed but not built,
label it **`(planned)`** inline. A doc describing a phantom tool or an
unwired config field is worse than no doc: it costs someone a debugging
session before they find out it was fiction.

## STATUS stays truthful

Any commit that changes behavior updates `dev/docs/reality/STATUS.md` in
the **same commit**. STATUS.md is the one place a new contributor (human
or agent) can read to get the current truth without archaeology through
commit history. Stale STATUS.md is a bug, not a documentation nice-to-have.

## Walk the flow before shipping

Inspection is not verification. Before shipping installer, wizard, CLI,
or any user-facing flow change, actually run it start to finish as the
operator would — don't ship on "the code looks right." Patching things a
prior release already had working, discovered only after ship, burns more
trust than the extra ten minutes of walking the flow would have cost.

## Pre-1.0 note

Before this repo's 1.0, the no-back-compat-shims rule inside this repo's
own boundary is in full effect: no dual-field reads, no legacy migration
paths, no defensive code for operators who don't exist yet. Delete freely.
This note itself should be deleted once the repo cuts 1.0 and gets real
consumers who need compat guarantees.
