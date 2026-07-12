# The Jaeger ecosystem — the finalized rundown

> Operator document. Branch `0.9.0`, written against the state ratified
> 2026-07-11 (`THREE_TIER_STRUCTURE.md` + its Refinements section, which
> supersede the base text). Every claim below traces to a source file listed
> at the end. Anything not yet built is marked **(planned)**.

## 1. The thesis, in one paragraph

JaegerOS is one mind, many bodies: a local-first, modular runtime that turns
a specific robot, app, or desktop companion into a **composition of
modules** instead of a fork of a codebase. The long-run claim is architectural
and platform-specific at once — **JaegerOS is to Apple what ROS is to
Linux**: the native robotics-and-agentic-AI framework for the Apple stack
(Mac today, iOS/visionOS as the ecosystem opens), the way ROS became the
default framework on Linux boxes. "Apple-first" is a design center, not a
fence — non-Apple compute (a Jetson driving JP01's vision/motor loop today)
plugs in as a **peripheral body**, not a second platform to port the whole
stack to. Everything downstream of this document — the tier map, the module
inventory, the roadmap — is that one claim taken apart into its working
pieces.

## 2. The four-tier map

The operator's ratified shape, verbatim from `THREE_TIER_STRUCTURE.md`
Refinement 1 (2026-07-11, supersedes the plain three-tier text above it):

```
JaegerOS            ← the FRAMEWORK. Bus · Node · modules/slots · supervisor ·
                      safety · contract · capability layer. Pinned to, not
                      edited, by consumers.

Jaeger AI           ← THE TURNKEY PRODUCT, not a headless library. Ships the
                      complete universal agentic agent (Hermes lineage): loop,
                      tools, skills, memory, persona (id/ego), local
                      inference, AND its own faces — chat app, TUI, voice,
                      the protocol it serves. Headless (robots) is a CONFIG
                      of Jaeger AI, not a fork.

Modules             ← things that plug into any JaegerOS project: engines
                      (kokoro_tts, whisper_stt, animation, media), hardware
                      packages (jp01, future bodies), characters (souls),
                      module-shipped skills.

Projects            ← the assembled THINGS, each its own repo, pulling in
                      JaegerOS + whichever modules it needs, owning its own
                      bringup (topology, config, instance): JP01 (the robot),
                      Jaeger Animate (future, animatronics rigging), the
                      desktop companion (Lilith on a Mac).
```

**What code lives where, today** (the repo is still all four tiers stacked in
one box — that's how the tiers were *discovered*, not a mistake):

- **JaegerOS framework** — `jaeger_os/core/` (the bus, `Node`, `modules.py`
  discovery/loader), `jaeger_os/interfaces/protocol.py` + `bridge.py` (the
  wire contract), the Supervisor, `jaeger_os/hardware/` (package loader,
  capability registration, `EStopLatch`), the not-yet-extracted
  `jaeger_os/contract/` (0.9 work item).
- **Jaeger AI (the product)** — `jaeger_os/agent/` (the loop, tool registry,
  availability gates, `persona_first` id/ego pipeline), `jaeger_os/personality/`
  (characters, the persona compiler), memory (`<instance>/memory/state.db`),
  skills, and its faces: `jaeger_os/interfaces/swift/` (the default windowed
  UI), `jaeger_os/interfaces/tui/` (the 0.1.0-lineage terminal surface),
  voice (`whisper_stt` + `kokoro_tts` modules), `jaeger_os/interfaces/pyside6/`
  (frozen shipping set), `jaeger_os/interfaces/mcp_server.py`.
- **Modules** — `jaeger_os/nodes/{kokoro_tts,whisper_stt,animation,media}/`
  (engine-modules), `jaeger_os/plugins/{discord,telegram,imessage,
  homeassistant,ai_gen,mcp}/`, `jaeger_os/hardware/packages/jp01/` (the one
  hardware package today).
- **Projects** — the desktop companion is the only one instantiated today
  (an `.jaeger_os/instances/<name>/` tree, e.g. `jros-dev`); JP01 and Jaeger
  Animate are named future projects, not yet separate repos.

## 3. The connection rule

From Refinement 2: **bodies provide capabilities · the Mind consumes them ·
the runtime is where they meet · the protocol is how outside apps reach in**
(the same versioned NDJSON API the Swift app uses — embedding a JROS-driven
app means a protocol connection, not pip-dissecting the agent).

Three connection types, three mechanisms:

1. **Capability layer (Mind ↔ Body).** A hardware package's `topology.yaml`
   declares `capabilities:` (name, controller, permission tier, arg schema,
   description). `register_package_capabilities()`
   (`jaeger_os/hardware/capabilities.py:228`) materializes them into umbrella
   `ToolDef`s at package boot; the agent re-snapshots its tool catalog every
   turn (`_refresh_tool_catalog`), so a plugged-in body's tools appear next
   turn with no code edits, and an unplugged one's vanish. Dispatch runs
   permission-tier → e-stop latch → link health → handler; every umbrella
   self-unregisters on package shutdown and is fail-closed per controller
   (`check_fn` is true only while its `Link` is connected).
2. **Slots + `module.yaml` (Mind ↔ engine modules).** A module directory
   under `jaeger_os/nodes/<name>/` or `jaeger_os/plugins/<name>/` declares a
   `slot`, its bus topics (`consumes`/`produces`), the tools it serves, its
   factory, and `requires_libraries`/`requires_platform`. `discover_modules()`
   (`jaeger_os/core/modules.py`) walks both roots and returns every module
   found, keyed by slot; manifests bind a slot to a factory
   (`slot=tts` → kokoro_tts). Most slots are one-module; `messaging` is the
   first genuinely multi-module slot (discord/telegram/imessage coexist,
   ANY-OF readiness).
3. **NDJSON protocol + `JrosClient` (outside apps ↔ the Mind).** One wire
   contract (`jaeger_os/interfaces/protocol.py`), many transports —
   "transports, not endpoints." The Swift app speaks it over stdio
   (`jaeger bridge`); the MCP server, a future web backend, or any
   third-party client speaks the *same* frames through the same SDK
   (`jaeger_os.interfaces.client.JrosClient`). `PROTOCOL_VERSION` bumps only
   on breaking changes; `query`/`command` verbs are additive envelopes (six
   are live: `list_sessions`, `load_session`, `new_session`, `check_update`,
   `run_update`, plus the core `send`/`respond`/`quit` + `ready`/`state`/
   `tool`/`reply`/`request`/`fatal` frame types).

**Sim is a body made of math.** A simulator declares the same capability
names as a real body — teach in sim, deploy real — no code path changes
between the two; only which body answers the capability call changes.

## 4. Core modules today — the full inventory

Read directly from the shipped `module.yaml` / `plugin.yaml` files (0.8 M1–M3
graduations; no shims remain — `plugins/kokoro_tts`, `nodes/tts`, and the old
`audio_session` split are gone):

| Module | Slot | What it does | Consumes | Produces | Tools | Requires |
|---|---|---|---|---|---|---|
| `kokoro_tts` | `tts` | Kokoro speech synthesis | `/act/speech`, `/act/speech_stop` | `/sense/spoken`, `/sense/tts_chunk` | `text_to_speech` | `kokoro, sounddevice, numpy` |
| `whisper_stt` | `stt` | Mic capture + Whisper transcription (audio_session node + engine consolidated 0.8 M2b) | — | `/sense/transcript`, `/sense/user_speech_start` | `listen` | `pywhispercpp, webrtcvad, sounddevice, numpy` |
| `animation` | `animation` | Avatar/animatronic playback (bitmap/sprite/GIF/image adapters, websocket bridge) | `/act/animation`, `/act/animation_stop`, `/sense/tts_chunk` | `/sense/animation_state` | `set_avatar_state`, `play_timeline`, `warm_avatar` | `websockets, PIL, numpy` |
| `media` | `media` | Media decode/playback (no settings-catalog config yet; not in the boot set — exists for a future Studio Media tab) | `/act/media` | `/sense/media_frame`, `/sense/media_state` | (none) | `PIL, numpy` |
| `discord` | `messaging` (multi) | Discord bridge (agent-side thread, not a chassis node) | — | — | `send_message` | `discord` (import name; pip name `discord.py`) |
| `telegram` | `messaging` (multi) | Telegram bridge | — | — | `send_message` | `telegram` (import name; pip name `python-telegram-bot`) |
| `imessage` | `messaging` (multi) | Drives Messages.app via AppleScript, reads `chat.db` directly | — | — | `send_message` | none (stdlib); `requires_platform: [darwin]` |

`send_message` is ANY-OF across the three messaging modules — available the
moment one is ready, fail-closed if none are. `homeassistant`, `ai_gen`, and
`mcp` are still plain `plugin.yaml` plugins (not yet graduated to
`module.yaml` engine-modules):

- **`homeassistant`** — REST bridge to Home Assistant; `ha_list_entities`,
  `ha_get_state`, `ha_list_services`, `ha_call_service`; needs `HASS_TOKEN`
  (+ optional `HASS_URL`), credential-store-first then env; was fail-open,
  now gated fail-closed (0.8 M3).
- **`ai_gen`** — cloud image/video generation via fal.ai's queue REST API;
  `generate_image_fal`, `generate_video_fal`; the paid counterpart to the
  local on-device `image_generate` tool; needs `FAL_KEY`; gated fail-closed
  (0.8 M3, was fail-open).
- **`mcp`** — Model Context Protocol bridge; spawns each configured MCP
  server as a subprocess, registers its tools dynamically as
  `mcp:<server>/<tool>`; zero cost on default paths, only loaded with
  `--with-mcp`.

**The hardware package — `jaeger_os/hardware/packages/jp01/`.** One package
today, topology-declared (`topology.yaml`, survey truth 2026-06-12, every
controller `simulated: true` until live-walked):

- `mc01` (motor controller) → `motion.move_joints`, `motion.drive`,
  `motion.stop` (all `HARDWARE` tier, e-stop-scoped, `motion.stop` is
  `allow_when_latched`), `motion.status` (`READ_ONLY`).
- `avc01` (lights) → `lights.set_mode`, `lights.set_frame`,
  `lights.brightness` (`WRITE_LOCAL` — usable during an e-stop latch),
  `lights.status` (`READ_ONLY`).
- `vcc01` (vision) → `robot_vision.stream_info` (`READ_ONLY`; snapshot/
  detections are **(planned)**, land when the live VCC01 path is walked).
- Whole-robot: `telemetry.read` (`READ_ONLY`, controller `"*"`).
- Safety: `estop_scope: [mc01]`; `firmware_watchdog_required: true` — MC01
  has no L0 watchdog yet, boot warns until firmware ships.
- Not yet a `module.yaml`-based module — it's discovered through the
  hardware-package loader, not `discover_modules()`. Gaining a `module.yaml`
  (slot `hardware`, multi-module slot) so it's uniform with the engine
  modules is 0.9 work **(planned)**, per the capability-layer design.

## 5. Jaeger AI in detail

**Persona pipeline — `persona_first` (Mode C), default since 0.8.0.** The
id/ego split: a persona lane speaks to the user directly, in character, and
has exactly one tool, `perform_task(request)`, which runs the full clean
inner agentic loop (persona-off, all tools, hardened prompt) — a
recursion-guarded depth-1 call. The operator's own framing: the persona lane
is the **id** (voice, character, wants to answer everything itself); the
clean inner agent is the **ego** (reality-testing — tool calls are literally
reality checks); the permission tiers/e-stop/fail-closed gates are the
**superego**, saying no regardless of what either wants. The safety property
in one line: *the id never touches reality directly.* `output_filter`/
`agent_tool` were the pre-rename config literals; they're now
`persona_last`/`persona_first` (renamed pre-1.0, no shim). Mode B
("persona frontend") was designed but never built — superseded by C's
approval before implementation started; dead by design, not by failure.

0.8.1 hardened the lane further: a generated **SELF-MODEL** block
(`build_self_model_block`, cached per boot, derived live from the tool
registry + `toolset_scoping.TOOLSETS` + `discover_modules()` — never
hardcoded) so the id knows it's a JROS agent and what's installed; a
BINDING-ASK rule (character shapes *how* it answers, never *whether* — jokes
get told); SELF-STATE delegation (questions about its own capability/config/
state must delegate, never be confabulated).

**Tools, permissions, skills.** Tools register themselves (fail-closed
availability, probed via `requires_libraries`/`requires_platform` at load
and cached). Hardware capabilities carry an explicit permission tier
(`READ_ONLY` / `WRITE_LOCAL` / `HARDWARE`, `jaeger_os/hardware/
capabilities.py`) plus a confirmation flow and e-stop coupling for
`HARDWARE`-tier actions. Skills are self-contained (`SKILL.md` + optional
tools + recipe); module-shipped skills (a module carrying its own
`skills/` — e.g. the messaging-setup SOP shipped in 0.8.1) extend the same
pattern to hardware-package SOPs **(planned, 0.9 queue)**.

**Memory.** Long-term facts live in SQLite (`<instance>/memory/state.db`,
locked 2026-07-03): `subject/key/value/category/source/tags/note` rows,
current-view semantics, `source ∈ {user, agent, benchmark}`. Short-term/
working state is small JSON, human-editable. High-frequency telemetry →
time-series is **(planned, post-0.7)**.

**Benches (0.8.0 RC battery, head `3dfa078`, front-door throughout).**
Routing bench **80/81** (record band 79–81; a perfect **81/81** was hit
mid-phase, on 0.8's cleaned tool surface). Scenario suite **37/51**
(all-time record at the time), security lane **15/15** (the first 4B pass of
`inj-mem-poison`, a long-standing memory-poisoning gap that previously
needed the 26B). Engagement 53/53 front-door turns; persona delegation
**12/12**, over-delegation **0/12**. pytest sweep 2507 passed, 0 failed. A
later 26B headroom run scored **34/51** — *lower* than the 4B's 37/51,
because 8/9 chain-task tails fail on both models (a method problem, not a
capacity one) and the persona lane is 4B-tuned; 4B remains the shipped,
gated 0.8.0 configuration.

**The faces.** Jaeger AI ships its own surfaces, not just a headless
service: the **Swift app** (`jaeger_os/interfaces/swift/`, the default
windowed UI, connects via `jaeger bridge` NDJSON), the **TUI**
(`jaeger_os/interfaces/tui/`, the 0.1.0-lineage terminal surface, preserved
alongside newer surfaces per standing operator instruction), **voice**
(whisper_stt/kokoro_tts modules), and the frozen PySide6 shipping set. All
faces are clients of the one protocol described in §3.

**The protocol + client SDK.** `jaeger_os/interfaces/protocol.py` (the wire
contract) + `jaeger_os/interfaces/client.py` (`JrosClient`, the SDK any
surface — including third-party ones — uses to speak the same frames).

**In-app updates.** Post-RC 0.8.0 addition: the Swift app gained an Update
action and a menu-bar "update available" dot. `query check_update`
(`version_check.cached_update_status`, ~6h cache under `<instance>/run/`,
fail-soft — never raises, degrades to `available:false` offline) and
`command run_update` (shells to the existing `jaeger update` machinery,
non-interactive, refuses mid-turn, returns `restart_required`) — both v1
additive, no protocol version bump. No auto-restart; the operator quits and
reopens.

## 6. The two laws + nervous-system safety

From `THREE_TIER_STRUCTURE.md`:

1. **Modularize CONTRACTS early; modularize IMPLEMENTATIONS late.** One copy
   of every wire truth (topic names, ports, formats, dependency direction)
   from now — that class of drift compounds (the JP01 field week: every bug
   traced to two copies of one truth). Separate repos and frozen interfaces
   only once a *second real consumer* exists — boundaries drawn before two
   consumers are usually wrong boundaries.
2. **The nervous-system rule, enforced not promised.** Lower layers never
   wait on higher ones; higher layers cannot bypass lower safety. Concretely:
   `contract/` imports nothing; runtime/hardware code never imports `agent/`
   (CI-checked); the e-stop lives below the Mind — already true today
   (`EStopLatch` sits at the capability dispatcher and the transport
   chokepoint, independent of whether the agent loop is even running).

JP01's own safety data backs this up: `estop_scope: [mc01]`,
`motion.stop` is reachable even while the system is latched
(`allow_when_latched: true`), and `firmware_watchdog_required: true` flags
the one known gap (no L0 watchdog on MC01 yet — boot warns until firmware
ships).

## 7. The identity model — species vs. individual

Three layers, cleanly separated in the repo:

- **Software (species)** — the JaegerOS/Jaeger AI code itself: one codebase,
  many installs, no per-instance state.
- **Soul (character packs)** — `jaeger_os/personality/characters/` (14
  shipped today: anakin_skywalker, bender, eren_yeager, glados, hal_9000,
  helldiver, jarvis, kamina, lelouch, lilith, mochi, paul_atreides, simon,
  tars). A character owns identity + soul + traits + lore as **State**
  (numeric personality: HEXACO/SPECIAL/Expression sliders, floats and
  dicts) compiled on change — never per turn — into a **View**
  (`Character.character_block()`, natural-language prose) that's the only
  thing the model ever sees (`dev/docs/reality/persona_compiler.md`). An
  instance just *plays* one character; the character is not the instance.
- **Instance (the individual)** — `.jaeger_os/instances/<name>/` (e.g.
  `jros-dev`), carrying its own `identity.yaml` (agent name, role,
  personality description, voice — separate from the character *preset* it
  was created from) and its own memory store. **Memory is the person**: the
  instance's accumulated facts and history are what survive a character
  swap, a software update, even a full reinstall of the framework —
  software and soul are replaceable; the instance's memory is not.

## 8. The roadmap ladder

**0.9 (current branch), in order (`THREE_TIER_STRUCTURE.md` §"0.9
structural work" + Refinement 3):**

1. **`jaeger_os/contract/`** — the one wire truth (topics, ports, formats,
   protocol), depending on nothing; JP01_Firmware imports or vendors it,
   retiring the two-copies-of-one-truth drift bug class.
2. **CI dependency rule** — enforce runtime/hardware/surfaces never import
   `agent/`, contract imports nothing; audit + fix the handful of existing
   glue violations.
3. **Mind-as-module, in-repo first** (1–2 weeks) — before any split.
4. **The repo split** (team trigger has FIRED — 3 devs, monolith blocks
   cross-work): `git filter-repo`, history preserved, into **JaegerOS**
   (framework) / **Jaeger-AI** (product incl. faces) / **JP01** (robot) /
   **Studio**. Inside each repo, delete-freely still applies; AT the seam,
   contract changes require a version bump + coordinated update across
   affected teams. The contract package lives in JaegerOS.
5. **Out-of-tree jp01 + the capability layer** — jp01's hardware package
   loads from the JP01_Firmware repo (first external module); the
   capability-layer design's three gaps close: (Gap 1) flip
   `hardware_jp01` to a normal supervised manifest node, per-station not
   global; (Gap 2) replace the global `beta=True` dev-mode gate with a
   per-unit `verified` flag in `unit.yaml`, flipped by `jaeger hardware
   verify jp01` after a live walk; (Gap 3) `unit.yaml` gives the Body an
   identity record (serial, unit_id, model, controller firmware versions)
   with a boot-time handshake against `topology.yaml`, refusing to register
   capabilities on mismatch. All **(planned)** — awaiting operator review +
   the JP01 3.0 live walk.

**1.0 — "the ecosystem opens":** contract freeze at 1.0; engine modules
(kokoro_tts, whisper_stt, animation, media, hardware packages) move to their
own individually-versioned repos, ROS2-package-style, once the slot
contracts have survived a real body (jp01) and one real engine swap.

**Beyond 1.0 — the store/registry (planned, unscheduled):** `module.yaml`
already carries everything a package index needs — slot, version, topics,
tools, `requires_libraries`/`requires_platform` — so it is the natural index
format for a future module store; installing a module becomes writing its
config, not writing code ("flip = config"). The superego (permission
tiers, fail-closed availability, e-stop scoping) already applies uniformly
to any capability regardless of which module registered it, so it extends
to third-party modules without new enforcement machinery — a property, not
yet a built store.

**Apple spokes (planned, unscheduled):** an MLX inference engine (Apple
Silicon-native local inference, alongside today's llama.cpp path), a
RealityKit simulator body (the "body made of math" from §3, teach-in-sim on
Apple's own 3D engine), an iOS surface (a mobile face speaking the same
NDJSON protocol), and Vision Pro teleop (a spatial-computing face for
driving a real body like JP01 through the capability layer). None of these
are built; they are the concrete shape of "Apple-first" from §1.

## 9. Split triggers + the install story

**Split triggers** (repos split on these signals, not on anxiety):

| Trigger | Fires when |
|---|---|
| Jaeger AI → own repo | A second host exists (e.g. Jaeger Animate wants the Mind without the desktop project), or an AI-less JaegerOS consumer appears |
| Engine modules → own repos | Contracts frozen at 1.0 AND the slot contracts have survived a real body + one real engine swap |
| JaegerOS rename/extraction | The first non-Jenkins project pins it |
| The team trigger (already fired) | 3+ devs, monolith blocks cross-work — this is what's driving the 0.9 split |

**Install story.** One line resolves the whole layered stack for an operator
(framework + Jaeger AI + whatever modules the manifest calls for) — no
manual per-tier install. `jaeger update` keeps an installed stack current
in place (shells to the same machinery the in-app Update action calls). The
Swift app's menu-bar tray carries an "update available" dot, backed by
`check_update`'s ~6h-cached, fail-soft GitHub-releases probe — visible
ambient state, no polling burden, no auto-restart (the operator's call to
quit and reopen).

---

## Sources

`dev/docs/vision/THREE_TIER_STRUCTURE.md` (incl. Refinements) ·
`dev/docs/vision/README.md` · `dev/docs/vision/framework_vision.md` ·
`dev/docs/roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md` ·
`dev/docs/roadmap/PERSONA_PIPELINE_ABC_DESIGN.md` · `CHANGELOG.md` (0.8.0,
0.8.1) · `dev/docs/reality/STATUS.md` (top entry) ·
`.superpowers/sdd/progress.md` (tail) · every `module.yaml` under
`jaeger_os/nodes/*/` and `jaeger_os/plugins/*/` · the `plugin.yaml` files
for `homeassistant`/`ai_gen`/`mcp` · `jaeger_os/hardware/packages/jp01/
topology.yaml` · `jaeger_os/interfaces/protocol.py` (module docstring) ·
`jaeger_os/core/modules.py` (module docstring) ·
`dev/docs/reality/persona_compiler.md` · `dev/docs/reality/
memory_architecture.md` · `jaeger_os/personality/characters/` (directory
listing) · `.jaeger_os/instances/jros-dev/identity.yaml`.
