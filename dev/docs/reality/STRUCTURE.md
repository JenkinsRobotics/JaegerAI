# JROS repository structure — reviewer guide

**Status:** current as of branch `0.5.0` tip `697587f`
**Audience:** reviewers / new contributors / future-you trying to
remember where a thing lives.

## The identity statement

> **JROS = Hermes-in-`agent/` + ROS-in-`nodes/` + a shared
> `transport/` that lets them talk.**

Other projects own ONE of those (Hermes owns the agent, ROS owns
the peripheral nodes, LM Studio owns the model).  JROS is the
intersection.  The folder layout reflects this exactly — read the
top-level `jaeger_os/` directory and the architecture is visible.

## At a glance

```
JROS/
├── jaeger_os/                — the Python framework
├── apps/                     — Swift renderer (in-tree, out-of-process)
├── dev/docs/                 — design + audits + roadmaps
├── dev/tests/                — pytest suite (~2000 tests)
├── dev/benchmark/            — agent corpus + bench harness
├── dev/scripts/              — developer utilities
├── dev/tools/                — voice/audio reference clients
├── docs/                     — operator-facing docs
├── sandbox/                  — in-repo instance for dev (gitignored)
├── scripts/                  — install / setup
├── CHANGELOG.md
├── README.md
├── LICENSE                   — Apache 2.0
├── pyproject.toml
├── requirements.txt
├── launch / launch.py        — main entry point shim
├── jaeger                    — operator CLI console shim
├── run.sh                    — daemon mode
└── install.sh
```

## `jaeger_os/` — the framework

```
jaeger_os/
├── agent/             ← THE CONSCIOUS NODE ("the Hermes")
├── nodes/             ← THE UNCONSCIOUS NODES ("the ROS")
├── transport/         ← THE BRIDGE
├── skill_tree/        ← META-SYSTEM (XP progression across both)
├── personality/       ← character config (HEXACO + SPECIAL + sliders)
├── timeline/          ← multi-track performance scheduler
├── core/              ← INFRASTRUCTURE shared by agent + nodes
├── plugins/           ← 3rd-party engine wrappers
├── interfaces/        ← operator surfaces
├── cli/               ← operator CLI subcommands
├── topics.py          ← bus SSOT (msgspec.Struct)
├── main.py            ← boot path
└── ...
```

### `agent/` — everything cognitive

```
jaeger_os/agent/
├── loop/              jaeger_agent.py + runtime_bridge.py (drive_one_turn)
├── adapters/          model clients (local_llama, MLX, external_model HTTP)
├── dialects/          Hermes / ChatML / Llama-3 / Mistral tool format
├── parsing/           response → tool-call extractor
├── schemas/           ToolDef, tool_registry, toolsets, message_types
├── util/              context_guard, prompt_builder, retry_utils
│
├── tools/             ← the agent's 30-module tool surface
│                        files, time_and_math, memory, scheduling, web,
│                        code, speak, vision, host, credentials, etc.
│
├── skills/            ← v3 skill bundles (operator content)
│                        27 bundles: computer_use_v1, macos_computer_v1,
│                        apple/, autonomous-ai-agents/, creative/, etc.
│
├── skill_registry/    ← v3 skill LOADER + manifest parser
│                        skill_loader.py, playbook_skills.py,
│                        manifest_v3.py, curator.py, toolsets.py, etc.
│
├── prompts/           ← system prompt assembly
│                        assemble.py, rules.py, prompts.py, reflection.py
│
├── personas/          ← wizard prefill templates (jarvis.yaml, ...)
├── prompt_assets/     ← raw prompt text repository
├── runners/           ← ThinkingRunner (deep-think queue)
│
└── README.md
```

### `nodes/` — peripheral subsystems

```
jaeger_os/nodes/
├── base.py            Node base class — shared
├── runtime.py         ensure_*_node factories — shared
│
├── tts/               speech synthesis (Kokoro)
├── audio_session/     mic + AEC + VAD + STT + filters
├── stt/               back-compat shim → audio_session
├── animation/         face / avatar rendering
│   ├── node.py         AnimationNode
│   ├── base.py         AnimationAdapter Protocol + FrameBuffer
│   ├── bridge.py       WebSocket bridge → Swift app
│   └── adapters/       L1-L4 adapters (vendored from Mochi):
│       ├── image_adapter.py     L1 static raster
│       ├── bitmap_adapter.py    L1 1-bit packed
│       ├── sprite_adapter.py    L2 sheet crop
│       ├── gif_adapter.py       L3 animated GIF/APNG
│       └── math_adapter.py      L4 procedural Python script
├── vision/            camera frame capture (USB + TCP)
├── motor/             actuator control (universal Protocol; locked)
└── light/             LED patterns (universal Protocol; locked)
```

