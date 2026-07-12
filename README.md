<h1 align="center">JaegerKokoroTTS</h1>

<p align="center">
  <em>The tts-slot engine module for the Jaeger ecosystem — streaming Kokoro speech synthesis, pins JaegerOS only, standalone module-contract tests, field-proven on JP01.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerKokoroTTS/releases"><img src="https://img.shields.io/badge/version-0.9.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

## What it is

JaegerKokoroTTS is an **engine module** — the `tts` slot of the Jaeger
ecosystem. The module IS the engine: this package owns the generic
`TTSNode` + `Synthesizer` protocol, the real `KokoroTTS` engine, a
persistent audio player, its own settings-catalog config slice, and its
`module.yaml` manifest (module/slot/version/consumes/produces/tools/
factory) — the seam
[`discover_modules()`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/jaeger_os/core/modules.py)
reads to bind a slot to this module at boot.

It pins [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) **only**
— never [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI) — so a
robot body can speak without the AI product installed at all. Two real
consumers today: the JaegerAI product and JP01's non-AI console.

- **One persistent output stream** — opens once at warm/first `speak()`
  and stays open for the process lifetime; no per-utterance stream
  churn, no audible device power-cycle clicks.
- **`Synthesizer` protocol** — `TTSNode` (the generic node) is decoupled
  from `KokoroTTS` (the real engine) behind a small protocol, so a
  future sibling module (e.g. a different TTS backend) can bind the
  same `tts` slot without touching the node.
- **Bus contract** — `/act/speech` in, `/sense/spoken` + `/sense/tts_chunk`
  out, the `text_to_speech` tool. Declared once, in `module.yaml` —
  nowhere else.

## Install

```bash
git clone https://github.com/JenkinsRobotics/JaegerKokoroTTS.git
cd JaegerKokoroTTS
pip install -e .
```

Pins `jaeger-os` (framework substrate: transport, `nodes.base`,
`core.audio`, `core.instance.setting_meta`) plus Kokoro's own
third-party libraries (`kokoro`, `sounddevice`, `numpy`,
`huggingface_hub`) — see `requirements.txt`. While staging pre-release,
the `jaeger-os` dependency is a `file://` path reference to a sibling
`JaegerOS` clone; a real version-range pin replaces it once `jaeger-os`
has published releases.

## Quick start

Prove the module contract — manifest parses, the factory builds a live
node, the bus contract round-trips — without touching audio hardware or
loading the Kokoro model weights:

```bash
pytest jaeger_kokoro_tts/nodes/kokoro_tts/tests
# or run it directly:
python -m jaeger_kokoro_tts.nodes.kokoro_tts.tests.test_module_contract
```

Bind the `tts` slot into a running JaegerOS instance — `discover_modules()`
finds this module automatically once it's installed (it registers itself
under the `jaeger_os.module_roots` entry-point group; JaegerOS never
imports or names this package directly):

```python
from jaeger_os.core.modules import discover_modules
modules = discover_modules()
modules["tts"]  # -> this module, factory jaeger_kokoro_tts.nodes.kokoro_tts:make_tts_node
```

## Architecture

JaegerKokoroTTS is an **engine module** — the third tier in the Jaeger
ecosystem's four-tier map, pinning JaegerOS and consumed by JaegerAI or
any other JaegerOS project that needs the `tts` slot filled:

```
JaegerOS      ← the framework this repo pins. Never forked, never edited.

JaegerAI      ← the Mind — one of two real consumers of this module.
                Installs it as an optional extra (.[kokoro_tts]).

Modules       ← YOU ARE HERE. tts slot. Pins JaegerOS ONLY — never
                JaegerAI — so a robot body can speak standalone.

Projects      ← JP01's non-AI console — the other real consumer.
```

See
[`JAEGER_ECOSYSTEM.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/JAEGER_ECOSYSTEM.md)
for the whole-ecosystem picture (module inventory, the connection rule)
and
[`THREE_TIER_STRUCTURE.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/THREE_TIER_STRUCTURE.md)
for the tier-map reasoning — both canonical in JaegerOS, linked here
rather than duplicated.

## Ecosystem

| Repo | Tier | What |
|---|---|---|
| [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) | Framework | Bus, node, modules/slots, supervisor, safety, contract, capability layer. This repo pins it, only it. |
| [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI) | Mind (product) | Installs this module as an optional extra for voice. |
| **JaegerKokoroTTS** | Engine module (`tts` slot) | This repo. |
| [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT) | Engine module (`stt` slot) | The listening sibling — same discipline, own repo. |
| JP01 | Project (Body) | Consumes this module directly for its non-AI console. |

Two more repos round out the ecosystem without being part of the tier map
themselves: [JaegerTemplate](https://github.com/JenkinsRobotics/JaegerTemplate)
(the conventions every new ecosystem repo — this one included — started
from) and [JP01_Firmware](https://github.com/JenkinsRobotics/JP01_Firmware)
(the robot's Mac + Jetson body-side code JP01's console pairs with).

## Development

```bash
pytest jaeger_kokoro_tts/nodes/kokoro_tts/tests   # module-contract smoke (7 tests)
pytest dev/tests                                   # HF-offline integration test
```

The two engine modules together gate at 13/13 module-contract tests
(7/7 here + 6/6 in [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT))
— the split's per-repo, no-hardware-touched proof that each stands alone.

No doc in this repo describes behavior the code doesn't implement yet
(mark it `(planned)` instead) — see JaegerOS's `CONVENTIONS.md` for the
full ecosystem ruleset this module follows.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
