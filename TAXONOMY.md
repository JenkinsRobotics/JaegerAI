# Taxonomy — the five compositional tiers

> Operator-ratified, written against `THREE_TIER_STRUCTURE.md` and
> `JAEGER_ECOSYSTEM.md` (JaegerOS repo, branch `0.9.0`, ratified
> 2026-07-11) plus this template's own module/workspace skeletons and a
> real shipped module (`JaegerKokoroTTS`). Where this doc and the code
> disagree, the code wins and this doc gets edited — same rule as
> `CONVENTIONS.md`'s "no spec ahead of code."
>
> This is a **different cut** of the ecosystem than `THREE_TIER_STRUCTURE.md`'s
> four structural tiers (JaegerOS / Jaeger AI / Modules / Projects), not a
> competing one. That doc answers *"which repo does this code live in."*
> This doc answers *"what compositional role does this thing play,
> regardless of which repo it lives in."* See "Reconciling with the
> structural tiers" at the bottom — the two maps agree everywhere they
> overlap.

## The principle: role, not size

A tier is defined by **what it does in the assembly**, not by how much
code it contains or how many files it has. A one-file module and a
ten-thousand-line module are still both MODULE tier if they're
discovered the same way (one `module.yaml`, one slot). A workspace with
one controller and a workspace with twelve are still both
PACKAGE/WORKSPACE tier if they both own a body's bringup. Judge tier
membership by the question below, not by line count.

## The five tiers

```
NODE                 the atom. Never distributed alone. ONE standard
                      everywhere.

MODULE                the unit of discovery. One module.yaml, one slot.

PACKAGE / WORKSPACE   the unit of assembly. topology + manifest + unit
                      + safety + pins.

APP                   a face. Protocol-connected or stack-embedding.

DISTRIBUTION          the bundle for humans.
```

### NODE — the atom

**Question it answers:** "what is the smallest thing that does one job
on the bus?"

A `Node` is JaegerOS's atomic unit: a four-phase lifecycle
(`setup → tick → teardown → health`) around a bus connection. It is
**never distributed alone** — nobody ships a node as a standalone
artifact; it always arrives inside a module or a hardware package.
There is **one standard everywhere**: every node in the ecosystem,
whether it's `kokoro_tts`'s synthesis node or JP01's `motor` node,
implements the same four phases and the same health-report shape. This
is the layer where "modularize contracts early, implementations late"
(`CONVENTIONS.md`, law 1) bites hardest — a node's *topics* are the
contract; its internal tick loop is free to be anything.

- **Real examples today:** `jaeger_os/nodes/kokoro_tts/node.py`
  (`jaeger_kokoro_tts/nodes/kokoro_tts/node.py` in the split-out repo),
  the generic `jaeger_os/nodes/motor`, `jaeger_os/nodes/light`,
  `jaeger_os/nodes/vision` node classes that JP01's adapters bind to.
- **Template shape:** `{{package_name}}/node.py.example` — one class,
  four phases, imports nothing outside its own module + the bus.

### MODULE — the unit of discovery

**Question it answers:** "what does `discover_modules()` find, and
what slot does it fill?"

A module is a directory carrying exactly **one `module.yaml`** and
claiming exactly **one slot** (`tts`, `stt`, `vision`, `animation`,
`media`, `messaging`, …). It bundles everything needed to make that
slot's capability real: the node(s), the engine code, its own
`config.py` settings-catalog slice, the tools it registers, and
(optionally) module-shipped skills. `discover_modules()`
(`jaeger_os/core/modules.py`) walks the module roots and returns every
module found, keyed by slot — a manifest binds a slot to whichever
module claims it (`slot=tts` → `kokoro_tts`), so swapping engines is a
config edit, never a code edit. Most slots are one-module; `messaging`
is the first genuinely multi-module slot (discord/telegram/imessage
coexist, ANY-OF readiness).

- **Real example — the ground truth for this tier,**
  `jaeger_kokoro_tts/nodes/kokoro_tts/module.yaml` (JaegerKokoroTTS
  repo):

  ```yaml
  module: kokoro_tts
  slot: tts
  version: 1.0.0
  consumes: [/act/speech, /act/speech_stop]
  produces: [/sense/spoken, /sense/tts_chunk]
  tools: [text_to_speech]
  factory: jaeger_kokoro_tts.nodes.kokoro_tts:make_tts_node
  config: kokoro_tts
  requires_libraries: [kokoro, sounddevice, numpy]
  ```