### `transport/` — the bus layer

```
jaeger_os/transport/
├── bus.py             Bus abstract base + SubscriberFn
├── codec.py           JSON / MessagePack adaptive picker
├── inproc_bus.py      queue.Queue (monolithic mode)
├── zmq_bus.py         ZeroMQ (future multiprocess mode)
└── broker.py          XPUB ↔ XSUB proxy for ZMQ
```

### `skill_tree/` — the meta-system

```
jaeger_os/skill_tree/
├── schema.py          SkillNode, SkillTree, XpAward (msgspec)
├── registry.py        thread-safe registry + persistence
├── xp_emitter.py      bus subscriber → registry
└── seed.py            default skill catalog (animation, voice,
                       vision, motor, light, core)
```

### `core/` — strictly shared infrastructure

After the 0.5.0 reorg, `core/` contains ONLY what both the agent
side and the peripheral nodes use:

```
jaeger_os/core/
├── audio/             AEC + chimes + reference buffers
├── background/        cron + deep-think board
├── bench/             bench harness
├── diagnostics/       health probes
├── instance/          InstanceLayout (the User bucket)
├── memory/            SQLite backend
├── models/            GGUF / MLX client builders
├── runtime/           process slot, log rotation
├── safety/            Three Laws + permission tiers
├── voice/             parse_gate, non_speech, reply_cleaner
└── credentials.py     per-instance secrets
```

What used to live here but moved to `agent/`:
- `core/tools/`        → `agent/tools/`
- `core/skills/`       → `agent/skill_registry/`
- `core/prompts/`      → `agent/prompts/`
- `core/runners/`      → `agent/runners/`

Plus moves from root:
- `jaeger_os/skills/`   → `agent/skills/`     (v3 bundles)
- `jaeger_os/personas/` → `agent/personas/`
- `jaeger_os/prompts/`  → `agent/prompt_assets/`

### `personality/`, `timeline/`, `cli/`

```
jaeger_os/personality/
├── schema.py          HEXACO + SPECIAL + Expression + Domains
└── compose.py         compose_block() → system prompt fragment

jaeger_os/timeline/
├── schema.py          Timeline / Track / Clip msgspec
└── runner.py          wall-clock dispatcher → bus topics

jaeger_os/cli/
├── __init__.py        argparse router
├── _common.py         colour helpers + instance resolver
├── skills_cmd.py      jaeger skills [overview|tree|view]
├── instances_cmd.py   jaeger instances [list|show|switch]
├── personality_cmd.py jaeger personality [view|set <field> <value>]
├── status_cmd.py      jaeger status
└── roadmap_cmd.py     jaeger roadmap
```

### Plugins + interfaces

```
jaeger_os/plugins/
├── kokoro_tts/        local TTS wrapper
├── whisper_stt/       local STT wrapper
├── discord/, telegram/, imessage/
├── mcp/               Model Context Protocol client
├── messaging_gateway.py
└── voice_loop.py      standalone voice daemon

jaeger_os/interfaces/
├── tui/               primary Rich + prompt_toolkit TUI
├── rich_tui/          archived older Rich UI
└── tray/              macOS menu bar tray
```

## `apps/` — out-of-process surfaces

```
apps/
└── JROS-Avatar/       Mac-native Swift Spatial Avatar Renderer
    ├── Package.swift
    ├── README.md
    ├── Sources/JROSAvatar/
    │   ├── AvatarApp.swift     @main + FrameStore
    │   ├── ContentView.swift   connect field + status + canvas
    │   ├── RendererView.swift  current-frame display
    │   ├── WebSocketClient.swift
    │   └── FrameDecoder.swift  [4-byte len][JSON header][RGBA8]
    └── Tests/JROSAvatarTests/  4 round-trip + error tests
```

## `dev/docs/` (architecture + audits + roadmaps)

```
dev/docs/
├── revision_summaries/   per-version retro records (0.1 → 0.4)
├── library_review/       audits of external code (voicellm, mochi,
│                         hermes_supervisor, jp01_firmware)
├── architecture/         load-bearing principles (system_runtime_user)
├── skill_template/       v3 manifest template
│
├── ROADMAP_0.5.md             active roadmap
├── 0.5.0_agent_reorg_plan.md  this reorg's plan doc
├── 0.5.0_swift_renderer_plan.md
├── 0.5.0_timeline_schema.md
├── SKILL_TREE.md
├── SELF_MODIFICATION_BOUNDARIES.md
├── STRUCTURE.md               this file
└── (many more — see revision_summaries/README.md catalogue)
```

## `dev/tests/` — pytest suite (~2015 tests)

Mirrors `jaeger_os/` directory tree:

