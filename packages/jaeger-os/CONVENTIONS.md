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
