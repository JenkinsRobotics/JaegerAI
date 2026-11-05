# JaegerAI — what it is

JaegerAI is a standalone AI intelligence stack — a platform for building proactive, world-model AI companions and operators.

It is, in one line: a proactive, world-model AI companion and operator. One identity that listens, sees live, speaks to you, remembers you and your work, helps day to day, runs your projects, and eventually moves in a robotic body — with the same memory and the same enforced authority model in every case.

## What it is

- **Standalone intelligence, not a workspace, not a CAD suite, not a machine project.** JaegerAI integrates with other tools, it does not absorb them.
- **Proactive, not turn-based.** It acts from sensor events, background monitoring, and a heartbeat, not only from a prompt. It keeps a world model — a checkable model of projects, machines, and work — and it imagines what happens next before it acts.
- **A companion, not just a worker.** The same identity that talks to you is the one that knows your projects, your machines, and your work. It is one companion identity. Characters are persona packs that one companion can wear (see jaeger_ai/modules/personality/README.md) — 20 character folders in features/personality/, including work roles — not separate identities, not separate products. Personalities are a JaegerAI framework feature and stay in the stack.
- **A project operator.** JaegerAI runs your projects: content, automation, and products to sell. YouTube integration is the fastest way to get automated content working, using real engineering work, not templated content.
- **A future humanoid brain.** Robotics companies and makers can use JaegerAI as the intelligence layer for humanoid robots, building up over time from consumer-grade hardware to better units.

## What it is not

- Not a chatbot or a model wrapper. The model is a component, not the agent: MODEL != AGENT.
- Not a local-model system by default. The app/runtime runs locally on your hardware, but LLM work today uses cloud models. On-device is the goal to build toward, not a current claim.
- Not a workspace hub. Aether Suite, JROS, and the machine repos stay separate.
- Not a plugin marketplace, not a multi-agent swarm, not a custom CAD kernel, renderer, OS, or chip.
- Not a proven edge on its own. Persistence alone is not unique (Honcho and others do it), and code existing is not proof it works end to end. The edge, if it is real, is the combination below, and it must be proven by shipping.

## The edge, in combination

1. Proactive, world-model intelligence, not turn-based prompting.
2. Autonomy by default within explicit, configurable, revocable authority scopes (Tier 1 act independently / Tier 2 act and notify / Tier 3 obtain authorization), enforced at tool boundaries in code by the policy kernel — not by prompt. Simulation-first, artefact-bound approval still applies to Tier 3 physical work: simulate the exact artefact, verify deterministically, owner approves, then act, plus an independent hardware safety check. Re-plan = re-simulate + re-approve. (Corrected 2026-11-05: approval is the Tier 3 gate, not the default for all work.)
3. On-device Apple trust: memory, approvals, audit, and raw senses stay on the customer's device/NAS. See docs/TRUST.md.
4. Our own operating layer and engineering tools underneath: JROS (our ROS 2 alternative, Jaeger Robot Operating Software) and Aether Suite (CAD and simulations).
5. A real business and real machine projects underneath it, not just a demo.

## How it works with other tools

- **jaeger-agent** (in packages/, also a standalone repo): the reusable headless agent brain — loop, tools, skills, cognition, SQLite memory, sandbox, verify gate. JaegerAI depends on it. JaegerAgent must never import JaegerAI. Do not edit the inside copy and the standalone copy separately.
- **JROS / JaegerOS**: our operating layer for humanoid robots, drones, and digital agents — transport, nodes, topics, body contract, local-first on Apple Silicon / Jetson Orin.
- **Aether Suite**: CAD and simulations — Aether CAD, Aether Animation / animacore, Aether Dynamics as the simulation piece to build out.
- **NAS / file storage**: your business / content / project home, system of record for files. Configured per-instance via `config.yaml`. GitHub (or any git host) is the system of record for code.
- **YouTube / CGI tools**: available tools only (Remotion, Blender, Unreal/Unity, FFmpeg). Jaeger writes script, shot list, and checks the render; it does not build a new video engine. Channel configuration is per-instance via `youtube.toml`.
- **CNC / 3D printing projects**: completed machine projects can be used as simulation / test material, not as new product work.

## Rules that do not change

MODEL != AGENT, SESSION != AGENT, CLIENT != AGENT, DEVICE != AGENT.
PROPOSED ACTION != AUTHORIZED ACTION. TOOL SUCCESS != VERIFIED SUCCESS.
MEMORY != CONTEXT WINDOW. OBSERVATION != CLAIM != BELIEF != FACT.
ONE FACT = ONE AUTHORITATIVE OWNER.

## Authority model (vNext, agreed 2026-11-04, reconciled after the 2026-11-05 audit)

Jaeger is an **autonomous operator**, not a proposer-only chatbot. Authority is enforced in code at tool boundaries by the policy kernel (`core/authority/kernel.py`: ALLOW / DENY / MODIFY / REQUIRE_APPROVAL, fail-closed), not only in a prompt.

- **Tier 1 — act independently:** research, read files, draft content, organise non-destructively, edit authorised project files, run tests, produce **local git commits**, monitor status, restart approved services.
- **Tier 2 — act and notify:** significant failures, unexpected behaviour, material plan changes, authorised operations warranting an immediate report.
- **Tier 3 — obtain authorization:** financial transactions, external communications, public publishing, destructive actions, permission changes, physical actuation. Approved physical operations must also pass independent hardware safety checks.

**Authority grants** specify: permitted actions, resources, repositories, branches, identity, grantor, expiration / revocation conditions, and audit evidence. Specialists (ARES, Grok Bot, Muse, future) cannot escalate or inherit permissions beyond their delegated scope. **Local Git commits are Tier 1; remote pushes require an explicit grant covering the specific destination and branch.** Verification is engineering, not a human bottleneck: check authority before an action, monitor during, verify the observable outcome after, recover or report on failure. Operational learning updates operational memory; it never silently rewrites safety or permission policies.

**Human needs (J-077, reconciled):** gentle nudges only, quiet hours 22:00–07:00, never pause tasks, never contact anyone else; connection/purpose go to a daily digest. Needs do NOT outrank tasks — the implementation lives in one place, `jaeger_ai/features/human_needs/policy.py`.

**Phase 4 demo target:** autostart backend, realtime two-way voice with interruption, 10 consecutive voice exchanges, concurrent background task during conversation, memory surviving controlled restart, webcam frame understood in a voice turn, verified recovery — each with observable evidence.

## Status

This file is the current product definition, updated 2026-11-05 (vNext authority model). Supersedes the 2026-10-22 wording in which approval was the default gate for all work; that was an earlier agent's misreading, not the owner's design. Older docs that say something different (IDE-first direction, workspace hub, local-model by default, 14 characters as the product) are historical, not current, even if they are still in the tree. See docs/README.md for classification.
