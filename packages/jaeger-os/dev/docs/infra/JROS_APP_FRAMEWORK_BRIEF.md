# JROS / Mochi / JP01-CC01 — Unified Application Framework Planning Brief

Audience: an LLM-driven planning agent. Read cold.
Output: one markdown design document — see §6.
Do not write production code. Class sketches, schemas, dir layouts inside the doc are fine.

## 1. Mission

Three Jenkins Robotics apps exist today, each with a different boot / supervisor / node-loading model. As they converge (JROS → ships on JP01-CC01 hardware; Mochi → "hardware light" reference for the Tier 3 contract; future Jaeger apps in the same family), this divergence is technical debt that compounds.

Design the unified application framework that JROS, Mochi, JP01-CC01, and future Jaeger apps all share as their chassis — the shape that defines how an app boots, supervises nodes, loads config, runs its bus, manages surfaces. Each app differs only in what it configures and which nodes it loads, not in how the app itself runs.

Implementation is gated on operator approval of your plan.

## 2. The three apps as they exist today

| App | Repo | Process model | Config | Node/plugin loading | Surfaces |
|---|---|---|---|---|---|
| JROS | ~/GITHUB/JROS | Single-process today; --attach flags on tray/voice/messaging are first daemon-attach experiments | config.yaml (warm-jobs, hardware.package) | register_package_capabilities (just shipped); tools auto-register | TUI, tray, voice window, GUI window, animation widget |
| Mochi | ~/GITHUB/Mochi | main.py + config.yaml + ZMQ broker subprocess + per-plugin subprocesses | config.yaml | Plugin subprocesses spawned via the broker; lifecycle = subprocess on/off/restart | Companion Qt window, mini-window in-process child |
| JP01-CC01 | ~/GITHUB/JP01_Firmware/controllers/JP01-CC01 (branch 2.0) | Single-process PySide6 Qt app + plugin manager (Core/ + Advanced/) | config.json (enabled_plugins) | In-process plugin managers; subsystem managers per Core plugin | Qt tabs (motion, vision, av, audio, system) |

Three boot models, three config formats, three node-loading mechanisms, three supervisor stories. The work to add a node, ship a window, or change a transport is currently different in every app.

## 3. What's already been decided (do NOT redesign)

| Decision | Where | Status |
|---|---|---|
| JROS Tier 1-4 daemon split | docs/JROS_DAEMON_ARCH_BRIEF.md | Plan in flight (other planner) — assume Tier 1 (identity daemon) + Tier 2 (subagents) + Tier 3 (hardware nodes) + Tier 4 (operator windows) as your tier vocabulary |
| JROS hardware framework (Tier 3) | dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md + jaeger_os/hardware/ | Shipped — Transport/Protocol/Link/HardwarePackage/EStopLatch already exist. The HardwareNode contract is set. |
| Animation node = Tier 3 contract reference | dev/docs/JROS_HARDWARE_INTEGRATION_BRIEF.md §6.5 | Operator standing instinct: "migrate animation node onto the framework before any physical hardware" |
| Mochi/VoiceLLM/AgenticLLM dir alignment to agent/nodes/transport/core | prior session | Shipped — the three demo apps already share JROS's top-level vocabulary |

You are not redesigning these. Your framework must accommodate them. The hardware tier 3 contract is especially fixed — your App shape must hand a node-loading hook to the existing register_package_capabilities machinery, not replace it.

## 4. The gap — what to design

A single jaeger_app (or equivalent) framework, shared by all four apps, that provides:

1. **App base / chassis.** Defines the boot sequence, signal handling, atexit teardown, top-level event loop integration (Qt for apps with windows, asyncio for headless).
2. **Supervisor / lifecycle.** Same on/off/restart shape Mochi already has for plugins, Tier 3 already has for hardware nodes, and Tier 1 needs for subagents. One model. Pluggable backend (in-process / subprocess / external host) per node — chosen by config, not by code.
3. **NodeRegistry / PluginLoader.** A node is a node — animation node, hardware node, subagent, voice node, plugin. They share one contract (start / stop / restart / health / capabilities). The framework loads them from a manifest. Mochi's plugin model + JROS's hardware-package model + JP01-CC01's enabled_plugins collapse into one shape.
4. **ConfigLoader.** One config format across all apps (yaml? json? both with a loader?). Schema-validated. Per-app config extends a common shape.
5. **Bus / IPC.** The shared transport between nodes within an app. Mochi uses ZMQ XPUB/XSUB broker; JROS Tier 3 uses an internal bus; JP01-CC01 uses Qt signals + ZMQ. Pick one or define the abstraction so each app can pick its backend.
6. **SurfaceManager / Tier 4 windows.** All three apps have operator-facing windows. Today: Mochi has companion + mini-window, JP01-CC01 has Qt tabs, JROS has TUI/tray/voice/GUI. The framework defines what a "surface" is, how it registers, how it's started/stopped.
7. **Logging + Telemetry as first-class.** One log stream shape per app. Telemetry topics defined once.
8. **Manifest for each app.** A jaeger.toml (or equivalent) at each app root declares: name, version, framework version, enabled nodes, surface set, config path, supervisor backend choice. This is what makes an app an app in the new framework.

