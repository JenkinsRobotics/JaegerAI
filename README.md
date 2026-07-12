<h1 align="center">JaegerAI</h1>

<p align="center">
  <em>The universal turnkey agentic agent — local inference, tools, skills, memory, the id/ego persona pipeline, chat/voice/TUI faces, and the client protocol. The Mind. Runs on JaegerOS; headless is a config, not a fork.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerAI/releases"><img src="https://img.shields.io/badge/version-0.9.0--dev-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

## What it is

JaegerAI is the **Mind** tier of the Jaeger ecosystem — the turnkey
agentic product, not a headless library. It ships the complete universal
agentic agent (Hermes lineage): the loop, tools, skills, memory, the
id/ego persona pipeline, local inference, **and its own faces** — chat
app, TUI, voice, and the protocol it serves. Headless (running on a
robot with no display) is a **config** of JaegerAI, not a fork of it.

It pins [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) (the
framework tier — bus, nodes, modules/slots, supervisor, safety, wire
contract, capability layer) and builds everything agentic on top:

- **`agent/`** — the loop, tool registry, availability gates, and the
  **`persona_first`** pipeline (default since 0.8.0): an id/ego split
  where a persona lane speaks to the user directly, in character, and
  has exactly one tool — `perform_task(request)` — which runs the full
  clean inner agentic loop (persona-off, all tools, hardened prompt).
  The safety property in one line: *the id never touches reality
  directly.*
- **`personality/`** — characters (14 shipped) own identity + soul +
  traits + lore as **State** (HEXACO/SPECIAL/Expression sliders),
  compiled on change — never per turn — into a **View** the model
  actually sees. An instance just *plays* a character; the character
  isn't the instance.
- **Memory** — subject-attributed SQLite (`subject/key/value/category/
  source/tags/note`), current-view semantics, provenance-tracked.
- **Skills** — self-contained (`SKILL.md` + optional tools + recipe);
  the agent researches, writes, smoke-tests, benchmarks, and versions
  its own skills.
- **Its own faces** — the Swift app (default windowed UI), the TUI
  (`jaeger_os/interfaces/tui/`, the 0.1.0-lineage terminal surface,
  preserved alongside newer surfaces per standing convention), voice
  (via the `kokoro_tts`/`whisper_stt` engine-module extras), and the
  frozen PySide6 shipping set. All faces are clients of one protocol.
- **The client protocol** — `jaeger_ai/contract` (vendored from
  JaegerOS) + `jaeger_ai/interfaces/client.py` (`JrosClient`), a
  versioned NDJSON wire contract any surface — including third-party
  ones — speaks over `jaeger bridge`.
- **`cli/`** — the `jaeger` command (every real verb: `status`, `config`,
  `runtime`, `agent create/list/use/inspect/delete`, `update`, …).
  JaegerOS ships no CLI at all — this repo is where it lives.

Engine modules ([JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS),
[JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT))
are **optional extras** — each its own repo, pinning JaegerOS only, so a
robot body can run without the AI product installed at all.

## Install

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI
./install.sh                       # venv + editable install of jaeger-os + jaeger-ai
```

`JaegerAI` depends on `jaeger-os` (a path/pin dependency — see
`requirements.txt`'s header for the exact staging-vs-release pin story)
and installs **editable** (PEP 660), same model as JaegerOS: the code
stays writable in place because the agent self-modifies its own skills.
Voice is optional — pull in the engine extras when you want speech:

```bash
pip install -e '.[kokoro_tts]'     # speak (JaegerKokoroTTS)
pip install -e '.[whisper_stt]'    # listen (JaegerWhisperSTT)
```

## Quick start

```bash
./jaeger agent create              # opens the setup wizard (character, model, permissions)
                                    # --tui for the terminal wizard
./jaeger                           # launch the default agent
```

Manage multiple agents — a character is the persona; an agent is a
deployed AI that plays one, with its own memory + config:

```bash
./jaeger agent list                # list agents / mark the default
./jaeger agent --help              # create | list | use | inspect | delete | clear
./jaeger --agent <name>            # launch a named agent
./jaeger --agent <name> --no-voice # text-only (no mic, no TTS warm)
```

`jaeger` is the one operator command — installed on `PATH` after
`install.sh`, or run as `./jaeger` from the clone.

## Architecture

JaegerAI is the **Mind** tier — the second layer in the Jaeger ecosystem's
four-tier map, pinning JaegerOS and pinned in turn by nothing:

```
JaegerOS      ← the framework this repo pins. Never forked, never edited.

JaegerAI      ← YOU ARE HERE. The Mind — loop, tools, skills, memory,
                persona, local inference, and its own faces. Ships the
                jaeger CLI (JaegerOS ships none).

Modules       ← engine modules this repo can optionally install:
                JaegerKokoroTTS (tts), JaegerWhisperSTT (stt).

Projects      ← the assembled things that install JaegerAI: JP01 (the
                robot, headless config), a desktop companion.
```

The connection rule (from
[`JAEGER_ECOSYSTEM.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/JAEGER_ECOSYSTEM.md)):
**bodies provide capabilities · the Mind consumes them · the runtime is
where they meet · the protocol is how outside apps reach in.** See
[`THREE_TIER_STRUCTURE.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/THREE_TIER_STRUCTURE.md)
for the full tier-map reasoning this repo is built against.

## Ecosystem

| Repo | Tier | What |
|---|---|---|
| [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) | Framework | Bus, node, modules/slots, supervisor, safety, contract, capability layer. This repo pins it. |
| **JaegerAI** | Mind (product) | This repo — the turnkey agentic product and its faces. |
| [JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS) | Engine module (`tts` slot) | Streaming Kokoro speech synthesis. Optional extra of this repo. |
| [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT) | Engine module (`stt` slot) | Two-pass Whisper transcription with VAD + wake word. Optional extra of this repo. |
| JP01 | Project (Body) | The reference hardware Jaeger — installs this repo headless. |

## Development

```bash
pytest dev/tests -m smoke          # ~30s sanity check
pytest dev/tests                   # full suite (204 test files)
./dev/benchmark/bench.py           # routing corpus — the ≥79/81 gate for any agentic-pipeline change
./dev/benchmark/scenarios.py       # 51-case hermetic full-system scenario suite
./dev/benchmark/scenarios.py --lane security   # the 15 security gates only
```

Test markers (`slow`, `integration`, `model`, `ui`, `subprocess`,
`smoke`, `regression`) let CI and local iteration pick the right subset
— see `pyproject.toml`. Follow the ecosystem's conventions: no doc
describes behavior the code doesn't implement yet (mark it `(planned)`
instead), and any commit that changes behavior keeps its docs truthful
in the same commit.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
