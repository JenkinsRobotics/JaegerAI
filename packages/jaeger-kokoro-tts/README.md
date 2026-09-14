<h1 align="center">JaegerKokoroTTS</h1>

<p align="center">
  <em>Turnkey Kokoro speech synthesis for JaegerOS robots — correlated playback, barge-in, bounded queues, health telemetry, and no AI-stack dependency.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerKokoroTTS/releases"><img src="https://img.shields.io/badge/version-0.12.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

> **Jaeger ecosystem identity**
> ID: `org.jenkinsrobotics.tts.kokoro` · Type: **module** ·
> Slot: `tts` · Kind: `engine` · Implementation: `kokoro`

## What it is

JaegerKokoroTTS is an **engine module** — the `tts` slot of the Jaeger
ecosystem. The module IS the engine: this package owns the generic
`TTSNode` + `Synthesizer` protocol, the real `KokoroTTS` engine, a
persistent audio player, its own settings-catalog config slice, and its
`module.yaml` manifest (stable ID, type, implementation, slot, version,
topics, tools, and factory) — the seam
[`discover_modules()`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/jaeger_os/core/modules.py)
reads to bind a slot to this module at boot.

It pins [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) **only**
— never [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI) — so a
robot body can speak without the AI product installed at all. Two real
consumers today: the JaegerAI product and JP01's non-AI console.

- **One persistent hardware stream** — JaegerOS `audio_io` owns the device
  and keeps it open by default; Kokoro never competes with chimes or another
  producer for the speaker.
- **Correlated completion** — PCM and speaker drain messages carry the
  speech request id. An unrelated notification cannot acknowledge the wrong
  utterance, and every producer in a shared burst gets a completion edge.
- **Robot-safe failure behavior** — bounded queue, text/rate limits, drain
  timeout, immediate barge-in, shutdown cancellation, and automatic output
  restart when hardware callbacks stop moving.
- **Operational health** — queue depth, warm state, current request,
  success/failure counters, audio backlog, underruns, output restarts, and
  the last hardware error use normal JaegerOS node health.
- **`Synthesizer` protocol** — `TTSNode` (the generic node) is decoupled
  from `KokoroTTS` (the real engine) behind a small protocol, so a
  future sibling module (e.g. a different TTS backend) can bind the
  same `tts` slot without touching the node.
- **Bus contract** — `/act/speech/say` in, `/act/speech/spoken` + `/act/speech/chunk`
  out, the `text_to_speech` tool. Declared once, in `module.yaml` —
  nowhere else.

## Install

```bash
git clone https://github.com/JenkinsRobotics/JaegerKokoroTTS.git
cd JaegerKokoroTTS
pip install -e .
```

Pins `jaeger-os` (transport, node lifecycle, audio driver, and settings
metadata) plus Kokoro's runtime libraries — see `requirements.txt`.
`sounddevice` is used only by the standalone direct player; a JaegerOS app
routes audio through its configured driver.

## Layout

The package root IS the module — the canonical module-repo shape from
[Jaeger-Template](https://github.com/JenkinsRobotics/Jaeger-Template)'s
`{{package_name}}/`, matching the sibling JaegerWhisperSTT:

```
JaegerKokoroTTS/            ← the repo: packaging, docs, license
├── pyproject.toml
├── README.md
├── requirements.txt
└── jaeger_kokoro_tts/      ← the importable package, and the module
    ├── __init__.py          ← exports the module.yaml factory
    ├── module.yaml          ← slot, topics, tools, factory, requires
    ├── config.py            ← this module's settings-catalog slice
    ├── node.py              ← TTSNode + the Synthesizer Protocol
    ├── engine.py            ← the Kokoro engine
    ├── bus_player.py        ← publishes to the audio driver
    ├── persistent_player.py ← owns a device directly (no-bus path)
    ├── cli.py               ← `jaeger-kokoro-tts` standalone driver
    ├── module_roots.py      ← the discovery entry point
    └── tests/
```

Before 0.12.0 the module sat two levels deeper, at
`jaeger_kokoro_tts/nodes/kokoro_tts/` — inherited from its old home
inside `jaeger_os/nodes/`, where a `nodes/` package holding many nodes
made sense. In a repo shipping exactly one module it held one entry,
inside a package already called `jaeger_kokoro_tts`. Both levels are
gone; `discover_modules()` already handled a root that *is* a module.

The remaining nesting — package inside repo — is Python packaging, not
Jaeger: `import jaeger_kokoro_tts` resolves to a directory of exactly
that name, so the code cannot live at the repo root.

## Standalone CLI

Exercise the engine with no app around it:

```bash
jaeger-kokoro-tts speak "hello there"
jaeger-kokoro-tts speak "hello" --voice bm_george
jaeger-kokoro-tts save "hello there" out.wav   # no audio device needed
jaeger-kokoro-tts voices
jaeger-kokoro-tts bench --no-play
```

`save`, `voices` and `bench --no-play` open no device, so they work on a
build box or over SSH. `speak` uses the system default output directly —
there is no device flag, because a CLI process with no other nodes has
nothing to share a speaker with. Inside an app the engine takes the bus
instead and publishes to `/act/speaker/pcm` so the audio driver owns the
device.

## Robot configuration

The module works with no configuration. These are the supported production
knobs:

```toml
[config.tts]
voice = "af_heart"
lang = "a"
warm = true
queue_maxsize = 32
max_text_chars = 4000

[config.audio_io]
playback_rate = 24000
keep_output_open = true
audio_backend = "avaudio"
```

Kokoro output is always 24 kHz mono; sample rate is deliberately not a
Kokoro setting. Labeling those samples with another rate causes slow,
fast, or pitched playback. `keep_output_open = false` is available for
battery-sensitive systems at the cost of device-open latency and a greater
risk of audible power-cycle pops.

## Quick start

Prove the module contract — manifest parses, the factory builds a live
node, the bus contract round-trips — without touching audio hardware or
loading the Kokoro model weights:

```bash
pytest jaeger_kokoro_tts/tests
# or run it directly:
python -m jaeger_kokoro_tts.tests.test_module_contract
```

Bind the `tts` slot into a running JaegerOS instance — `discover_modules()`
finds this module automatically once it's installed (it registers itself
under the `jaeger_os.module_roots` entry-point group; JaegerOS never
imports or names this package directly):

```python
from jaeger_os.core.modules import discover_modules
modules = discover_modules()
modules["tts"]  # -> this module, factory jaeger_kokoro_tts:make_tts_node
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
python -m pytest -q
```

The suite covers discovery/factory behavior, request/ack correlation,
backpressure, background warm-up, offline model loading, playback timeouts,
and barge-in without requiring speakers.

No doc in this repo describes behavior the code doesn't implement yet
(mark it `(planned)` instead) — see JaegerOS's `CONVENTIONS.md` for the
full ecosystem ruleset this module follows.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
