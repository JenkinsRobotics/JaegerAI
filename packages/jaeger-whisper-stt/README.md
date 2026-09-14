<h1 align="center">JaegerWhisperSTT</h1>

<p align="center">
  <em>Production local speech-to-text for JaegerOS — six Whisper modes, streaming captions, wake commands, and offline media.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerWhisperSTT/releases"><img src="https://img.shields.io/badge/version-0.13.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

> **Jaeger ecosystem identity**
> ID: `org.jenkinsrobotics.stt.whisper` · Type: **module** ·
> Slot: `stt` · Kind: `engine` · Implementation: `whisper`

## What it is

JaegerWhisperSTT is an **engine module** — the `stt` slot of the Jaeger
ecosystem. The module IS the engine: this package owns
`AudioSessionNode`, the pywhispercpp-backed Whisper engine (six
recognition methods), its own settings-catalog config slice, and its
`module.yaml` manifest (stable ID, type, implementation, slot, version,
topics, tools, and factory) — the seam
[`discover_modules()`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/jaeger_os/core/modules.py)
reads to bind a slot to this module at boot.

It pins [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) **only**
— never [JaegerAI](https://github.com/JenkinsRobotics/JaegerAI) — so a
robot body can listen without the AI product installed at all. Two real
consumers today: the JaegerAI product and JP01's non-AI console.

- **Six selectable recognition methods** — production two-pass, lightweight
  VAD-segment, continuous phrase recognition, phrase partials, rolling-window
  captions, and LocalAgreement streaming. Two-pass uses a fast `base.en` model to gate an
  accurate `medium.en` model: the fast pass makes wake-word matching
  responsive, and the accurate pass commits the final transcript.
- **VAD-segmented** — voice-activity detection drives when a pass runs,
  not a fixed window.
  Wake-word gating (`require_wake_word`) is supported by `vad_segment`,
  `two_pass`, `continuous`, and `phrase_word`. Rolling `window` and
  `local_agreement` commits may split wake words from commands, so directed
  command detection belongs in the app for those two modes.
- **whisper.cpp backend** — via `pywhispercpp`, the same native engine
  that accelerates on Apple Silicon (Metal) without any Python-side
  GPU code.
- **Bus contract** — `/sense/mic/pcm` in; `/sense/stt/transcript`,
  `/sense/stt/speech_start`, and `/sys/gate/decision` out; plus the `listen`
  tool. Declared once, in
  `module.yaml` — nowhere else.
- **Offline media API** — reuse one model across a batch and export TXT, SRT,
  VTT, CSV, or JSON without opening audio hardware.
- **Production tuning** — wake matching, VAD timing, rolling-decode cadence,
  LocalAgreement cursor behavior, and bounded queue sizes are validated config
  fields routed into the selected engine rather than hardcoded demo values.

## Install

```bash
git clone https://github.com/JenkinsRobotics/JaegerWhisperSTT.git
cd JaegerWhisperSTT
pip install -e .
```

Pins `jaeger-os` (framework substrate: transport, `nodes.base`,
`core.audio`, `core.voice`, `core.instance.setting_meta`) plus
Whisper's own third-party libraries (`pywhispercpp`, `webrtcvad-wheels`,
`sounddevice`, `numpy`) — see `requirements.txt`. JaegerOS is not yet on
PyPI, so install its local clone first or use the `bootstrap` extra.

## Layout

The package root IS the module — the canonical module-repo shape from
[Jaeger-Template](https://github.com/JenkinsRobotics/Jaeger-Template)'s
`{{package_name}}/`:

```
JaegerWhisperSTT/           ← the repo: packaging, docs, license
├── pyproject.toml
├── README.md
├── requirements.txt
└── jaeger_whisper_stt/     ← the importable package, and the module
    ├── __init__.py         ← exports the module.yaml factory
    ├── module.yaml         ← slot, topics, tools, factory, requires
    ├── config.py           ← this module's settings-catalog slice
    ├── node.py             ← AudioSessionNode (setup → tick → teardown)
    ├── offline.py          ← reusable file transcription + export API
    ├── cli.py              ← `jaeger-whisper-stt` standalone driver
    ├── module_roots.py     ← the discovery entry point
    ├── engine/             ← the six STT methods + the registry
    └── tests/
```

Before 0.12.0 the module sat two levels deeper, at
`jaeger_whisper_stt/nodes/whisper_stt/` — inherited from its old home
inside `jaeger_os/nodes/`, where a `nodes/` package holding many nodes
made sense. In a repo that ships exactly one module it held one entry,
inside a package already called `jaeger_whisper_stt`, inside a
distribution already called `jaeger-whisper-stt`. Both levels are gone;
`discover_modules()` already handled a root that *is* a module.

The remaining nesting — package inside repo — is Python packaging, not
Jaeger: `import jaeger_whisper_stt` resolves to a directory of exactly
that name, so the code cannot live at the repo root without the import
name becoming the clone's folder name and `.git`/`pyproject.toml`
landing inside the importable package.

## Quick start

Prove the module contract — manifest parses, `AudioSessionNode` builds
correctly-wired on an injected bus, the bus contract round-trips —
without touching microphone hardware or loading the real Whisper model
weights:

```bash
pytest jaeger_whisper_stt/tests
# or run it directly:
python -m jaeger_whisper_stt.tests.test_module_contract
```

Bind the `stt` slot into a running JaegerOS instance — `discover_modules()`
finds this module automatically once it's installed (it registers itself
under the `jaeger_os.module_roots` entry-point group; JaegerOS never
imports or names this package directly):

