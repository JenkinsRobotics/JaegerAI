# JROS as a framework — the modular north star (long-term, 0.8+)

**Status: vision / north star.** Not a spec to build now — the lens to hold when
we do major structural work (settings, nodes, plugins, hardware). Operator-set
2026-07-05.

## The one-line goal
Turn JROS from *"an agentic agent built for one application"* into *"a real
framework for building embodied agents"* — the **ROS2 for agentic robots**. A
specific robot (a drone, a humanoid, a car, a desktop companion) is a
**composition of modules**, not a fork of the codebase.

## The core principle: the framework AGGREGATES, the module OWNS
Every capability is a **self-contained module** that owns its own code, config
schema, settings, lifecycle, and tests — and *connects into* the framework
through a defined seam. The framework's job is to **aggregate and orchestrate**
modules, never to be the source of truth for what a module contains.

The mental model is macOS System Settings: the settings window is one unified
surface, but an app's settings pane is provided BY the app, not defined inside
Apple's code. JROS's unified settings surface works the same way — it *imports*
each module's settings; the definitions live in the module.

## What a "module" is (present + future)
- **Nodes** — TTS, STT, vision, animation, motor control, sensor streams. Each
  fully self-contained (own code + config + schema + lifecycle), connecting over
  the bus. A user swaps their TTS node (Kokoro → another) without touching core.
- **Plugins** — HomeAssistant, Discord, Telegram, MCP, ai-gen. Already registry-
  based; extend the same pattern.
- **Hardware packages** — a drone package, a humanoid package (JP01), a car
  package. Each brings its nodes, its config, its safety profile, its topology.
- **Agentic modules** — even the agent runner / model backend could one day be
  a swappable module (different agentic engines for different applications).
- **Skills** — already self-contained (SKILL.md + optional tools + recipe).
- **Instances** — already self-contained agent state (identity + config +
  memory + character).

A user installs / removes / updates modules like ROS2 packages or apt/npm
dependencies — and the framework composes them into one coherent agent.

## Module anatomy — the "neuron" (self-contained AND swappable)
A module is like a neuron: a self-contained cell that integrates into the whole
through standard connection points. Everything about one capability lives inside
its module folder:

- **Code** — the implementation (Kokoro synthesis, a motor PID loop, a vision
  model).
- **Settings** — its own config schema + defaults, contributed to the unified
  settings surface via its provider (it OWNS these; the framework imports them).
- **Agentic connection** — how the agent uses it: the tool(s) it exposes to the
  agent loop (e.g. a TTS node exposes `speak`), and/or the skill that teaches
  the agent to drive it.
- **Input connection** — what it consumes (bus topics it subscribes to, e.g.
  `/act/speech`; or a data/hardware input).
- **Output connection** — what it produces (bus topics it publishes, e.g.
  `/sense/speech_done`; audio out; actuator commands; health/telemetry).
- **Lifecycle** — on / off / restart / status / health, so the supervisor can
  manage it like any other node.
- **Tests** — verifies its own contract in isolation.

**The two properties that must BOTH hold:**
1. **Self-contained** — remove the folder, that capability is gone; nothing else
   breaks (graceful degradation). Add it, it wires itself in.
2. **Swappable via a standard contract** — every module of a *type* implements
   the SAME interface (same tool surface, same input/output topics, same
   settings-provider shape, same lifecycle). So "TTS = Kokoro today, XYZ
   tomorrow" is a matter of dropping in a different module that honors the TTS
   contract — the agent, the settings window, and the bus don't change. The
   contract is defined by the *slot* (a "TTS node"), not by any one
   implementation.

This is the ROS2 node/interface model: a node is a package; the interface
(topics/services/params) is the swappable boundary. JROS adds the agentic layer
— the module also declares how the AGENT talks to it.

## The federation seam (the recurring pattern)
Anywhere the framework presents a UNIFIED view over many modules, use the same
shape: a **registry of providers**, where each module contributes its slice and
the framework aggregates. Concretely, the seam carries: *identity* (which
module), *schema* (its typed config/settings), *read* (current values),
*write* (validated, persisted to the module's own file), *lifecycle*
(on/off/restart/health), *dependencies/status*.

This already exists in pieces — the tool registry (tools register themselves),
the plugin registry, the skill loader, the toolset scoping map. The work ahead
is to make it **consistent and first-class** across settings, nodes, and
hardware.

## Concrete near-term (what to keep aligned NOW)
- **Unified settings (0.7, in progress):** build the catalog as a **federation
  of providers**, not a central list. Phase 1 = the Config provider (walks the
  Pydantic schema). The seam must let a FUTURE module — a TTS node, a plugin, a
  hardware package — register its own settings provider so its settings appear
  in the unified surface without editing the framework's catalog core. Design
  the provider interface for that from the start, even while only the Config
  provider ships.
- **Node lifecycle (0.7/0.8, the archived daemon brief's Tier 3):** when
  hardware forces process isolation, nodes get ON/OFF/RESTART/STATUS + a
  manifest (`[[node]]`) — that IS module lifecycle. Format-0.1 Supervisor is the
  pattern.
- **Don't hardcode module-specific knowledge into the framework.** Every time we
  add a TTS/STT/hardware detail to core, ask: should this live in the module and
  be imported instead?

## Why this matters
Modularity is what makes JROS a *framework* rather than a single-purpose app:
different users compose different agents (different TTS/STT, different hardware,
different agentic engines) from a shared core. It's also what makes the app
FEEL like one connected system — a unified settings window, a single tray, one
coherent agent — despite being many independently-developed modules underneath.

## Related
- dev/docs/archive/JROS_DAEMON_ARCH_BRIEF.md — the four-tier model (Tier 3 =
  hardware nodes as supervised modules); re-opens when JP01 hardware lands.
- dev/docs/settings_architecture.md — the settings federation (provider seam).
- dev/docs/agentic_runners.md — the runner tiers (themselves a candidate for
  future modularity).