- **Template shape:** `{{package_name}}/module.yaml.example` +
  `config.py.example` + `node.py.example` + `docs/DESIGN.md.example` +
  `tests/test_module_contract.py.example` — this template's module-repo
  shape mirrors the real one field-for-field.

### Module KINDS — the ownership axis

**Question it answers:** "what is this module allowed to touch?" —
orthogonal to slot. Slot answers *what role* a module fills (`tts`,
`stt`, `vision`, …); kind answers *what it owns*. All four kinds below
are still MODULE tier by the discovery/loading mechanism above — one
`module.yaml`, one slot, one factory. Kind is a second, independent cut
through the same tier, operator-ratified 2026-07-11.

```
DRIVER        owns ONE hardware device family, exclusively — device
              talk + its middleware + health + config. Exposes ONLY
              standardized topics. Swap the device = swap the module.

PROCESSING    software-only, universal by construction — touches
              topics, never devices.

ENGINE        fills a capability slot (tts, stt, …) — the shipped
              pattern today.

MIND          the agent itself — singleton, slot mind.
```

- **DRIVER** — e.g. a `usb_camera` module publishing
  `/sense/camera_frame`. Its whole job is standardizing the topic so
  any camera in that family is interchangeable underneath it. The
  rule this kind exists to enforce: **nothing outside a driver-kind
  module may open a device.**
- **PROCESSING** — e.g. a video codec module, an image-ops module
  (resize/crop/color-convert), a VAD (voice-activity detector). Inputs
  and outputs are both topics; it is portable to any driver that
  produces the topic shape it expects. No shipped example exists yet
  — the pattern is real and ratified, the first processing-kind module
  is unbuilt.
- **ENGINE** — `kokoro_tts` (`slot: tts`), `whisper_stt` (`slot: stt`).
  Bundles engine code (a synthesis/recognition library) + a node,
  bound to a slot. **Honest gap:** both shipped examples also touch
  hardware directly inside their own node today (`kokoro_tts` owns the
  speaker, `whisper_stt` owns the mic, both via the engine's own
  library calls) — a driver/engine split would clean this up, but per
  the second-consumer rule (this doc's own "role, not size" spirit,
  restated in `CONVENTIONS.md`), that split is premature until a
  second module actually needs the same raw device stream
  independently.
- **MIND** — the agent core. Today: in-repo `jaeger_os/agent/` code
  with its own `module.yaml` at the root (0.9 step 3), not yet a
  swappable implementation the way `kokoro_tts` is — see this doc's
  DISTRIBUTION section and `examples/FRAMEWORK_GAPS.md` gap 5.

**Worked example — lidar** (hypothetical; no lidar body exists in the
ecosystem today):

```
lidar_driver module (kind: driver)
  owns: device talk (serial/USB), link health, its own config
  exposes: /sense/scan             ← the ONLY thing downstream sees
                 │
                 ▼
slam_processing module (kind: processing)
  subscribes /sense/scan, produces /sense/map
  never touches a device — device-blind, portable to any lidar
  hardware that also emits /sense/scan
```

**Status:** `kind` is **(planned)** as a validated field —
`ModuleSpec` (`jaeger_os/contract/modules.py`) doesn't have it yet
(`forbid_unknown_fields = True`; a real `module.yaml` that adds `kind:`
today fails strict validation until the schema ships it). See
`module.yaml.example`'s `kind:` field for the scaffold and its four
enum values, and the JaegerOS vault's `Ownership_Model.md` /
`Nodes_And_Modules.md` for the fuller ownership-rule writeup this
section is the template-repo counterpart of.

### PACKAGE / WORKSPACE — the unit of assembly

**Question it answers:** "what brings a specific BODY (or a specific
running instance) into existence?"