```
dev/tests/jaeger_os/
├── core/                 (instance, models, safety, voice, etc.)
├── nodes/                one test module per node
│   ├── test_animation.py
│   ├── test_image_adapter.py
│   ├── test_bitmap_adapter.py
│   ├── test_sprite_adapter.py
│   ├── test_gif_adapter.py
│   ├── test_math_adapter.py
│   ├── test_frame_bridge.py
│   ├── test_animation_e2e.py
│   ├── test_audio_session.py, test_tts.py, test_vision.py, etc.
├── transport/
├── skill_tree/           registry + XpEmitter + seed catalog
├── timeline/             schema + runner
├── personality/          schemas + compose + assemble integration
├── agent/                loop + adapters + dialects + parsing
├── interfaces/           TUI + voice_session tests
├── plugins/              plugin unit tests
├── skills/               v3 manifest tests
├── runtime/              process slot + locks
├── migrations/           version-migration scripts
├── main/                 boot path tests
└── cli/                  operator CLI tests
```

## Top-level entry points

| File | What |
|---|---|
| `launch` / `launch.py` | the operator's main entry — boots TUI, voice loop, etc. |
| `jaeger`               | operator CLI console — `jaeger skills`, `jaeger status`, etc. |
| `run.sh`               | daemon mode (background JROS) |
| `install.sh`           | curl installer target |

## Branches + tags

```
origin/master    — 0.4.0 release tip
origin/0.4.0     — release branch (matches master)
origin/0.5.0     — ACTIVE — 0.5 work happens here
origin/0.3.0-archive  — walked-back 0.3.0 daemon/Swift work
refs/tags/0.4.0  — annotated release tag (+ 0.1.0 / 0.2.x lineage)
```

Naming convention: only `0.X.Y` form (never `v0.X.Y`) —
operator-locked since 0.2.0.

## Standing operator rules

Useful for any external reviewer / contributor:

1. **No `git push` without explicit OK that turn** — local commits
   + tags are fine; push requires direct authorisation.
2. **No new/moved tags without explicit OK that turn** — tags mark
   "ready for main merge."
3. **No `v` prefix on tags** — only `0.X.Y`.
4. **Each robot = one persona.**  No multi-persona switching.
5. **Walk user flows before claiming a UX is shipped.**
6. **Commit at milestones, not after every pass.**
7. **No Claude co-author trailer on commits.**

## Things to know that aren't obvious

1. **Three-bucket architecture** (System / Runtime / User) governs
   the whole codebase since 0.2.1.  `jaeger_os/` is the framework
   (System); `~/.jaeger_os/instances/<name>/` is operator state
   (User).  Boundary is the `InstanceLayout` object.

2. **Conscious / unconscious model** — peripheral nodes filter +
   gate + reflex; the brain only engages on confirmed signals.
   The post-reorg folder layout reflects this: `agent/` is the
   conscious node, `nodes/` is the unconscious ones.

3. **Skill tree is project-wide, not just animation.**  Every node
   + skill has level + XP + prereqs.  Long-term goal: video-game-
   aesthetic visualisation rendering the tree as a radial graph.

4. **Two distinct "skills" concepts** — the post-reorg names
   disambiguate them:
     - `agent/skills/`         = v3 playbooks (workflows the agent
                                  loads at runtime)
     - `agent/skill_registry/` = the loader for the above
     - `skill_tree/`           = XP progression across BOTH agent
                                  skills AND node capabilities

5. **Mochi vendoring** — `/Users/jonathanjenkins/GITHUB/Mochi/` is
   the operator's prior animation engine; the L1-L4 adapters in
   `nodes/animation/adapters/` are distilled from Mochi's
   handlers.  Audit at `dev/docs/library_review/mochi_demo.md`.

## Where to start a review

1. **`CHANGELOG.md`** — read the 0.4.0 + 0.5.0 entries for the
   architectural model.
2. **`dev/docs/ROADMAP_0.5.md`** — what 0.5 is + isn't.
3. **`dev/docs/0.5.0_agent_reorg_plan.md`** — the just-shipped
   reorganisation; explains WHY the folder layout reads the way
   it does.
4. **`dev/docs/SKILL_TREE.md`** — load-bearing pattern.
5. **`dev/docs/revision_summaries/README.md`** — what every other
   doc means + whether it's still current.
6. **`jaeger_os/topics.py`** — the bus SSOT; reading this gives
   the shape of every signal flowing through JROS.
7. **`jaeger_os/main.py`** — the boot path.  Long but mostly
   linear.
8. **`jaeger_os/agent/`** — pick `loop/jaeger_agent.py` then
   `tools/` to see how the brain dispatches.  Or
   `prompts/assemble.py` to see how the system prompt builds.
9. **`jaeger_os/nodes/`** — pick any node (TTS is simplest) to
   see how the bus contract gets implemented on the peripheral
   side.
