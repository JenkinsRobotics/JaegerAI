# JROS / Mochi / JP01-CC01 — Unified Application Framework Plan

**Date:** 2026-06-12 (revised same day per operator feedback — see §1.1)
**Brief:** `dev/docs/JROS_APP_FRAMEWORK_BRIEF.md`
**Status:** PLAN ONLY — no production code in this round. Implementation
gated on operator approval.
**Naming:** every name introduced by this plan is `PROPOSED:` unless it
cites an existing file. Anything not yet built is labeled `(planned)`.

---

## 1. Executive summary

One **app format** — a versioned spec + reference chassis in its own
dedicated repository (PROPOSED: `Jaeger-Framework`), which every app —
JROS included — COPIES into its own tree (`jaeger_os/app/`,
`Mochi/app/`, CC01's `core/`) — becomes how every Jenkins Robotics app
is built. **Nothing is shared across repositories at runtime — no
common package, no cross-repo imports.**
Apps stay separate codebases in separate repos and each owns its copy
outright, the Microsoft-Office model: one design system, many
applications (operator decision, §1.1 item 6). The
load-bearing discovery of the survey: **the unified node contract
already exists and is already shared — by exactly this copy mechanism.**
`jaeger_os/nodes/base.py` (setup / tick / teardown / health + `NodeState`)
is the contract the hardware framework composes, the contract JP01-CC01
ported verbatim on branch 2.0 (`core/node.py`), and the contract Mochi's
`MochiNodeBase` approximates in different clothes. The framework therefore
does not invent a Node — it **promotes** the existing one, and adds the
four things no app has cleanly today: a manifest (`jaeger.toml`) that
declares what an app is made of; a supervisor with per-node backends
(thread / subprocess / external) and ON/OFF/RESTART verbs; a surface
manager that owns the event-loop question (Qt vs TUI vs headless); and one
config story (YAML, schema-validated) replacing three. The canonical app
format is **service + shell** (§2.0): a headless core that can autostart
at login, and at most one GUI shell process per app holding every window —
the Ollama/Docker-Desktop shape, held to a ten-point desktop-grade
checklist (one Dock icon, windows close together, tray, hotkey popup,
click-to-launch). Every subsystem is anchored to a named industry pattern
(launchd, systemd restart semantics, ROS 2-style node lifecycle,
liveness/readiness health) rather than to any of the three apps, and the
chassis is macOS-first by operator decision. Mochi migrates
first (lowest risk, fullest coverage), CC01 second (already the node
formation — adoption is reconciling its copy), JROS last and only in coordination
with the in-flight daemon-arch plan, whose Tier 1–4 vocabulary this design
adopts wholesale and whose jurisdiction (Tier-1 process topology, IPC verb
set) this plan deliberately does not enter.

### 1.1 Revision — the desktop-grade bar (operator, 2026-06-12)

Operator feedback on the first draft widened the mandate in two ways,
and this revision carries both:

1. **Prior decisions are inputs, not constraints.** The brief's §3
   ("do NOT redesign") is relaxed: where a single unified method is
   better, the unified method wins. Concretely this plan *keeps* the
   Node contract, the Bus family, and the hardware framework — not
   because they were decided, but because they already are the unified
   shape — and it *revises* one prior framing: the daemon brief's
   "Tier 4 = Mochi-style supervised subprocess windows" is superseded
   by the shell model in §2.0/§2.7 (per-window subprocesses are exactly
   the orphaned-window machinery the operator is debugging today).
2. **Apps must behave like real desktop applications** — Claude Code,
   Ollama, ordinary Mac software — and that bar is now §2.0, with a
   testable checklist. Operator's words: click an icon and it launches;
   create and close windows freely; one Dock/tray icon; shortcut popup;
   multiprocess IO underneath; everything closes together; optional
   auto-launch at startup. "Currently JROS feels buggy — launching
   multiple apps that sometimes don't close together; Mochi seems a bit
   better."
3. **The final format may match none of the three apps — industry
   standard wins** (operator, second pass). The design is anchored to
   named industry patterns (§2.0 table): launchd service management,
   systemd-style restart policies, ROS 2-style node lifecycle,
   liveness/readiness health vocabulary. The three apps are evidence,
   not templates.
4. **Node launch / restart / diagnose is a headline feature, not
   plumbing** (operator: "really good for multiprocess nodes for a
   humanoid robot") — §2.4 gains the operator-facing diagnose surface
   and the per-subsystem crash-isolation rationale.
5. **Platform posture: macOS-first for now.** The chassis builds against
   macOS facilities (LaunchAgent, NSStatusBar tray, Accessibility
   hotkey); the design keeps the seams portable (the robot's Jetson side
   is Linux and already lives behind the `external` backend), but no
   Linux/Windows chassis work ships in v1.
6. **The framework is a FORMAT, not a shared dependency** (operator,
   third pass): "I don't necessarily want a standalone jaeger app…
   these different repos are different apps. I just want a consistent
   framework on how to design an app… I will copy that framework to
   each app — similar to how Microsoft Office works: a consistent app
   format, but Excel, Word, PowerPoint all run as different codebases."
   So: one **spec** (the app format this document defines) + one
   **reference implementation** that each app *copies* into its own
   tree — the distribution mechanism the demo apps and CC01 already
   use. No cross-repo imports, no editable installs, no shared library.
   §2.1 is rewritten accordingly, and prior-draft language about
   `pip install -e` consumption is dead.
7. **ROS 2-inspired node organization; clean directories** (operator,
   fourth pass): "stuff that acts like nodes should be organized within
   the nodes folder, and within that: hardware, software, etc. — I do
   want our repository to be clean and clear organization." The format
   gains a directory convention (§2.3): everything node-shaped lives
   under `nodes/`, categorized; wire machinery and frameworks live
   elsewhere. §3.1 carries the concrete JROS `nodes/` reorg map — a
   mechanical, suite-verified move that can ship ahead of the rest of
   the framework on operator OK.
8. **The format gets its own repository** (operator, fifth pass:
   "that's just a format — so it should be its own repository").
   PROPOSED: a dedicated repo (working name `Jaeger-Framework`, the
   brief's own Q1 suggestion; final name = open question 3) holding the
   spec, the pristine reference chassis, conformance tests, a skeleton
   app template, and the format changelog. EVERY app — JROS included —
   copies from it; none import from it. §2.1 rewritten accordingly.
9. **The shell contract is UI-toolkit-agnostic** (operator, fifth
   pass): each app picks ONE toolkit and stays consistent — PySide6 as
   the cross-platform reference, or native Swift on macOS — but both
   implement the same shell contract (§2.7). Split mode is what makes
   this free: the shell is a client of the core, so the toolkit is
   swappable; `apps/JROS-Avatar/` (Swift, attaching to the Python core
   over the animation bridge) is the in-tree proof.

---

## 2. Framework overview

### 2.0 The canonical app format — service + shell

The shape that satisfies §1.1 is the one mature local-AI apps already
use (Ollama: menu-bar app + `ollama serve`; Docker Desktop: GUI +
daemon; Claude Code: terminal client + background services):

```
┌─ shell ──────────────────────────────┐   ┌─ core (service) ───────────────┐
│ ONE GUI process per app:             │   │ headless: bus + supervisor +    │
│  • one Dock icon (one QApplication)  │◄──┤ nodes (thread/subprocess/       │
│  • ALL windows live here — created   │IPC│ external backends), single      │
│    and closed freely at runtime      │   │ instance, optional autostart    │
│  • tray/menu-bar icon                │   │ at login (LaunchAgent on macOS) │
│  • global-hotkey quick popup         │   │ (planned)                       │
└──────────────────────────────────────┘   └────────────────────────────────┘
```

Two manifest modes `(planned)`:

- **`mode = "fused"`** — shell and core in one process (CC01 today;
  simple apps). Same code, no IPC hop.
- **`mode = "split"`** — core runs as a service (auto-startable,
  survives shell exit if configured); the shell attaches. This is the
  JROS daemon target and the Ollama shape. Whether closing the shell
  stops the core is per-app: `shell_quits_core = true` (Mochi instinct:
  close companion = quit everything) or `false` (JROS: Lilith keeps
  running headless).

**The desktop-grade checklist** — each item is an acceptance test for
the framework, not aspiration; an app on the chassis gets these from
shared code, not bespoke wiring:

| # | Behavior | Where it lands |
|---|---|---|
| 1 | Click an icon → app launches (no terminal required) | launcher entry + .app bundling `(planned)`, §2.2 |
| 2 | One Dock icon no matter how many windows | one shell QApplication, §2.7 |
| 3 | Create / close windows freely at runtime | shell WindowManager, §2.7 |
| 4 | Quit → *everything* dies (no orphan windows/processes) | process-group teardown, §2.2 |
| 5 | Tray / menu-bar icon as a standard surface kind | §2.7 (JROS `interfaces/tray` generalized) |
| 6 | Global-hotkey summon popup (Claude Code style) | quick-summon surface `(planned)`, §2.7 |
| 7 | Multiprocess IO (nodes send/receive over the bus) | §2.4 backends + §2.6 bus |
| 8 | Second launch doesn't double the app | single-instance slot → attach, §2.7 |
| 9 | Optional auto-launch at startup | autostart manifest key → LaunchAgent, §2.2 |
| 10 | Same format for every app ("sure shot") | the manifest + chassis, §2.2/§2.5 |

**Industry anchors.** Per §1.1 item 3, each chassis subsystem follows a
named industry pattern — none is invented here, and none is inherited
from the three apps just because it exists:

| Chassis subsystem | Industry pattern it follows |
|---|---|
| Service management (split-mode core) | macOS `launchd` LaunchAgent — the platform's own service manager, not a custom daemonizer (`jaeger_os/daemon/_child_entry.py`'s spawn-not-fork lesson stays) |
| Restart policy | systemd semantics: `Restart=never/on-failure/always`, exponential backoff, burst limit (`StartLimitBurst` analog) |
| Node lifecycle | ROS 2 managed-node lifecycle — §2.4 maps `NodeState` onto it; keeps a future `ros2_bridge` (hardware plan §6 Q3) mechanical |
| Health vocabulary | Kubernetes-style split: *liveness* (heartbeat on `/sense/node_health`) vs *readiness* (`check_fn` availability — already shipped in `jaeger_os/hardware/capabilities.py`) |
| Manifest | `pyproject.toml` conventions: TOML, static, declarative, versioned `requires_framework` |
| Service + shell topology | Ollama (`ollama serve` + menu-bar app), Docker Desktop (daemon + GUI) |
| Single instance + attach | The LSP/daemon-client pattern: socket + PID file, second client attaches |

**Platform posture (§1.1 item 5): macOS-first.** Tray = NSStatusBar via
the existing Qt tray code (`jaeger_os/interfaces/tray/macos.py`),
autostart = LaunchAgent, hotkey = macOS event tap behind the
Accessibility grant. Portability is preserved at the seams (these are
each one module behind a small interface), but Linux chassis support is
explicitly deferred — the Linux that matters today is the robot's Jetson,
which participates as `external`-backend nodes over the bus, not as a
chassis host.

### 2.1 The format, the reference, and the copies

**Position (§5 Q1, revised per §1.1 item 6): the framework is a spec +
reference implementation, distributed by COPY.** Three artifacts:

**There is no shared `jaeger_app` package, library, or standalone app —
that name is retired from this plan.** Nothing crosses a repo boundary
at runtime, ever. What exists instead (per §1.1 items 6+8):

1. **The format repository** — PROPOSED: `~/GITHUB/Jaeger-Framework`
   (name = open question 3), a new dedicated repo that is *only* the
   format. It holds the spec, the pristine reference chassis, the
   conformance tests, a skeleton app template, and the changelog. No
   app code lives here; nothing imports from here; it is the place you
   COPY FROM:

   ```
   Jaeger-Framework/                (PROPOSED — all of it)
   ├── docs/JAEGER_APP_FORMAT.md    ← the spec, versioned (format 0.1);
   │                                   §2 of this plan is its first draft
   ├── app/                         ← the reference chassis (layout below)
   ├── tests/test_app_format.py     ← conformance tests, copied with app/
   ├── template/                    ← skeleton new-app: jaeger.toml,
   │                                   config.yaml, main.py, nodes/…
   └── CHANGELOG.md                 ← per format version: which modules
                                       changed, so re-copying is a diff
   ```

2. **Each app's own chassis directory** — PROPOSED: `app/` inside each
   app's package, that app's copy of the reference: `jaeger_os/app/`,
   `Mochi/app/`, CC01 keeps `core/`. Every app — **JROS included** —
   copies from the format repo and owns its copy outright. Every app's
   `jaeger.toml` declares `requires_framework = ">=0.1"` against the
   spec version it implements.
3. **Upstreaming keeps the reference alive.** Fixes and improvements
   are usually discovered inside an app (JROS will find most, having
   the test discipline — 2,182 passing, `dev/docs/STATUS.md`); they are
   upstreamed to the format repo, the changelog entry is written, and
   other apps re-copy when they choose. The format repo's own tests run
   standalone (the chassis is dependency-light by rule), so the
   reference is verifiable without any app present.

Office model, stated plainly: Word, Excel, and PowerPoint are different
codebases sharing a design system. Mochi, CC01, and JROS are different
apps sharing an app format. A bug fixed in the reference copy propagates
by re-copying the affected module into the other apps and re-running
their conformance tests — deliberate, visible, per-app — not by a
version bump rippling through three repos overnight.

What makes the chassis directory copy-able is the same rule that made
CC01's port painless: **its modules import only the stdlib, pyyaml,
optional pyzmq/msgspec, and each other (relatively)** — never the rest
of the host app. Paste the directory anywhere and it works. An
import-lint test enforces this the same week the directory lands
(standing rule — no convention ahead of code).

```
app/                      ← in the format repo, AND as each app's copy
│                           (JROS: jaeger_os/app/, Mochi: Mochi/app/ …)
├── __init__.py           ← surface pin + FRAMEWORK_FORMAT version stamp
├── app.py                ← App chassis (§2.2)
├── node.py               ← Node + NodeState (§2.3 — JROS: promoted from
│                            jaeger_os/nodes/base.py)
├── supervisor.py         ← NodeHandle + backends + restart policy (§2.4)
├── manifest.py           ← jaeger.toml loader + validator (§2.5)
├── config.py             ← YAML config loader + schema hooks (§2.5)
├── bus/
│   ├── api.py            ← Bus ABC (JROS: from jaeger_os/transport/bus.py)
│   ├── inproc.py         ← InProcBus (JROS: from transport/inproc_bus.py)
│   ├── zmq.py            ← ZMQBus + Broker (JROS: from transport/{zmq_bus,broker}.py)
│   └── codec.py          ← JSON/MessagePack codec (JROS: from transport/codec.py)
├── surfaces.py           ← SurfaceManager (§2.7)
├── health.py             ← NodeHealth publishing + HostMonitor-style cache (§2.8)
└── logging.py            ← log stream shape (§2.8)
```

Rules of the copy:

```
the format repo  is the single copy-from source for every app, JROS included
every app        owns <its package>/app/ completely; renames allowed
                 (CC01 may keep core/) — the spec names contracts, not paths
every copy       internal imports are RELATIVE; nothing outside the dir
                 except stdlib/pyyaml/optional pyzmq+msgspec
every copy       carries a FRAMEWORK_FORMAT version stamp + the copied
                 conformance test file, runnable in that app's own venv
improvements     upstream from apps to the format repo (+ changelog entry),
                 then propagate outward by deliberate re-copy
NO repo          imports chassis code from another repo. Ever.
```

What gets *promoted* vs *referenced* inside JROS: the Bus family and
Node base move into `jaeger_os/app/` and the old paths re-export them in
the same change-set (alias modules — JROS has one implementation, its
own). The hardware framework (`jaeger_os/hardware/` — fixed, shipped)
stays where it is because it is JROS's Tier-3 stack, not chassis; the
chassis reaches it through the node-loader hook (§2.3). Other apps never
receive the hardware framework in their copy — it isn't part of the
format.

The conformance tests are part of what gets copied: a single test module
(PROPOSED: `test_app_format.py`) exercising the spec'd contract — boot
phase order, node lifecycle states, supervisor verbs, manifest
validation, teardown-reaps-everything — against whichever copy it sits
next to. CC01's `tests/test_node_formation.py` (16 tests, branch 2.0) is
the working prototype of exactly this idea.

### 2.2 App chassis contract

What the survey found, so the chassis is shaped by real boots:

- **JROS** boots through `launch.py` → in-process TUI (the 2026-06-05
  revert documented in `launch.py`'s docstring), takes a singleton slot
  (`jaeger_os/core/runtime/process_slot.py: acquire_slot/acquire_slot_exclusive`),
  installs the permission policy, runs warm jobs (`jaeger_os/main.py:
  _warm` — STT/TTS/vision/avatar/hardware-package), and lazy-boots nodes
  through module-level singletons (`jaeger_os/nodes/runtime.py:
  ensure_tts_node / ensure_audio_session_node / ensure_animation_node`).
  A parked daemon exists (`jaeger_os/daemon/`: NDJSON over a Unix socket,
  `server.py: Server.register(op, fn)`, `lifecycle.py` PID-file
  start/stop/status, `attach.py`) plus piecemeal `--attach` flags
  (`jaeger_os/plugins/voice_loop.py`, `jaeger_os/plugins/messaging_gateway.py`,
  `jaeger_os/interfaces/tray/macos.py`).
- **Mochi** boots through `main.py: run_host()` — load `config.yaml`,
  start `core/host_monitor.py: HostMonitor` (SUB cache + REP queries),
  spawn `transport/broker.py` (XPUB/XSUB proxy) as a subprocess, then
  spawn each enabled plugin from `core/plugin_registry.py: PluginSpec`
  via `subprocess.Popen`, then poll every 5 s and tear down children on
  exit.
- **JP01-CC01** (branch 2.0, commit `18ed304`) boots through `main.py:
  main()` — validate `topology.yaml` (`core/topology.py`), start
  `InProcBus` (`core/bus.py`), run `JetsonLinkNode` + `StreamRxNode` on
  daemon threads, then hand the main thread to Qt with tabs wired through
  a `BusBridge` (bus callback → Qt signal).

Three boots, one underlying sequence. PROPOSED chassis (sketch, not code):

```python
class JaegerApp:                                    # PROPOSED
    """manifest → config → bus → nodes → surfaces → run → teardown"""
    def __init__(self, manifest_path): ...
    # boot phases, in order, each overridable but rarely overridden:
    #  1. load_manifest()      jaeger.toml → AppSpec (validated)
    #  2. acquire_instance()   single-instance slot (process_slot pattern)
    #  3. load_config()        config.yaml → app schema (validated)
    #  4. build_bus()          backend per manifest [bus]
    #  5. start_nodes()        Supervisor starts [[node]] entries by tier order
    #  6. start_surfaces()     SurfaceManager; main surface claims the main thread
    #  7. run()                event loop (qt | asyncio | tui | none)
    #  8. shutdown()           reverse order; signal-safe; atexit-registered
```

Contract points (each is an observed pain in at least one app today):

- **Signals + atexit are chassis-owned.** SIGTERM/SIGINT → `shutdown()`;
  the atexit net mirrors what `jaeger_os/hardware/packages/jp01/boot.py`
  does for motors/LEDs today. Nodes never install their own process-level
  handlers when chassis-managed (the `install_signal_handlers=False`
  convention in `jaeger_os/nodes/base.py` already anticipates this).
- **Orphan-proof teardown (checklist #4 — the "sure shot" rule).** Every
  child process the chassis spawns goes into the app's own process group
  and into a PID registry on disk; `shutdown()` walks the registry with
  Mochi's terminate→kill escalation (`Mochi/main.py: run_host` finally
  block is the precedent), then `killpg` sweeps anything that escaped.
  Next boot, the chassis reaps stale registry entries before taking the
  slot — so even a SIGKILL'd app can't leave yesterday's windows running.
  JROS's "launched multiple apps that sometimes don't close together" is
  this bug class; the fix is structural (group + registry), not
  per-surface diligence.
- **Autostart (checklist #9) `(planned)`.** `autostart = true` in the
  manifest (split mode only — what autostarts is the *core*, never a
  window) installs/uninstalls a per-app macOS LaunchAgent plist via a
  chassis verb (`<app> autostart on|off`). The shell then attaches to
  the already-running core at login the same way a second launch does.
- **Click-to-launch (checklist #1) `(planned)`.** The chassis exposes one
  console entry per app (`python -m <app>` reading `jaeger.toml`), and a
  thin .app bundling recipe wraps it for Finder/Dock launch. Bundling
  details (icons, signing) are out of scope (§8); the contract here is
  only that launching never *requires* a terminal.
- **Event-loop ownership is declared, not discovered.** The manifest's
  `event_loop = "qt" | "asyncio" | "tui" | "none"` decides what `run()`
  blocks on. Qt apps get `QApplication` constructed by the chassis on the
  main thread before any surface exists (the CC01 main.py shape); headless
  apps get an asyncio loop; the JROS TUI keeps owning its terminal.
- **Boot is best-effort per node, fail-fast per chassis.** A dead node
  degrades (its capabilities fail closed — the `check_fn` pattern already
  shipped in `jaeger_os/hardware/capabilities.py`); a broken manifest or
  config refuses boot loudly with the offending field named (the
  `core/topology.py` / `jaeger_os/hardware/package.py` posture).
- **Teardown is reverse boot order and idempotent** — surfaces, then
  nodes (supervisor joins them), then bus close, then slot release. The
  operator's "I closed the application and the windows are still up"
  complaint (daemon brief §1) is a chassis bug class, killed here.

### 2.3 Node contract (unified)

**Position (§5 Q4 — the load-bearing call): the universal Node is the
existing `jaeger_os/nodes/base.py` contract, promoted to
the chassis's `app/node.py` unchanged (JROS: `jaeger_os/app/node.py`).**
A correction to the brief's framing:
nothing named `HardwareNode` shipped. What shipped is *generic* nodes
(`jaeger_os/nodes/{motor,light,vision}/node.py`) subclassing
`nodes/base.Node`, plus hardware-package machinery
(`jaeger_os/hardware/package.py`, `capabilities.py`) that *composes* that
Node with adapters and links. So there is no "does HardwareNode become
universal" fork in the road — the universal node already exists and the
hardware framework already builds on it. Evidence it generalizes:

| Consumer | File | Relation to the contract |
|---|---|---|
| JROS animation node | `jaeger_os/nodes/animation/node.py` | `class AnimationNode(Node)` — already conformant; the §6.5 "migrate animation first" instinct is already satisfied at the class level |
| JROS voice/TTS/audio | `jaeger_os/nodes/{tts,audio_session,stt}/` | `Node` subclasses, run by `nodes/runtime.py` singletons |
| JP01 hardware nodes | `jaeger_os/hardware/packages/jp01/boot.py` | Stock `MotorNode`/`LightNode` over package adapters |
| JP01-CC01 | `controllers/JP01-CC01/core/node.py` | Verbatim port (branch 2.0) |
| Mochi animation | `Mochi/nodes/animation/node.py` | `MochiNodeBase` — same lifecycle, different spelling (§3.2 maps it) |

The contract, restated as the framework's (existing semantics, no
redesign): `setup()` once; `tick()` repeatedly (default sleeps);
`teardown()` always runs; `health() -> dict`; `NodeState` INIT →
SETTING_UP → RUNNING → STOPPING/RESTARTING → STOPPED/FAILED; tick errors
are transient, setup errors are fatal; `stop()` graceful + idempotent.

Two framework-level additions `(planned)`:

1. **`FrameNode(Node)`** — PROPOSED: a thin specialization for
   render-loop nodes: fixed-rate `tick()` scheduling plus an
   `_update_tick/_render_tick` split, so Mochi's `MochiNodeBase`
   subclasses migrate mechanically (its abstract methods map 1:1; its
   health payload fields — fps target, memory, tx rate — move to
   `health()` details). Nothing in JROS needs it on day one; it exists so
   Mochi's migration is a rename, not a rewrite.
2. **The node-loader hook** — a manifest node entry names a factory
   (`module:callable`) that returns either a `Node` instance or a list of
   them. `jaeger_os/hardware/boot.py: boot_hardware` already has exactly
   this shape (package name → runtime with nodes + tools); the manifest
   entry for JROS's hardware tier is a *reference to it*, not a
   replacement of it — `register_package_capabilities` keeps owning
   capability→tool registration, per the brief's hard rule.

What is deliberately NOT a Node: Tier-2 subagents and Tier-4 windows that
run as subprocesses. They are supervised through the same *handle*
contract (§2.4) but their in-process internals are their own business —
forcing a Qt window to implement `tick()` would be ceremony. A node is the
in-process implementation shape; the handle is the universal lifecycle
shape.

**Directory convention (§1.1 item 7) — the nodes/ tree.** ROS 2-inspired
twice over: the lifecycle mapping (§2.4) and now the workspace shape —
everything node-like lives under one `nodes/` tree, organized by
category, the way a ROS workspace organizes packages:

```
<app>/nodes/
├── base.py          # the Node contract (the format's copy)
├── hardware/        # nodes that own a physical device through a link
│   └── <node>/      #   (motor, light, camera …)
├── software/        # nodes whose device is compute — render, audio
│   └── <node>/      #   pipelines, ML stages …
└── <category>/      # apps add categories as needed (sensor/, comms/ …)
```

Three rules keep it clean and decidable:

1. **Acts like a node → lives in `nodes/`.** No node classes scattered in
   `plugins/`, `core/`, or `gui/`.
2. **Wire machinery is not a node — and it is named `middleware/`**
   (operator, 2026-06-12: "the top-level hardware is about protocols
   and doesn't actually control end devices — so it's middleware").
   Transports, protocols, links, and the topology loader stay outside
   `nodes/` under `middleware/` — the layer that CONNECTS nodes to
   devices, never the device controller. The first draft kept JROS's
   `hardware/` name and called the `hardware/` vs `nodes/hardware/`
   collision "intentional and readable" — the operator tripped on it
   within a day, which settles that. In JROS, `jaeger_os/hardware/`
   (the shipped framework) renames to `jaeger_os/middleware/` in the
   same mechanical commit as the `nodes/` reorg (§3.1); "middleware"
   is also the industry's own word for this layer (ROS bills itself
   as robot middleware).
3. **Categories appear when they pay.** RECOMMENDED at ≥4 nodes;
   an app with two nodes (CC01 today) may stay flat — the format
   mandates the `nodes/` root, not empty subdirectories.

Borderline calls get decided by what the node *owns*: vision owns a
physical camera → `nodes/hardware/`; animation's surface is a screen
widget → `nodes/software/` — while remaining the Tier-3 contract
reference ("hardware light," §6.5 of the integration brief). The
category is an organizational fact, not a contract difference: both
are the same Node.

### 2.4 Supervisor / lifecycle

**Position (§5 Q2): backend per node, declared in the manifest; default
`thread`.** The evidence cuts against a subprocess default: JROS reverted
to in-process as its main path (`launch.py` docstring), CC01 is in-process
and correct for an operator console, and the daemon brief's anti-pattern
#1 is "making everything a subprocess because it feels more modular."
Mochi's subprocess isolation is right where it is used — crash-isolated
renderer + GUI — and stays available per node.

PROPOSED `NodeHandle` — the one lifecycle surface regardless of backend:

```
NodeHandle                       # PROPOSED — what the supervisor holds
  .id, .kind, .tier, .backend
  .start()  .stop()  .restart()  .state  .health() -> dict
```

| Backend | Implementation | Today's precedent |
|---|---|---|
| `thread` (default) | `Node` instance on a daemon thread; stop = `node.stop()` + join | `jaeger_os/nodes/runtime.py`; CC01 `main.py`; `jp01/boot.py:_start_nodes` |
| `subprocess` | `Popen` from a PluginSpec-shaped launch block; stop = terminate→kill escalation; health via bus heartbeats | Mochi `core/plugin_registry.py: PluginSpec/PluginProcess` + `main.py` teardown |
| `external` | not launched, only observed — a process something else owns (the Jetson's VCC01 services) registers health and capabilities but has no start/stop | JP01 topology's `vcc01` controller is the motivating case `(planned)` |

Restart semantics (§5 Q8): **ON/OFF/RESTART is universal across node
kinds; hot *code* reload is not.** Restart means teardown + fresh start
(thread: stop/join/new instance; subprocess: kill/respawn) — never
importlib gymnastics. Per-node manifest policy follows systemd's
vocabulary: `restart = "never" | "on_failure" | "always"`, exponential
backoff between attempts, and a burst limit (N restarts in M seconds →
mark FAILED and stop trying; today Mochi just breaks its poll loop on
the first dead child, `main.py: run_host`). The supervisor exposes the
verbs programmatically; *who* may call them (operator CLI, tray menu,
agent tool) is surface wiring per app — JROS's agent-tool wrapper for it
belongs to the daemon plan's jurisdiction, not this one.

**Diagnose is a first-class verb (§1.1 item 4).** The operator surface
ships with the supervisor, not later `(planned)`:

```
<app> node ls                        # id, kind, tier, backend, state, uptime, restarts
<app> node status <id>               # health() snapshot + readiness + last error
<app> node restart|stop|start <id>
<app> node diagnose <id>             # status + last N log lines + restart history
                                     #   + crash-loop verdict, one screen
<app> node logs <id> [-f]
```

The same data feeds the shell's diagnostics window and (in JROS, via the
daemon plan) an agent tool — three views over one supervisor + health
cache. This is the humanoid-robot payoff the operator named: each
subsystem (gait, arms, vision, voice) runs as its own supervised node —
subprocess-backed where a crash must not take its neighbors — and a limb
controller that dies restarts under policy, visibly, without rebooting
the robot's identity.

**Node lifecycle ↔ ROS 2 managed nodes.** The shipped `NodeState`
(`jaeger_os/nodes/base.py`) maps onto the industry-standard lifecycle
almost 1:1, which is the §1.1-item-3 evidence that the contract is
already industry-shaped — and what keeps a future `ros2_bridge` node
mechanical rather than architectural:

| jaeger NodeState | ROS 2 lifecycle analog |
|---|---|
| INIT | Unconfigured |
| SETTING_UP (`setup()`) | Configuring → Inactive |
| RUNNING (`tick()`) | Active |
| STOPPING (`teardown()`) | Deactivating / CleaningUp |
| STOPPED | Finalized |
| FAILED | ErrorProcessing → Finalized |

No rename ships now (no churn for vocabulary's sake); the mapping is
documented so the contract stays convertible.

Mid-turn restart, graceful degradation, and "a node restart must not
crash Tier 1" are already solved at the capability layer
(`jaeger_os/hardware/capabilities.py` — offline → typed retryable error;
`check_fn` hides dead tools): the supervisor only has to keep `health()`
truthful and the existing machinery does the rest.

### 2.5 Config + manifest format

**Position (§5 Q3): YAML for config.** All three apps already speak it —
JROS instance config (`sandbox/.jaeger_os/instances/jros-dev/config.yaml`,
schema `jaeger_os/core/instance/schemas.py: Config`, pydantic
`extra="forbid"`), Mochi `config.yaml`, CC01 `topology.yaml` (validated by
`core/topology.py`). CC01's `config.json` is already dead — branch 2.0
retired it. Nothing to unify that isn't already unified; the framework
just makes the loader + "refuse loudly with the field named" posture
shared code.

**Position (§5 Q10): TOML for the manifest, YAML for config, and the split
is by mutability.** The manifest answers *what is this app made of* —
structural, edited when the app's shape changes, read once at boot. Config
answers *how should those parts behave* — tunable, per-instance,
per-robot. Mochi's `config.yaml` currently mixes both (infrastructure +
plugin list + per-plugin tuning); the JP01 topology keeps them cleanly
apart (structure in `topology.yaml`, behavior knobs per capability). TOML
for the manifest matches the `pyproject.toml` convention and resists the
templating/anchor temptation YAML invites.

PROPOSED `jaeger.toml` (sketch — schema + validator ship together, same
week, per standing rule):

```toml
[app]
name = "mochi"
version = "0.9.0"
requires_framework = ">=0.1"     # same load-time refusal contract as
event_loop = "qt"                # jaeger_os/hardware/package.py
mode = "fused"                   # "fused" | "split" (§2.0)
ui = "pyside6"                   # "pyside6" | "swift" | "tui" — ONE per app (§2.7)
single_instance = true
autostart = false                # split mode: install a LaunchAgent
shell_quits_core = true          # split mode: closing the shell stops the core
config = "config.yaml"

[bus]
backend = "zmq"                  # "inproc" | "zmq"
# zmq-only:
xpub = "tcp://127.0.0.1:5555"
xsub = "tcp://127.0.0.1:5557"

[[node]]
id = "animation"
tier = 3
backend = "subprocess"
module = "nodes.animation.node"  # subprocess: spawn `python -m`
restart = "on_failure"           # systemd vocabulary: never|on_failure|always
config_key = "animation"         # its slice of config.yaml
enabled = true

[[node]]
id = "jp01"
tier = 3
backend = "thread"
factory = "jaeger_os.hardware.boot:boot_hardware"   # the loader hook
args = { package = "jp01" }

[[surface]]
id = "companion"
main = true                      # owns the main thread / event loop
entry = "gui/mochi_companion.py"
```

Precedence and interaction: manifest fields never appear in config;
config never declares nodes. `enabled` lives in the manifest (it changes
the app's shape); a node's *tunables* live under its `config_key` in
config.yaml. CLI flags > env > config.yaml > defaults, and the manifest
is not overridable at runtime — if you want a different shape, you edit
the manifest (or ship a second one: `jaeger.toml` vs `jaeger.sim.toml` is
the sanctioned way to ship a simulation profile).

### 2.6 Bus abstraction

**Position (§5 Q5): converge on JROS's `Bus` ABC; backend per app; Qt
signals are not a bus.** This is the most already-decided question of the
ten. JROS ships the abstraction *and both backends* today:
`jaeger_os/transport/bus.py` (ABC: publish / subscribe / unsubscribe /
request), `inproc_bus.py` (queue + delivery thread), `zmq_bus.py`
(`class ZMQBus(Bus)`), **and** `broker.py` (`Broker`, XPUB/XSUB defaults,
`make_bus_for_node`) — Mochi's broker pattern is already ported behind
the same interface. CC01 ported `InProcBus` verbatim. The framework
places this family in the chassis directory (`app/bus/`; JROS:
`jaeger_os/app/bus/` with the old transport paths re-exporting).

- **Topic vocabulary:** JROS's typed `/sense/*` `/act/*` namespace
  (`jaeger_os/topics.py`, `TOPIC_TO_CLASS` registry) is the shape; CC01
  already adopted it. Mochi's dotted `node.<id>.health` / `sys.*` / `ext.*`
  (`Mochi/transport/topics.py`) maps onto it at migration
  (`node.<id>.health` → `/sense/node_health`, which exists:
  `jaeger_os/topics.py: NodeHealth`). The framework's chassis-owned
  topics are exactly the health/lifecycle/log set (§2.8); app domain
  topics stay app-owned.
- **Qt's place:** CC01's `BusBridge` (`controllers/JP01-CC01/main.py` —
  bus subscriber → Qt signal emit, the one thread-safe hop into widget
  land) is the sanctioned pattern, promoted into the framework's surface
  layer `(planned)` rather than reinvented per app.
- **Frames and other big payloads** ride the bus where they already do
  (Mochi publishes rendered frames through the broker; CC01 publishes
  H.264 bytes on `/sense/video`) — with the codec layer
  (`jaeger_os/transport/codec.py`: JSON for text topics, MessagePack for
  binary) promoted alongside. Anything faster than that (UDP video) stays
  off-bus, per the hardware plan's existing position.

### 2.7 Surface manager — the shell

**Position (§5 Q6, revised per §1.1): windows are not processes. Each app
has at most ONE GUI shell process; every window is an in-shell Qt window
the shell's WindowManager creates and closes at runtime.** This
supersedes the daemon brief's "Tier 4 = Mochi-style supervised
subprocesses" framing — per-window subprocesses are precisely how windows
get orphaned and Dock icons multiply, and Mochi itself already walked
this back for its mini-window (`gui/mochi_companion.py:
build_mini_window` — in-process child, "single Dock icon, closes with
parent"). Subprocess surfaces remain only as the *exception* for
isolation-critical renderers, supervised like any node, with the
helper-subprocess registry pattern (`gui/mochi_companion.py` ~line 398)
as the teardown precedent.

The shell `(planned)`:

- **WindowManager** — checklist #2/#3: registered window *kinds*
  (main window, settings, diagnostics, quick popup, per-app extras like
  CC01's tab panel) that the operator can open N of and close freely;
  the shell quits when told to quit, not when a child window closes;
  quitting closes every window because they're all its objects.
- **Tray surface** — checklist #5: a standard surface kind wrapping the
  platform tray/menu-bar icon. JROS already has the bespoke version
  (`jaeger_os/interfaces/tray/macos.py`, which today hand-rolls
  daemon-detection + `--attach` passing); it becomes the reference
  implementation, generalized.
- **Quick-summon popup** — checklist #6: a global-hotkey surface
  (Claude Code style) that toggles a small always-on-top window wired to
  the bus/core. macOS requires Accessibility permission for global event
  taps — surfaced honestly at first enable, never silently requested
  (risk table).
- **Event-loop awareness stands** (unchanged from the first draft): the
  shell owns QApplication on the main thread; TUI shells own the
  terminal; headless apps have no shell at all. Uniform treatment is a
  lie at the Qt boundary.
- **Attach is the shell↔core contract** — in split mode the shell is a
  *client* of the core: it can be started later, restarted alone, or
  closed while the core keeps running (`shell_quits_core = false`). This
  is the consolidation target for JROS's three ad-hoc `--attach` wirings
  (`jaeger_os/plugins/voice_loop.py`,
  `jaeger_os/plugins/messaging_gateway.py`,
  `jaeger_os/interfaces/tray/macos.py`). The wire already exists
  (`jaeger_os/daemon/{protocol,client,attach}.py`); whether it stays
  NDJSON-over-Unix-socket or becomes a ZMQ bus endpoint is the daemon
  plan's call — this plan fixes the shape, not the wire.
- **Bus→Qt hop**: CC01's `BusBridge` (`controllers/JP01-CC01/main.py`)
  is promoted as the one sanctioned pattern for feeding widgets from the
  bus.
- **Toolkit-agnostic (§1.1 item 9).** The shell contract specifies
  *behavior* (one process, one icon, window verbs, tray, hotkey,
  attach, teardown) — not a widget library. Each app picks ONE toolkit
  in its manifest (`ui = "pyside6" | "swift" | "tui"`) and stays
  consistent. PySide6 is the reference implementation (cross-platform,
  what all three apps speak today); a native Swift shell is a per-app
  choice that implements the same contract as a *client over the attach
  wire* in split mode — which is exactly what `apps/JROS-Avatar/`
  (Swift, attached to the Python core via the animation bridge) already
  does. The core never knows or cares what its shell is drawn with.

**Position (§5 Q7, single instance):** chassis-enforced when
`single_instance = true`, using the proven slot pattern
(`jaeger_os/core/runtime/process_slot.py: acquire_slot_exclusive` +
`jaeger_os/daemon/lifecycle.py` PID-file precedent). Second launch of the
same app+instance does not boot a twin — it either fails with "already
running, use attach" or (flag) launches a surface in attach mode. One
Dock icon falls out of the main-surface rule: one QApplication per app,
child windows are widgets, not processes.

### 2.8 Logging + telemetry

Today: JROS prints `[node:<name>]`-tagged lines to stderr
(`jaeger_os/nodes/base.py: _log`) plus per-instance file logs with
rotation (`jaeger_os/core/runtime/log_rotation.py`); Mochi nodes publish
structured health (`mochi.node.health.v1` payloads,
`transport/node_base.py: _build_health_payload`) cached by `HostMonitor`
for REP queries; CC01 publishes `Log` messages on `/sense/log` rendered
into per-tab log boxes (`core/topics.py`, `tabs/tab_widgets.py: LogBox`).

The framework keeps all three habits and names them once `(planned)`:

- **Log stream:** one line shape — `ts level [app.node] message` — to
  stderr and a per-app rotating file; a `/sense/log` topic mirrors
  operator-relevant lines onto the bus so any surface can render them
  (CC01's pattern, generalized). No new logging framework; stdlib +
  the existing rotation.
- **Telemetry:** `NodeHealth` on `/sense/node_health` (already in
  `jaeger_os/topics.py`, already published at 1 Hz by
  `jaeger_os/hardware/packages/jp01/boot.py` and consumed nowhere yet —
  the framework's health cache becomes its first consumer) carries
  state + per-kind details from `Node.health()`. Mochi's psutil extras
  (memory MB, tx rate, fps) become optional detail fields, not schema.
- **Health cache:** a chassis-internal `HostMonitor`-shaped cache
  (Mochi `core/host_monitor.py` is the reference: SUB everything, cache
  latest health/meta per node, answer point queries) so surfaces and the
  supervisor ask "what's alive" without each holding subscriptions. In
  JROS this is also what the agent's future `node_status` tool reads —
  wiring that tool is daemon-plan territory.

---

## 3. Per-app migration plans (specification only — not executed)

### 3.1 JROS — current state → framework state

Gated: **adopts the chassis only in coordination with the daemon-arch
plan** (its Tier-1 jurisdiction). The un-gated part is mechanical
promotion that changes no behavior.

Target shape: **`mode = "split"`** — the core (Tier 1 + nodes) is the
service, auto-startable at login, `shell_quits_core = false` (Lilith
keeps running when the windows close); ONE shell process hosts TUI-or-GUI
main window, tray, voice panel, and the quick-summon popup as windows of
a single app. Acceptance for this phase is the operator's literal
complaint inverted: launching JROS twice never yields two apps; quitting
the shell leaves nothing orphaned; quitting the core takes every window
and node with it (checklist #4/#8).

| Today (verified) | Framework state | Notes |
|---|---|---|
| `jaeger_os/transport/{bus,inproc_bus,zmq_bus,broker,codec}.py` | promoted to `jaeger_os/app/bus/`; old paths become re-export aliases | One implementation, same change-set — all inside JROS |
| `jaeger_os/nodes/base.py` | promoted to `jaeger_os/app/node.py`; old path re-exports | The universal Node |
| `jaeger_os/nodes/runtime.py` lazy singletons (`ensure_tts_node`…) | manifest `[[node]]` entries + supervisor; `ensure_*` becomes thin lookup | The "can't disable a node without code edit" pain (daemon brief §3) dies here |
| `jaeger_os/main.py: _warm` warm-jobs incl. hardware boot | boot phase 5 (`start_nodes`) — hardware entry uses `factory = jaeger_os.hardware.boot:boot_hardware` | `register_package_capabilities` untouched, per brief hard rule |
| `launch.py` + `process_slot.py` singleton | chassis `acquire_instance()` | Same slot files, shared code |
| `jaeger_os/daemon/` (parked) + `--attach` flags in `voice_loop.py` / `messaging_gateway.py` / `interfaces/tray/macos.py` | one Surface attach contract (§2.7) | Daemon plan decides the wire; framework fixes the shape. 0.1.0 surfaces preserved alongside, per standing memory |
| `jaeger_os/interfaces/{tui,rich_tui,tray}`, `apps/JROS-Avatar/` (Swift renderer) | `[[surface]]` entries; TUI is `main = true` today | Swift app connects as an external surface over the animation bridge — unchanged |
| Instance config (`core/instance/schemas.py: Config`) | unchanged; `jaeger.toml` is additive at repo/app root | Manifest declares shape; instance config keeps behavior |

**JROS `nodes/` reorg (§1.1 item 7)** — mechanical, un-gated by the
daemon plan, executable on operator OK ahead of everything else
(rename + import updates, no behavior change, suite-verified; no alias
shims per the no-back-compat rule — internal imports just move):

```
jaeger_os/nodes/                 today            →  target
├── base.py, runtime.py          (stay at nodes/ root — contract + boot)
├── motor/                       nodes/motor/     →  nodes/hardware/motor/
├── light/                       nodes/light/     →  nodes/hardware/light/
├── vision/                      nodes/vision/    →  nodes/hardware/vision/
├── animation/                   nodes/animation/ →  nodes/software/animation/
├── audio_session/               …                →  nodes/software/audio_session/
├── stt/                         …                →  nodes/software/stt/
└── tts/                         …                →  nodes/software/tts/
```

`jaeger_os/hardware/` **renames to `jaeger_os/middleware/`** in this
same mechanical commit (rule 2 above — operator naming, 2026-06-12:
it is the layer that connects nodes to devices, never the device
controller; the `nodes/hardware/*` workers are the controllers). Its
contents don't change; imports + the `dev/tests/jaeger_os/hardware/`
path move with it; STATUS.md notes the rename. `nodes/runtime.py`'s
singletons keep working through the move and die later, in Phase 3,
when the manifest takes over node declaration.

### 3.2 Mochi — current state → framework state

| Today (verified) | Framework state | Notes |
|---|---|---|
| `main.py: run_host()` (load config → monitor → broker → spawn → poll → teardown) | `JaegerApp` boot phases 1–8 | The chassis IS Mochi's host, generalized |
| `config.yaml` `plugins:` list (id/module/entry/cwd/config_path/enabled) | `[[node]]` manifest entries, `backend = "subprocess"` | Field-for-field mapping; `infrastructure:` block → `[bus]` |
| `core/plugin_registry.py: PluginSpec/PluginProcess` | the supervisor's subprocess backend | Promoted, not reinvented — this code is the reference implementation |
| `transport/broker.py` (XPUB/XSUB) | Mochi's copy of `app/bus/zmq.py` (JROS's `transport/broker.py` is already the same pattern — the reference copy reconciles both before Mochi copies it) | One broker implementation per app, same code lineage |
| `transport/node_base.py: MochiNodeBase` | `FrameNode(Node)` (§2.3); `_update_tick/_render_tick` map to the split hook; health details → `health()` | `nodes/animation/node.py: AnimationNode(MochiNodeBase)` migrates mechanically |
| `transport/topics.py` dotted topics | `/sense /act` typed topics; `node.<id>.health` → `/sense/node_health` | Mochi's ctrl PULL socket (`node_base._control_loop`) → supervisor verbs |
| `core/host_monitor.py: HostMonitor` | Mochi's copy of `app/health.py` | Same REP query idea, same code lineage |
| `gui/mochi_companion.py` (+ in-process `build_mini_window`) | THE shell (`mode = "fused"` first; `split` later if the renderer should outlive the window); mini-window = a WindowManager kind | Mochi's own commit history chose in-process windows; framework canonizes it. Operator: "Mochi seems a bit better" — because one supervisor owns and reaps every child |

### 3.3 JP01-CC01 — current state → framework state

Branch 2.0 (commit `18ed304`) is already the node formation by vendored
port — adoption is reconciling that copy against the reference and
adding the conformance tests; nothing is imported across repos.

| Today (verified) | Framework state | Notes |
|---|---|---|
| `core/bus.py`, `core/node.py`, `core/transport.py` (ports) | reconciled against the reference copy (diff, adopt deltas, add the conformance test file) | CC01 already IS the copy model — its ports came from the same shapes; this is the format's proof case, not its first victim |
| `core/topology.py` + `topology.yaml` | stays as the app's config.yaml-equivalent; a thin `jaeger.toml` is added declaring nodes/surfaces | Topology = hardware config; manifest = app shape |
| `nodes/jetson_link.py`, `nodes/stream_rx.py` | unchanged `Node` subclasses, declared as `[[node]]` `backend = "thread"` | |
| `main.py` (bus + nodes + Qt + `BusBridge`) | `mode = "fused"`; shrinks to `JaegerApp(manifest).run()` + tab wiring; `BusBridge` replaced by the framework's bus→Qt hop | Tabs (`tabs/*.py`) unchanged — they're callback-driven and already bus-fed |
| `--sim` flag | `jaeger.sim.toml` profile (§2.5) | Sim stays one command away |

### 3.4 Correction to the brief

The brief's §2 row for JP01-CC01 ("config.json `enabled_plugins`,
in-process plugin managers") describes the app before commit `18ed304`
(2026-06-12). Current truth on branch 2.0 is §3.3's left column; the old
`plugins/Core` managers are no longer imported by `main.py`.

---

## 4. Migration sequence

**Phase 0 — the format repo is born** `(planned)`: create
`Jaeger-Framework` (spec doc + reference `app/` + conformance tests +
template + changelog). The reference chassis is *extracted from* JROS's
proven modules (`nodes/base.py`, `transport/*` — they already obey the
copy-ability rules), then JROS immediately copies it back in as
`jaeger_os/app/` with old paths re-exporting. Net effect inside JROS:
zero behavior change, suite stays green; net effect outside: the format
now exists as its own artifact. Reversible by deleting both directories.

**Phase 1 — Mochi adopts** `(planned)`: Mochi copies `app/` (+
conformance tests) from the format repo into its own tree as
`Mochi/app/` and rebases `main.py: run_host` onto its copy. First because it is the lowest-risk, highest-coverage consumer —
already multi-process, already config-driven, no identity state, no
safety surface, and explicitly the operator's reference for the
supervisor pattern. It exercises every chassis subsystem (subprocess
backend, broker bus, shell + windows, health cache) in one app. If the
chassis can't host Mochi cleanly, the design is wrong and we find out
cheaply, before JROS is entangled. Acceptance: `python main.py` behaves
identically; node on/off/restart/diagnose works through the supervisor;
the Tk-era fallback entry in `config.yaml` maps to `enabled = false`;
conformance tests green in Mochi's venv.

**Phase 2 — JP01-CC01 adopts** `(planned)`: reconcile its vendored
`core/` against the reference copy per §3.3 and drop in the conformance
test file. Acceptance: existing `tests/` (16) plus conformance green in
CC01's own environment; `--sim` GUI walk unchanged. This phase proves
the copy mechanism on the app that already organically used it.

**Phase 3 — JROS adopts** `(planned, gated)`: only after the daemon-arch
plan returns and is approved, because the chassis becomes the skeleton of
whatever Tier-1 process that plan specifies. The un-gated subset
(promotions in Phase 0, manifest-declaring today's in-process nodes
behind the existing boot) can land earlier since it changes nothing
observable. The `--attach` consolidation happens here, against the daemon
plan's chosen wire.

Sequencing rationale in one line: prove the chassis on the toy, then on
the console, then put the soul on it.

---

## 5. Future Jaeger apps — slot-in spec

A new app in the family starts by **copying the reference** (the Office
model — the new app owns its copy from day one):

```
my-app/
├── app/                 # ITS copy of the chassis, copied from the
│   └── …                #   format repo (rename allowed, e.g. core/)
├── tests/
│   └── test_app_format.py   # copied conformance tests — run in MY venv
├── jaeger.toml          # [app] + [bus] + [[node]] + [[surface]]
├── config.yaml          # behavior knobs, schema-validated
├── nodes/               # everything node-shaped, categorized (§2.3):
│   ├── hardware/        #   physical-device nodes
│   └── software/        #   compute/render/pipeline nodes
├── surfaces/            # Surface builders (optional)
└── main.py              # ~5 lines: JaegerApp(manifest).run()
```

Checklist: pick `mode` (start fused; go split when the core should
outlive the windows) and `event_loop`; declare nodes with tier + backend +
restart policy; mark exactly one surface `main = true` (or none, for
headless); put tunables under each node's `config_key`; ship the config
schema with the app. The desktop-grade checklist (§2.0) comes free from
the chassis — an app only opts *in* to autostart and the hotkey popup. The hardware case is already solved — a robot app
declares a `[[node]]` whose factory is its hardware package boot, and the
capability surface arrives via the existing `jaeger_os/hardware`
machinery. The animation node remains the contract-validation case: any
new app that renders should start by running the animation node under its
own manifest before writing custom nodes (the §6.5 instinct, generalized
from "migrate it first" to "boot it first").

---

## 6. Positions on §5 design questions

| # | Question | Position | Why (compressed) |
|---|---|---|---|
| 1 | Where does the framework live? | Its OWN repository (PROPOSED: `Jaeger-Framework`): spec + reference chassis + conformance tests + template + changelog. Every app — JROS included — carries its own COPY (`<app>/app/`); improvements upstream to the format repo (operator decisions — "just a format, so its own repo"; the Office model). NOTHING is shared across repos at runtime | Apps stay independent codebases; the copy mechanism is already proven (CC01, VoiceLLM, AgenticLLM); conformance tests + format version + changelog keep copies honest |
| 2 | Subprocess vs in-process default | Per-node backend in the manifest; default `thread`. Windows are never the multiprocess unit — nodes are (§2.0) | JROS's own revert + daemon-brief anti-pattern #1; Mochi keeps subprocess where isolation pays; per-window processes are the orphan factory |
| 3 | Config format | YAML everywhere (already true post-`18ed304`); shared loader + refuse-loudly validation | CC01's json is already dead; nothing left to migrate but the loader code |
| 4 | Node shape | The existing `jaeger_os/nodes/base.py` contract, promoted verbatim; hardware nodes already compose it; `FrameNode` specialization for Mochi; subprocess children unify at the NodeHandle, not the class | It's already the de-facto universal contract in 3 of 3 repos — promote, don't invent |
| 5 | Bus | JROS `Bus` ABC + both existing backends promoted; broker = the zmq backend's topology; Qt signals demoted to the bus→Qt bridge pattern | JROS already ships the abstraction AND the Mochi-pattern broker behind it |
| 6 | Surface lifecycle | One GUI shell process per app; ALL windows are in-shell WindowManager objects, created/closed freely; subprocess surfaces only for isolation-critical renderers. Supersedes the daemon brief's per-window-subprocess framing (operator, §1.1) | Qt's main-thread rule + the desktop-grade bar; Mochi's mini-window history proves it |
| 7 | Single instance | Chassis-enforced slot (`process_slot` pattern) when `single_instance = true`; second launch → attach or refuse; `autostart` installs a LaunchAgent for the core in split mode | Proven code; one QApplication per app gives one Dock icon for free; autostart belongs to the service, never a window |
| 8 | Hot reload | ON/OFF/RESTART universal via NodeHandle; systemd-style policy (never/on_failure/always + backoff + burst limit); `node diagnose` CLI ships with it; no in-place code reload; Tier 1 excluded | Restart = teardown + fresh start is debuggable; importlib reload is not; diagnose is the humanoid-ops surface |
| 9 | Repo topology | Four repos: the format repo (`Jaeger-Framework`) + the three apps, all separate; nothing to merge FOR | Different apps, one format (Office model); firmware ships with hardware; the format is its own artifact per operator decision |
| 10 | Manifest | `jaeger.toml` = structure (nodes, surfaces, bus, event loop, instance policy); config.yaml = behavior; manifest not runtime-overridable; sim = alternate manifest | Mutability split keeps both files honest; validator ships with schema |

---

## 7. Open questions (operator can answer yes/no/"do X")

1. ~~Editable install vs vendored~~ — **answered by operator
   (2026-06-12): vendored/copied, the Office model.** Residual question:
   want a scaffold command later (`jaeger new-app <name>` copying the
   reference + template manifest), or is "cp -r and edit jaeger.toml"
   fine for the handful of apps we'll make?
2. **Mochi-first** — confirm Mochi is the right first adopter (it gets
   churned before JROS does), or would you rather CC01 go first since its
   delta is smallest?
3. **Names** — (a) the format repo: `Jaeger-Framework` is the working
   name (the brief's own suggestion); alternatives: `Jaeger-App-Format`,
   `JaegerKit`. (b) the chassis directory each app carries: plain `app/`
   (the plan retired `jaeger_app` — it read as a shared/standalone app,
   which it never was); alternatives: `chassis/`, keep-`core/`-everywhere.
   Pick either or both; everything else is independent of naming.
4. **Daemon-plan interlock** — when the daemon-arch plan lands, this plan
   defers to it on: Tier-1 process model, the attach wire (NDJSON socket
   vs bus), and agent-facing node-control tools. Confirm that division,
   or name a different boundary.
5. **Mochi node ctrl-socket retirement** — migrating `MochiNodeBase`
   retires its per-node PULL command socket in favor of supervisor verbs.
   Any Mochi tooling you use day-to-day that types raw `node <id> …`
   commands at that socket and must keep working?
6. **Shell-close semantics per app** — confirm the defaults:
   Mochi `shell_quits_core = true` (close companion = quit), JROS
   `false` (Lilith keeps running headless), CC01 fused (no split). 
7. **Autostart scope** — autostart at login for JROS's core: default on
   once split mode ships, or strictly opt-in via `<app> autostart on`?
8. **Global hotkey** — the quick-summon popup needs macOS Accessibility
   permission. OK to make it an explicitly-enabled surface (off by
   default in every manifest) so no app silently asks for that grant?

---

## 8. What I did NOT design (explicit non-goals)

- **Tier-1 internals** — process model, identity persistence, subagent
  IPC, the daemon verb set: the daemon-arch plan's jurisdiction. This
  chassis is the shape all four tiers boot through, not their contents.
- **The hardware framework** — `jaeger_os/hardware/` is fixed; this plan
  only references its boot hook and leaves `register_package_capabilities`
  as the capability path.
- **Cross-machine bus** — the `external` backend is reserved, not
  specified; Jetson-side services keep their current ZMQ surfaces.
- **MCP servers, Rust nodes, auth/permissions changes** — out of scope;
  permissions stay `jaeger_os/core/safety/permissions.py` as shipped.
- **New rendering/animation work** — the animation node is a migration
  subject, never redesigned here.
- **Packaging/installers** — `install.sh`, code signing, notarization,
  DMG/installer flows: untouched. (The thin .app-bundle launch recipe of
  checklist #1 is in scope; everything distribution-grade is not.)
- **Non-mac chassis hosts** — Linux/Windows ports of the chassis
  (systemd units, Windows services, non-NSStatusBar trays): deferred per
  the macOS-first posture (§1.1 item 5). The Jetson stays an
  `external`-backend participant, not a chassis host.
- **ROS 2 interop** — the lifecycle *mapping* is documented (§2.4); an
  actual `ros2_bridge` node remains future work per the hardware plan.

---

## 9. Risks

| Risk | Exposure | Mitigation |
|---|---|---|
| Chassis shaped by one app's needs (framework-before-second-consumer) | Design debt baked into the contract | Mochi-first sequencing — the second consumer arrives in Phase 1, before JROS is bound |
| Collision with the daemon-arch plan | Rework of §3.1 / attach contract | Phase 3 gated on that plan; chassis stays tier-agnostic; open question 4 pins the boundary |
| Promotion churn breaks JROS imports | Suite red, alias drift | Phase 0 promotes with re-export aliases in the same change-set; import-lint test enforces layering |
| Copy drift (chassis copies diverge; a fix in one app lingers unported) | Same bug fixed twice; copies quietly stop matching the spec | Accepted cost of the Office model, managed: per-copy `FRAMEWORK_FORMAT` stamp + copied conformance tests; the format repo's changelog lists which modules changed per format version so re-copying is a targeted diff, not an archeology dig |
| Format repo rots (no app imports it, so nothing forces it to stay current) | Reference falls behind the apps; new apps copy stale code | Its tests run standalone (chassis is dependency-light by rule); the upstream-then-recopy discipline routes every app-discovered fix through it; the skeleton `template/` is exercised whenever a new app is scaffolded |
| Bus throughput for frames in-process | UI jank on CC01 video | Already measured patterns: Mochi pushes frames through XPUB/XSUB at 60 fps targets; CC01 pushes H.264 through InProcBus today; codec layer keeps binary topics MessagePack |
| Manifest scope creep (absorbing config) | Two config files that both do everything | §2.5 mutability rule + validator refusing behavior keys in the manifest |
| Restart races (node restarting while its tools dispatch) | Mid-turn errors | Existing typed-error + `check_fn` machinery; supervisor flips health before teardown so `check_fn` hides tools first |
| Global-hotkey permission (macOS Accessibility) surprises the operator or silently fails | Quick-summon "doesn't work" reports; trust erosion | Hotkey surface off by default; first enable explains the grant and links System Settings; degrade to tray-click summon when denied (open question 8) |
| LaunchAgent drift (autostart plist points at a moved venv/repo) | Core fails to start at login, silently | `<app> autostart status` verb validates the plist target at every boot; install/uninstall owned by one chassis module, never hand-edited |
| Fused→split migration breaks an app's assumptions (shared memory between shell and core) | Mochi/CC01 code that touched node objects directly | Fused mode keeps direct access legal; split mode is opt-in per app and only after its surfaces talk bus/IPC only — the import-lint test gains a "shell imports core internals" check at that point |

---

*End of plan. No code was written or modified in any repo for this
deliverable beyond this document and the saved brief.*
