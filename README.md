<h1 align="center">JaegerOS</h1>

<p align="center">
  <em>The Jaeger robot operating framework — bus, nodes, modules & slots, supervisor, safety, wire contract, capability layer. The Apple-native nervous system every Jaeger project builds on. Useful without any AI.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerOS/releases"><img src="https://img.shields.io/badge/version-0.9.0--dev-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

## What it is

JaegerOS is the **framework** tier of the Jaeger ecosystem — the way ROS
is to a robot stack: libraries, standards, and tooling that other things
**build on**, pinned to a release, never forked. It is deliberately
**useful without any AI** — a robot body can boot, speak, listen, and
move on JaegerOS alone.

It ships:

- **`contract/`** — the one wire truth: topics, ports, wire formats, the
  `module.yaml` schema, the capability-layer API. Imports nothing —
  CI-enforced (`dev/tests/jaeger_os/contract/test_no_inward_imports.py`).
- **`transport/`** — the Bus (in-process + ZMQ), broker, codec.
- **`nodes/`** — the `Node` base class (four-phase lifecycle: setup →
  tick → teardown → health), the module/slot runtime singleton, and the
  generic body-node types (`motor/`, `light/`, `vision/`) that stay
  hardware-vague — instance-level adapters supply the wire specifics.
- **`hardware/`** — the capability layer: a hardware package declares
  `capabilities:` in its topology manifest; the framework materializes
  them into permission-tiered tools at boot. Includes the JP01 reference
  package shape.
- **`app/`** — the app manifest + supervisor + surfaces framework
  (`jaeger.toml`'s schema: what an app IS MADE OF).
- **`core/audio`**, **`core/tools`**, **`core/voice`** — shared
  substrate every module and the Mind pin: the mic/speaker session
  library, the tool contract (`ToolDef` + registry), and voice/slot
  resolution.
- **`core/safety`** — the nervous-system floor: 6-tier permissions, the
  hardline command blocklist, credential-path guard, redaction,
  per-session trust. Enforceable at the capability dispatcher even when
  the Mind never boots.
- **`core/modules.py`** — `discover_modules()`, the module/slot loader,
  including the out-of-tree entry-point seam (`jaeger_os.module_roots`)
  that lets sibling repos register modules without JaegerOS ever naming
  them.

**JaegerOS does not ship a CLI, an agent loop, or an inference stack.**
Those are [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI)'s job
— JaegerOS is a pinned dependency, not a product you run directly.

## Install

```bash
git clone https://github.com/JenkinsRobotics/JaegerOS.git
cd JaegerOS
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

`jaeger-os` on PyPI is the eventual path; until it has published
releases, downstream repos (JaegerAI, the engine modules) pin this repo
via a `file://` path dependency during staging — see their own
`requirements.txt` headers for the real pin story.

## Quick start — build a module + manifest

A module is a directory with a `module.yaml` manifest and a factory
function; `discover_modules()` finds it (in-tree, or out-of-tree via the
`jaeger_os.module_roots` entry point) and binds it to a **slot**:

```bash
mkdir -p my_module/nodes/my_module
cat > my_module/nodes/my_module/module.yaml <<'YAML'
module: my_module
slot: my_slot
version: 0.1.0
consumes: []          # topics this module subscribes to
produces: []           # topics this module publishes
tools: []               # tool names this module serves
factory: my_module.nodes.my_module:make_node
config: my_module
YAML
```

`factory:` points at a `(bus, config) -> Node` callable — see
[`jaeger_os/nodes/base.py`](jaeger_os/nodes/base.py) for the `Node`
contract, and
[`JaegerKokoroTTS`](https://github.com/JenkinsRobotics/JaegerKokoroTTS)'s
`nodes/kokoro_tts/` for the canonical shape (manifest + node + engine +
config slice + module-contract tests) this pattern mirrors.

Run the framework's own suite:

```bash
pytest dev/tests           # 279 tests, 0 failures — framework standalone
ruff check                 # lint
```

## Architecture

JaegerOS sits at the bottom of the Jaeger ecosystem's four-tier map — the
one thing every other repo depends on, depending on nothing above it:

```
JaegerOS      ← YOU ARE HERE. Bus · Node · modules/slots · supervisor ·
                safety · contract · capability layer. contract/ imports
                nothing; runtime/hardware never import agent/ (CI-checked).

JaegerAI      ← the Mind — the turnkey agentic product. Pins this repo.

Modules       ← engines (JaegerKokoroTTS, JaegerWhisperSTT), hardware
                packages (JP01), characters. Each pins this repo only.

Projects      ← the assembled things (JP01 the robot, a desktop
                companion) — pull in JaegerOS + whichever modules they need.
```

The nervous-system rule is enforced, not promised:
`dev/tests/jaeger_os/core/test_layering.py` AST-scans the tree for any
module-level import of an agent/Mind-owned prefix — empty allowlist by
design. See
[`dev/docs/vision/THREE_TIER_STRUCTURE.md`](dev/docs/vision/THREE_TIER_STRUCTURE.md)
for the full reasoning and
[`dev/docs/vision/JAEGER_ECOSYSTEM.md`](dev/docs/vision/JAEGER_ECOSYSTEM.md)
for the whole-ecosystem rundown (module inventory, the connection rule,
the roadmap ladder).

## Ecosystem

| Repo | Tier | What |
|---|---|---|
| **JaegerOS** | Framework | This repo — bus, node, modules/slots, supervisor, safety, contract, capability layer. |
| [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI) | Mind (product) | The turnkey agentic product: loop, tools, skills, memory, persona, local inference, and its own faces (chat app, TUI, voice). Pins this repo. |
| [JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS) | Engine module (`tts` slot) | Streaming Kokoro speech synthesis. Pins this repo only — never JaegerAI. |
| [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT) | Engine module (`stt` slot) | Two-pass Whisper transcription with VAD + wake word. Pins this repo only — never JaegerAI. |
| JP01 | Project (Body) | The reference hardware Jaeger — the first repo to consume out-of-tree modules and hardware packages the way this framework is built for. |

## Development

```bash
pytest dev/tests           # the framework's own test suite (279 passed, 0 failed, standalone)
ruff check                 # lint
```

Follow [`CONVENTIONS.md`](CONVENTIONS.md) — no doc describes behavior
the code doesn't implement yet (mark it `(planned)` instead), and every
commit that changes behavior keeps its `STATUS.md`/docs truthful in the
same commit.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
