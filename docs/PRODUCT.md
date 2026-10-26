# JaegerAI — what it is

JaegerAI is a standalone AI intelligence stack — a platform for building proactive, world-model AI companions and operators.

It is, in one line: a proactive, world-model AI companion and operator. One identity that listens, sees live, speaks to you, remembers you and your work, helps day to day, runs your projects, and eventually moves in a robotic body — with the same memory and the same approval gate in every case.

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
2. Simulation-first, artefact-bound approval for physical work: propose, simulate the exact artefact, verify deterministically, human approves that artefact, then act. Re-plan = re-simulate + re-approve.
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

## Status

This file is the current product definition, 2026-10-22. Older docs that say something different (IDE-first direction, workspace hub, local-model by default, 14 characters as the product) are historical, not current, even if they are still in the tree. See docs/README.md for classification.

Originals of the docs edited on 2026-10-22 are on the Desktop in JaegerAI-checkpoint-2026-10-22/ — that folder is the local checkpoint for this alignment, before any git commit. No archive folder is kept in this repo, by preference.
