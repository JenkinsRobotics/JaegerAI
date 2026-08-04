<h1 align="center">{{REPO_NAME}}</h1>

<p align="center">
  <em>{{DESCRIPTION}}</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/{{REPO_NAME}}/releases"><img src="https://img.shields.io/badge/version-0.1.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/JaegerOS-pinned-58A6FF?style=for-the-badge" alt="JaegerOS pinned">
</p>

---

> ## Replace-these checklist (delete this block once done)
>
> - [ ] `{{REPO_NAME}}` — every occurrence, this file + `docs/index.html` + `pyproject.toml.example`
> - [ ] `{{DESCRIPTION}}` — one-line description, this file + `docs/index.html`
> - [ ] `{{package_name}}` — the Python import name (snake_case) — rename the
>       `{{package_name}}/` directory itself, and every path inside it
> - [ ] Fill in `{{package_name}}/module.yaml` (drop the `.example`
>       suffix from every `*.example` file once real values are in)
> - [ ] Pin a real JaegerOS version range in `pyproject.toml.example`
>       (see [Ecosystem links](#ecosystem-links))
> - [ ] Seed `dev/docs/reality/STATUS.md` with today's date and truth
> - [ ] Enable GitHub Pages from `docs/` (see `docs/SITE.md`)
> - [ ] Pick a LICENSE (Apache-2.0 shipped by default — swap if this repo
>       needs different terms)
> - [ ] Building a project (a robot, a rig) instead of a module? Use
>       [`workspace/`](workspace/) instead of `{{package_name}}/` — see
>       [`workspace/README.md`](workspace/README.md) for its own checklist

---

## What it is

`{{REPO_NAME}}` is a **{{DESCRIPTION}}** built on
[JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) — the framework
layer of the Jaeger ecosystem (Bus · Node · modules/slots · supervisor ·
safety · contract · capability layer). This repo doesn't fork or edit
JaegerOS; it **pins** a release and builds on top of it, the same way a
ROS package builds on ROS.

This template scaffolds three different repo shapes. Pick the one that
matches what you're building — see [`CONVENTIONS.md`](CONVENTIONS.md)
for the full picture and when to reach for each:

- **Module repo** (the `{{package_name}}/` directory at this repo's
  root) — a self-contained capability (`module.yaml` + `config.py` +
  `node.py` + tests) that plugs into **any** JaegerOS project through a
  **slot** (see [`jaeger_os/nodes/kokoro_tts/`](https://github.com/JenkinsRobotics/JaegerOS/tree/master/jaeger_os/nodes/kokoro_tts)
  for the canonical shape this mirrors). Use this when you're building
  one swappable engine (a TTS backend, an STT backend, …) meant to be
  used by many different projects.
- **Workspace repo** (the [`workspace/`](workspace/) directory) — a
  project that owns a **Body's bringup**: `topology.yaml` (controllers,
  capabilities, e-stop scope), `manifest.toml` (the node graph that
  actually boots), `unit.yaml` (this physical/simulated unit's identity
  + live-verified gate), and `bringup/boot.py` (links → adapters →
  e-stop → capabilities → runtime). Mirrors JaegerOS's own reference
  hardware package, `jaeger_os/hardware/packages/jp01/`. Use this when
  you're standing up a robot, a rig, or any other physical/simulated
  body — see [`workspace/README.md`](workspace/README.md) to start.
- **Suite app** — a project that owns a **Mind-facing product**: its
  own faces (chat window, tray, voice), assembling JaegerOS + Jaeger AI
  + whichever modules it needs (the `jaeger.toml` / `jaeger.windowed.toml`
  manifest shapes in [Jaeger-AI](https://github.com/JenkinsRobotics/Jaeger-AI)
  are the reference). Use this when you're building an agentic product
  surface rather than a hardware bringup. **(planned)** — this template
  doesn't scaffold a suite-app skeleton yet; start from Jaeger-AI itself
  and pin forward rather than improvising one from this repo.

See [`CONVENTIONS.md`](CONVENTIONS.md) for the rules every repo in the
ecosystem follows, and the tier map in
[Ecosystem links](#ecosystem-links). For the formal version of that
tier map — five compositional roles (NODE, MODULE,
PACKAGE/WORKSPACE, APP, DISTRIBUTION), a ROS comparison, and
marketplace tagging — see [`TAXONOMY.md`](TAXONOMY.md). See
[`examples/`](examples/README.md) for six worked concept mappings
(a bare TTS module, a chatbot, JP01's own head, a lidar+SLAM demo, a
six-axis arm, and JP01 itself) that exercise the taxonomy against
real and archetypal apps, honest about what already exists versus
what still needs building.

## Install

```bash
git clone https://github.com/JenkinsRobotics/{{REPO_NAME}}.git
cd {{REPO_NAME}}
python3 -m venv .venv && source .venv/bin/activate
cp pyproject.toml.example pyproject.toml   # after filling in the pin — see checklist above
pip install -e .
```

This repo depends on a **pinned** `jaeger-os` release — it does not
vendor or fork the framework. See `pyproject.toml.example` for where the
version range is declared.

## Quick start

```bash
# Run this module's contract smoke test — proves module.yaml parses,
# the factory builds a live node, and the bus contract round-trips —
# all without touching real hardware or models.
pytest {{package_name}}/tests

# Or run it directly:
python -m {{package_name}}.tests.test_module_contract
```

Wire the module into a running JaegerOS instance by pointing its module
discovery at this package (see JaegerOS's `jaeger_os/core/modules.py` for
how `discover_modules()` walks module roots) — or, for a project-tier
repo, declare it in your instance's manifest.

## Module layout

The canonical shape every module/hardware-package repo in the ecosystem
follows, mirroring [`jaeger_os/nodes/kokoro_tts/`](https://github.com/JenkinsRobotics/JaegerOS/tree/master/jaeger_os/nodes/kokoro_tts)
in JaegerOS itself:

```
{{package_name}}/
├── __init__.py            ← exports the factory (module.yaml's `factory:` target)
├── module.yaml.example    ← the manifest: slot, topics, tools, requires_*
├── config.py.example      ← this module's settings-catalog schema slice
├── node.py.example        ← the four-phase Node (setup → tick → teardown → health)
├── docs/                  ← this module's own design notes
│   └── DESIGN.md.example
└── tests/
    └── test_module_contract.py.example   ← the module-contract smoke test
```

One copy of every truth: the manifest (`module.yaml`) is the single
source for what this module consumes, produces, and requires — nothing
else in the repo should restate it.

## Workspace layout

The project-tier shape — a repo that brings up a Body (or any project
that owns its own bringup), mirroring JaegerOS's own reference hardware
package (`jaeger_os/hardware/packages/jp01/`):

```
workspace/
├── README.md                  ← what a workspace repo is, and why these files
├── topology.yaml.example      ← controllers, capabilities, safety — the
│                                 Body's capability declaration
├── manifest.toml.example      ← [[node]] graph: engine modules bind by
│                                 slot=, the hardware package binds by factory
├── unit.yaml.example          ← this unit's identity + live-verified gate
├── requirements.txt.example   ← the pinned-stack pattern (JaegerOS +
│                                 modules @ tag)
├── bringup/
│   └── boot.py.example         ← links → adapters → e-stop → capabilities
│                                  → runtime
└── SAFETY_CHECKLIST.md        ← walk before any live (non-simulated) run
```

Start at [`workspace/README.md`](workspace/README.md) if this repo is a
workspace rather than a module — it has its own replace-these checklist.

## Development

```bash
pytest {{package_name}}/tests    # module-contract smoke test
ruff check                       # lint, if configured
```

Follow [`CONVENTIONS.md`](CONVENTIONS.md) — especially: no doc describes
behavior the code doesn't implement yet (mark it `(planned)` instead),
and `dev/docs/reality/STATUS.md` stays truthful — any commit that changes
behavior updates it in the same commit.

CI (`.github/workflows/ci.yml`) runs the test suite and, if this repo
sits below the Mind in the dependency graph, the nervous-system dependency
check (see `CONVENTIONS.md` → "The connection rule").

## Ecosystem links

- [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) — the framework
  this repo pins (Bus · Node · modules/slots · supervisor · safety ·
  contract · capability layer). You build on it; you don't edit it.
- [Jaeger-AI](https://github.com/JenkinsRobotics/Jaeger-AI) — the turnkey
  agentic product (the Mind): loop, tools, skills, memory, persona, local
  inference, and its own faces (chat app, TUI, voice).
- [JP01](https://github.com/JenkinsRobotics/JP01) — the reference
  hardware Jaeger (the Body); the first repo to consume out-of-tree
  modules and hardware packages the way this template scaffolds.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics

## Standalone use

Every module runs by itself — no agent, no app:

    python -m {{package_name}} --smoke

See `__main__.py` (from the `.example`). Inputs/outputs are declared in
`module.yaml` (`consumes`/`produces` topics, `tools`, `requires_*`) — the
slot contract IS the interface.