```python
from jaeger_os.core.modules import discover_modules
modules = discover_modules()
modules["stt"]  # -> this module, factory jaeger_whisper_stt:make_audio_session_node
```

Pick the method in `[config.stt].stt_mode`, or try one directly with
`jaeger-whisper-stt run two_pass`.

## Production checks

The live CLI uses the real `AudioIONode` + `AudioSession` +
`AudioSessionNode` path and prints typed transcript events. It does not have a
parallel microphone implementation.

```bash
# Download and load-validate both shipping models before deployment.
jaeger-whisper-stt models --prepare

# A read-only cache check suitable for an image-build gate.
jaeger-whisper-stt models --json

# Hardware/driver only — no model load. JSON report, nonzero on failure.
jaeger-whisper-stt doctor --seconds 10

# See device ids/names used by explicit input selection.
jaeger-whisper-stt devices

# Full live semantic path.
jaeger-whisper-stt run two_pass --seconds 60

# Explicit hardware selection when the system default is wrong.
jaeger-whisper-stt doctor --audio-backend portaudio --input-device 2

# Batch offline media, one model load, several output formats.
jaeger-whisper-stt transcribe one.wav two.mp3 --format txt --format srt
```

Run `models --prepare` while building the robot image, not on first production
boot. Normal pywhispercpp startup uses an existing cache without a freshness
request; missing weights otherwise trigger a download, which is inappropriate
for a robot expected to start without network access.

Operational health includes model worker liveness, microphone frame age,
invalid/rate-mismatched input, queue depth/drops, decode failures, transcript
counts, and the last error. Realtime queues are bounded and keep recent audio;
native input recovery happens outside the node tick so a wedged OS audio call
cannot stop health heartbeats.

The release gates and per-mode support matrix are maintained in
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

Complete JaegerOS demos live in `JaegerOS Demos/whisper stt`: offline files,
benchmarks, live/streaming captions, keywords, wake-command routing, bounded
always-listening room context, a desktop GUI, and timed production monitoring.
`JaegerOS Demos/voice echo` combines this module with Kokoro TTS.

## Architecture

JaegerWhisperSTT is an **engine module** — the third tier in the Jaeger
ecosystem's four-tier map, pinning JaegerOS and consumed by JaegerAI or
any other JaegerOS project that needs the `stt` slot filled:

```
JaegerOS      ← the framework this repo pins. Never forked, never edited.

JaegerAI      ← the Mind — one of two real consumers of this module.
                Installs it as an optional extra (.[whisper_stt]).

Modules       ← YOU ARE HERE. stt slot. Pins JaegerOS ONLY — never
                JaegerAI — so a robot body can listen standalone.

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
| [JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS) | Engine module (`tts` slot) | The speaking sibling — same discipline, own repo. |
| **JaegerWhisperSTT** | Engine module (`stt` slot) | This repo. |
| JP01 | Project (Body) | Consumes this module directly for its non-AI console. |

Two more repos round out the ecosystem without being part of the tier map
themselves: [JaegerTemplate](https://github.com/JenkinsRobotics/JaegerTemplate)
(the conventions every new ecosystem repo — this one included — started
from) and [JP01_Firmware](https://github.com/JenkinsRobotics/JP01_Firmware)
(the robot's Mac + Jetson body-side code JP01's console pairs with).

## Development

```bash
pytest -q   # unit, realtime ingress, module contract, and framework gates
```

The hermetic suite does not load model weights or touch a microphone. Use
`doctor`, a timed live run, and the production-monitor demo to qualify the
actual robot's microphone, audio interface, and room acoustics.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