## 5. Specific design questions you must answer

Pick a position on each. 1-3 sentence rationale per answer.

1. Where does the framework live? New top-level repo (Jaeger-Framework)? Inside JROS as a library? Pip-installable package?
2. Mochi's subprocess model vs JP01-CC01's in-process Qt model — which wins as the default? Or is supervisor backend per-node?
3. Config format unification. Mochi = yaml, JP01-CC01 = json, JROS = yaml. Pick one. Migration cost vs ecosystem preference.
4. The Node shape — does HardwareNode (just shipped) become the universal node, or does the framework define a higher Node that HardwareNode extends? This is the most load-bearing call.
5. Bus abstraction. ZMQ broker (Mochi's pattern), in-process pub/sub (JROS's pattern), Qt signals (JP01-CC01's pattern) — converge or coexist?
6. Surface lifecycle. A Qt window is heavyweight. A TUI is light. Should SurfaceManager be aware of the GUI vs headless distinction, or treat both uniformly?
7. App identity / single-instance enforcement. Mochi has "only one Dock icon" requirement, JP01-CC01 is single-process by Qt's nature, JROS spawns multiple windows. How does the framework handle this?
8. Hot reload of nodes. Standing operator instinct: nodes should be on/off/restart-able like Mochi. Universal across all node types?
9. Cross-app convergence path. When all three apps adopt the framework, do they merge into one repo? Stay separate? What's the long-term repo topology?
10. Manifest format + schema. What goes in jaeger.toml? How does it interact with config files?

## 6. Output spec

One markdown document. Save as dev/docs/JROS_APP_FRAMEWORK_PLAN.md in ~/GITHUB/JROS/.

Structure:

```
1.  Executive summary (5-10 lines)
2.  Framework overview
    2.1  Module / repo layout
    2.2  App chassis contract
    2.3  Node contract (unified — how this relates to the just-shipped HardwareNode)
    2.4  Supervisor / lifecycle (backends, restart semantics)
    2.5  Config + manifest format
    2.6  Bus abstraction
    2.7  Surface manager
    2.8  Logging + telemetry
3.  Per-app migration plans (specification only — not executed)
    3.1  JROS — current state → framework state, file map
    3.2  Mochi — current state → framework state, file map
    3.3  JP01-CC01 — current state → framework state, file map
4.  Migration sequence (which app first? why?)
5.  Future Jaeger apps — slot-in spec
6.  Position on §5 design questions (table)
7.  Open questions
8.  What I did NOT design (explicit non-goals)
9.  Risks
```

Hard rules:

- No production code in any repo. Sketches inside the doc are fine.
- File paths cited must actually exist (verify before claiming).
- Where you claim "Mochi does X" — cite the Mochi file. Same for JP01-CC01 and JROS.
- The just-shipped jaeger_os/hardware/ framework is fixed. Your Node contract must accommodate HardwareNode cleanly (likely as a subclass or specialization).
- The daemon-arch plan is in flight by another planner. Read docs/JROS_DAEMON_ARCH_BRIEF.md (the brief, since the plan isn't back yet). Your framework must NOT conflict with what that plan will produce — assume Tier 1-4 as your tier vocabulary, and design the app chassis so all four tiers fit.
- Keep doc under 1200 lines.

## 7. Standing rules

- No production code. Design doc only.
- Plan + approval before implementation — same as daemon-arch and hardware framework.
- No back-compat shims pre-1.0. Design for the right answer; don't carry legacy patterns from any of the three apps just because they exist.
- No convention ahead of code. Mark proposed names clearly (PROPOSED:).
- Truthful claims. If you cite a file, you've read it. Mark guesses [UNVERIFIED].
- Never push, never tag. Local commits OK if operator asks.
- No Claude co-author trailer. Solo authorship.
- Commit at milestones, not after every pass.
- Mochi parallels and JP01-CC01 patterns are references, not gospel. The right answer may be neither of their current models.

## 8. How to start

1. Read this brief end to end. Especially §3 (what's already decided) and §6 (output spec).
2. Read the four prior docs:
   - ~/GITHUB/JROS/docs/JROS_DAEMON_ARCH_BRIEF.md (Tier 1-4 vocabulary)
   - ~/GITHUB/JROS/dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md (Tier 3 contract — fixed)
   - ~/GITHUB/JROS/dev/docs/JROS_HARDWARE_INTEGRATION_BRIEF.md §6.5 (animation node = Tier 3 reference; same shape generalizes)
   - ~/GITHUB/JROS/dev/docs/STATUS.md (what just shipped)
3. Survey the three apps' current boot paths:
   - ~/GITHUB/JROS/jaeger_os/main.py + config.yaml
   - ~/GITHUB/Mochi/main.py + config.yaml + the broker subprocess code
   - ~/GITHUB/JP01_Firmware/controllers/JP01-CC01/main.py + config.json
4. Reason about §5 design questions before drafting. Take positions.
5. Draft the doc. Save to ~/GITHUB/JROS/dev/docs/JROS_APP_FRAMEWORK_PLAN.md.
6. Stop. Hand back the doc.

End of brief.