A workspace is a project that owns one Body's bringup: `topology.yaml`
(controllers + capabilities + safety), `manifest.toml` (the `[[node]]`
graph that actually boots — engine modules bind by `slot=`, hardware
packages bind by `factory=`), `unit.yaml` (this physical/simulated
unit's identity + `verified` live-walk gate), and `bringup/boot.py`
(links → adapters → e-stop → capabilities → runtime). **Hardware
packages ARE workspaces for bodies** — `jaeger_os/hardware/packages/jp01/`
is both "the JP01 hardware package" in JaegerOS's own vocabulary and a
workspace in this taxonomy's vocabulary; same shape, same role. A
software-only workspace (no controllers, no physical body) is a
degenerate case of the same tier — see `examples/simple_tts_app.md`.

- **Real example — jp01's `topology.yaml`**
  (`jaeger_os/hardware/packages/jp01/topology.yaml`, JROS repo):
  three controllers (`mc01` motor, `avc01` lights, `vcc01` vision),
  each with a `link:` (serial or ZMQ REQ, some relayed through a
  Jetson), capabilities grouped into umbrellas (`motion.*`,
  `lights.*`, `robot_vision.*`, `telemetry.read`) each tagged
  `HARDWARE` / `WRITE_LOCAL` / `READ_ONLY`, and a `safety:` block
  (`estop_scope: [mc01]`, `firmware_watchdog_required: true`).
- **Template shape:** `workspace/topology.yaml.example` +
  `manifest.toml.example` + `unit.yaml.example` +
  `requirements.txt.example` + `bringup/boot.py.example` +
  `SAFETY_CHECKLIST.md` — modelled field-for-field on jp01's real
  package.

### APP — a face

**Question it answers:** "how does something OUTSIDE the Mind's own
process reach in, or how does a Mind-facing surface present itself?"

An app connects to a running Mind one of two ways:

1. **Protocol-connected** — speaks the versioned NDJSON wire contract
   (`jaeger_os/contract/protocol.py`) over some transport, through
   `JrosClient` (`jaeger_os/interfaces/client.py`). This is how the
   Swift app talks to `jaeger bridge` over stdio, and how any
   third-party client (a web backend, a mobile app) would connect —
   "transports, not endpoints," never pip-dissecting the agent.
2. **Stack-embedding** — assembles JaegerOS + Jaeger AI + whichever
   modules it needs in its own process via a manifest
   (`jaeger.toml` / `jaeger.windowed.toml` shape). This is what the
   TUI, the frozen PySide6 set, and the fused-mode agent core itself
   do today.

Both are "a face" — the tier is about *how it connects*, not which
widget toolkit it uses. **Studio manages Jaegers**: `jaeger-studio` is
itself an APP-tier surface, but one whose job is observing/managing
*other* running Jaeger instances (panels, health, trace view) rather
than being a chat face — same tier, different role within it.

- **Real examples:** `jaeger_os/interfaces/swift/` (protocol-connected,
  default windowed UI), `jaeger_os/interfaces/tui/` (stack-embedding,
  0.1.0-lineage), `jaeger_os/interfaces/mcp_server.py`
  (protocol-adjacent — bridges MCP tool calls into the same agent),
  `jaeger-studio` (protocol-connected, multi-instance manager).
- **Template shape:** **(planned)** — this template doesn't scaffold
  an app skeleton yet (`CONVENTIONS.md`, "the three repo shapes");
  start from Jaeger-AI's `jaeger.toml`/`jaeger.windowed.toml` and pin
  forward.

### DISTRIBUTION — the bundle for humans

**Question it answers:** "what does an operator actually `pip install`
(or download) to get a running thing, with nothing else to assemble?"

A distribution is JaegerOS pinned + one or more MODULEs (at least one
mind-slot module) + one or more APPs + an installer, packaged so a
human runs one command and has a working product. **`JaegerAI` the
repo is a DISTRIBUTION**: it bundles the mind module, the engine
modules it ships by default (`kokoro_tts`, `whisper_stt`, `animation`,
`media`), its faces (Swift app, TUI, PySide6 set), and
`install.sh`/`pyproject.toml` as the installer.

**The nuance this taxonomy exists to state precisely:** *inside* that
distribution, the agentic core plays the MODULE role — it is (or, as
of today, is becoming — see the 0.9 roadmap's "mind-as-module,
in-repo first" item, **planned**, not yet a `module.yaml`-discovered
module) a thing bound to a **slot: mind**, exactly the same
compositional shape as `kokoro_tts` bound to `slot: tts`. **JaegerAI-
the-mind is a MODULE; JaegerAI-the-repo is a DISTRIBUTION that bundles
that module with others.** One repo, two tiers, because the repo's
job is bundling and the mind's job (inside it) is filling a slot.
Today the mind is not yet cleanly separable from the distribution
(it's core `jaeger_os/agent/` code, not yet behind `discover_modules()`)
— that gap is called out explicitly in `examples/simple_chatbot.md`
and `examples/FRAMEWORK_GAPS.md`.

- **Real example:** the `JaegerAI` repo (`jaeger.toml` /
  `jaeger.windowed.toml`, `install.sh`, bundled engine modules under
  `jaeger_ai/nodes/`, faces under `jaeger_ai/interfaces/` once the 0.9
  split lands).
- **Template shape:** none — a distribution is an assembly of the
  other four tiers, not something this template scaffolds directly.

## Marketplace tags

The tag an entry in a future module store/registry would carry — this
is what `module.yaml`'s existing fields (slot, version, `requires_*`)
already have enough information to index, per `JAEGER_ECOSYSTEM.md`
§8 "Beyond 1.0":

| Category | Tagged by | Examples today |
|---|---|---|
| **Modules** | slot (role) + kind (ownership, **planned** field) | `tts` (kokoro_tts, kind: engine), `stt` (whisper_stt, kind: engine), `animation`, `media`, `messaging` (discord/telegram/imessage), `mind` (planned) |
| **Hardware Packages** | body archetype | `jp01` (desk-scale, 3 controllers); future: turret, arm, lidar-body |
| **Apps** | connection mechanism + face | `swift` (protocol), `tui` (embedding), `pyside6` (embedding), `studio` (protocol, multi-instance manager) |
| **Souls** | character/tone | the 14 shipped character packs (`anakin_skywalker`, `bender`, `glados`, `jarvis`, `lilith`, `mochi`, `tars`, …) |
| **Skills** | domain / SOP | module-shipped skills (e.g. the messaging-setup SOP shipped with 0.8.1) |
| **Distributions** | product | `JaegerAI` (the only one today) |

## Comparison to ROS

| This taxonomy | ROS analog | Fit |
|---|---|---|
| **NODE** | ROS Node | Close. Both are the atomic single-purpose unit around a pub/sub connection with a lifecycle. Difference: a JaegerOS node is usually an in-process thread by default (fused mode); a ROS node is usually its own OS process. |
| **MODULE** | ROS package | Close. `module.yaml` ~ `package.xml` — both declare what a unit consumes/produces/depends on, and both are the unit a build/discovery tool indexes. |
| **PACKAGE/WORKSPACE** | colcon workspace + a `*_bringup` package | Two ROS concepts fused into one JaegerOS tier. `topology.yaml`/`manifest.toml`/`unit.yaml` do what a `_bringup` package's launch files + robot description do (declare what boots and how), while also being the thing you build/pin (colcon workspace's job). |
| **APP** | *(no single ROS analog)* | Loose. ROS doesn't have a strong "outside app talks to the robot over a stable wire protocol" concept the way JaegerOS's NDJSON contract does — rviz/rqt are closer, but ROS's default posture is "join the same DDS domain," not "speak a versioned client protocol." |
| **DISTRIBUTION** | a ROS distro (Noetic, Humble, …) | Partial. Both are curated, versioned bundles released together. Mismatch: a ROS distro is OS-level infrastructure curated by the ROS org, not itself a runnable product; a Jaeger distribution (JaegerAI) IS a turnkey running product. Don't lean on this analogy past "both are the thing you install to get a coherent set." |
| *(no analog)* | — | The **mind slot**, **souls** (character packs as swappable persona State→View), and the **capability layer**'s permission-tier/e-stop "superego" fused with an LLM tool registry have no ROS equivalent — ROS has no cognitive-agent identity layer and no built-in concept of gating actions by an LLM's own tool calls. |

## Reconciling with the structural tiers

`THREE_TIER_STRUCTURE.md` / `JAEGER_ECOSYSTEM.md` describe **where code
lives** (JaegerOS framework repo / Jaeger AI product repo / engine-
module and hardware-package repos / project repos). This document
describes **what compositional role a thing plays**, which is
orthogonal:

- **JaegerOS** (structural: framework) has no tier of its own here —
  it's the substrate all five tiers are built on (the `Node` base
  class, `discover_modules()`, the hardware-package loader, the
  protocol). It doesn't fill a role; it defines what a role IS.
- **Jaeger AI** (structural: product) is a DISTRIBUTION whose mind is
  a MODULE, per the note above.
- **Engine modules / hardware packages** (structural: modules) are
  MODULE tier and PACKAGE/WORKSPACE tier respectively, one-to-one.
- **Projects** (structural: JP01, Jaeger Animate, the desktop
  companion) are each some combination of PACKAGE/WORKSPACE (the body)
  + APP (the face) + DISTRIBUTION (if they ship an installer) — a
  project is an *assembly*, not a fixed tier; which tiers it needs
  depends on what it is (JP01 needs workspace + app; a pure chat
  product needs distribution + app; a headless robot loop needs just
  workspace).

No contradiction: the structural tiers say which repo a thing's code
sits in today (or will sit in after the 0.9 split); this taxonomy says
what job it does in an assembly, which is what a marketplace, a
`module.yaml`, or a new contributor deciding "which template shape do I
start from" actually needs to know.
