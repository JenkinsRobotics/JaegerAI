# Jaeger AI repository structure

**Status:** current for `0.12.0`
**Scope:** the Jaeger AI application repository, after the JaegerAgent and
JaegerOS package split.

## Ownership rule

Jaeger AI is an application. JaegerOS supplies its runtime framework and
JaegerAgent supplies its reusable multimodal agentic mind. A file belongs here
only when it describes Jaeger AI's product composition, state integration,
interfaces, application-owned nodes, or defaults.

## Repository

```text
JaegerAI/
├── jaeger_ai/                  installable application package
├── dev/                        tests, benchmarks, engineering docs and tools
├── clients/                    external protocol clients
├── docs/                       operator/product documentation
├── scripts/                    install and release automation
├── jaeger                     checkout launcher and CLI shim
├── jaeger.toml                normal application composition
├── jaeger.multimodal.toml     dedicated multimodal composition
├── jaeger.windowed.toml       windowed composition
├── install.sh                 development install entrypoint
└── pyproject.toml             package metadata and entrypoints
```

Generated application state lives under `.jaeger_os/instances/` and is not
source. The built macOS application is also an artifact rather than a second
implementation.

## Application package

```text
jaeger_ai/
├── __init__.py
├── __main__.py                `python -m jaeger_ai`
├── main.py                    application composition and lifecycle
├── module_roots.py            JaegerOS discovery entrypoint
│
├── characters/                direct character/v1 library root
│   ├── character.py           loading, selection, editing and asset resolution
│   ├── schema.py              HEXACO/SPECIAL/expression/domain state
│   ├── compose.py             state-to-prose persona compiler
│   └── <character>/           manifest, card and optional avatar assets
│
├── core/                      Jaeger AI application logic
│   ├── bench/                 app-level benchmark runner and scenarios
│   ├── diagnostics/           doctor and macOS permission probes
│   ├── instance/              app instances, schemas, migrations and setup
│   ├── models/                model discovery and host clients
│   ├── runtime/               lifecycle, preflight, process and worker helpers
│   ├── safety/                app-side guards
│   └── settings/              settings catalog
│
├── interfaces/                things an operator or external client sees
│   ├── swift/                 native macOS application
│   ├── pyside6/               Python GUI and multimodal face
│   ├── tui/                   terminal UI
│   ├── avatar_player/         avatar surface
│   ├── bridge.py              NDJSON application bridge
│   └── client.py              protocol client
│
├── modules/                   integrations with imported providers
│   ├── jaeger_agent.py        mind slot
│   ├── jaeger_kokoro_tts.py   TTS slot
│   └── jaeger_whisper_stt.py  STT slot
│
├── nodes/                     runtime nodes owned by Jaeger AI
│   ├── animation/
│   ├── animation_dev/
│   └── media/
│
├── plugins/                   optional app extensions and messaging channels
├── skill_tree/                application progression/training state
├── timeline/                  application event/timeline support
├── assets/                    shared product assets
└── models/                    packaged metadata and local model links
```

## Why the root still has three Python modules

- `__main__.py` is Python's package entrypoint.
- `main.py` is Jaeger AI's application entrypoint.
- `module_roots.py` is named directly by the `jaeger_os.module_roots`
  packaging entrypoint and must remain importable without booting the app.

Everything else belongs in a subsystem. The optional Hermes subprocess helper,
for example, lives in `core/runtime/hermes_worker.py`, not at package root.

## Mochi-aligned application convention

Jaeger AI and Mochi now use the same ownership test:

| Directory | Contents |
|---|---|
| `characters/` | Portable character data; one direct child per pack. |
| `modules/` | How this app integrates a provider, named for that provider. |
| `nodes/` | Runtime nodes implemented and owned by this app. |
| `interfaces/` | Windows, terminal surfaces and external protocol seams. |
| `core/` | Shared logic that only makes sense for this application. |

Jaeger AI is installable, unlike Mochi's workspace-style application, so these
directories stay under the `jaeger_ai` package. Copying Mochi's generic folders
to repository root would break packaging without improving ownership.

## Test mirror

`dev/tests/jaeger_ai/` follows the application package where that improves
navigation. Character format, loader and compiler tests therefore live under
`dev/tests/jaeger_ai/characters/`. Cross-cutting behavior remains grouped by
the surface or runtime boundary it verifies.

The pre-split 0.5 structure guide is preserved at
`dev/docs/history/STRUCTURE_0.5.0.md`; it is history, not a description of the
current application.
