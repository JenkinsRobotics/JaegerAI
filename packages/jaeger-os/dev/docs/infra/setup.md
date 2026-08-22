# JROS Setup, Upgrade, and Uninstall

> Canonical reference for installing JROS on a fresh machine, upgrading
> an existing install, and tearing it back down. As of `0.2.3`, JROS
> follows the **git-clone install model** used by Hermes-Agent,
> ComfyUI, A1111, and other end-user AI apps — not the pip-package
> model. This doc explains why and how.

---

## 0.2.3 — what changed

| | 0.2.2 and earlier | 0.2.3+ |
|---|---|---|
| **Install** | `pipx install jaeger-os` | `curl … \| bash` (clones to `~/jaeger`) |
| **Upgrade** | `pipx upgrade jaeger-os` | `git pull && ./install.sh` |
| **Entry point** | `jaeger` CLI (on `$PATH`) | `./run.sh` (from the clone) |
| **Package** | Installed to `site-packages/` | Lives in `~/jaeger/src/jaeger_os/` |
| **Per-agent content** | Mixed with site-packages | Plain `~/jaeger/src/jaeger_os/agents/<name>/` |

**Why the move:** JROS is an app, not a library. Operators were getting
confused about where their data lived (site-packages? `~/.jaeger`? the
working dir?). Putting weights, agents, and customisation inside a
`site-packages/` tree was hostile to the "just clone it and look around"
discovery story. The git-clone model is what Hermes-Agent, ComfyUI, and
the like all do — and it's how operators of those tools already think
about local AI apps.

The `from jaeger_os.main import …` import surface was **preserved**
— tests, benchmarks, and any out-of-tree integrations that reference
`jaeger_os.main` keep working unchanged. `run.py` is a thin entry-point
wrapper that delegates to `main:main()`. New code can use either; the
shipped contract is that 0.2.x keeps both surfaces alive.

---

## Install (fresh machine)

### Prereqs

| | macOS | Debian / Ubuntu |
|---|---|---|
| **Python 3.11 or 3.12** | `brew install python@3.12` | `apt install python3.12 python3.12-venv` |
| **Git** | `xcode-select --install` | `apt install git` |
| **C/C++ toolchain** | `xcode-select --install` | `apt install build-essential` |
| **PortAudio** | `brew install portaudio` | `apt install portaudio19-dev` |

Why these system deps: `llama-cpp-python` and `pywhispercpp` build native
code, and `sounddevice` wraps PortAudio. `pip` can't install system
libraries, so the script will refuse cleanly if these are missing.

### The one-line install

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
```

What this does, in order:

1. Verifies `git` and `python3` (3.11 or 3.12) are on `$PATH`.
2. Clones `https://github.com/JenkinsRobotics/JROS.git` to
   `$JAEGER_HOME` (default `~/jaeger`).
3. Runs the in-repo `./install.sh`:
   - creates `.venv/` in the clone,
   - installs `requirements.txt` (the whole runtime — local LLM, voice,
     vision, external models, messaging),
   - scaffolds `src/jaeger_os/agents/`,
   - ensures `~/.jaeger/instances/` exists.
4. Prints next-step instructions.

End state — three layers, each in a known location:

```
~/jaeger/                      ← SYSTEM   (the clone)
├── install.sh, run.sh, scripts/install.sh
├── requirements.txt, pyproject.toml
└── src/jaeger_os/
    ├── run.py                 ← entry point
    ├── core/, plugins/, skills/, prompts/, models/
    └── agents/                ← USER     (your personas, gitignored)
        ├── lilith/
        └── eren/

~/.jaeger/                     ← RUNTIME  (memory, daemon, logs)
└── instances/
    ├── lilith/
    └── eren/
```

### Pinning a release

```bash
JAEGER_REF=0.2.3 curl -fsSL \
  https://raw.githubusercontent.com/JenkinsRobotics/JROS/0.2.3/scripts/install.sh | bash
```

Use this for reproducible installs (CI, multiple machines that need to
agree). The default `master` ref always tracks latest.

### Custom install location

```bash
JAEGER_HOME=/opt/jaeger curl … | bash
```

Useful for system-wide installs, machines where `~` is on a small
volume, or running multiple JROS clones side-by-side.

### Manual install (no curl)

Identical end state; useful if you want to inspect every step:

```bash
git clone https://github.com/JenkinsRobotics/JROS.git ~/jaeger
cd ~/jaeger
./install.sh
./run.sh setup
```

---

## First run

After the install completes:

```bash
cd ~/jaeger
./run.sh setup           # create your first agent (default name auto-picked)
# or, with an explicit name:
./run.sh setup lilith
```

`./run.sh setup [NAME]` is the explicit "create or re-configure an
agent" subcommand — it always runs the wizard, even against an
existing instance. There is also an implicit path: launching with
`./run.sh --instance NAME` against a name that doesn't exist yet
auto-fires the wizard. Either reaches the same place; use whichever
fits your muscle memory.

To **see what's installed** or **remove an agent**:

```bash
./run.sh list             # list all agents on this machine
./run.sh delete NAME      # remove an agent (asks you to type the name)
./run.sh help             # full subcommand cheatsheet
```

The wizard walks through:

1. **Agent identity** — name, instance dir.
2. **Memory tier** — detects unified RAM, recommends an awake+asleep
   model pair (12 / 24 / 32 / 64+ GB ladder). See
   [`deep_think_design.md`](../core/deep_think_design.md).
3. **Model download** — fetches the chosen GGUF from Hugging Face into
   `src/jaeger_os/models/`. One-time, then offline forever after.
4. **Voice** — wakeword, TTS voice, mic selection (optional).

Then:

```bash
./run.sh               # interactive TUI
# or
./run.sh start         # daemonised background agent
./run.sh status        # daemon status
./run.sh rich-tui      # connect to running daemon
```

All flags forward to `src/jaeger_os/run.py`.

---

## Upgrade

```bash
cd ~/jaeger
git pull
./install.sh           # idempotent — only re-installs changed deps
```

Or re-run the curl one-liner — it detects an existing clone and runs
the same steps internally.

**The upgrade contract:**

- The `~/jaeger/` clone changes (System layer is what we ship).
- `~/.jaeger/instances/<name>/` is migrated forward (Runtime layer —
  the wizard / migration runs when format changes).
- `~/jaeger/src/jaeger_os/agents/<name>/` is **never touched** (User
  layer is yours; `.gitignore`d upstream).

If a release ever required a manual migration step it would be called
out in `CHANGELOG.md` and the install script would refuse to run until
you'd done it.

---

## Pinning a specific version after install

```bash
cd ~/jaeger
git fetch --tags
git checkout 0.2.3
./install.sh
```

Then `git checkout master` to rejoin latest later.

---

## Uninstall

```bash
# System layer — the clone
rm -rf ~/jaeger

# Runtime layer — memory, daemon, logs (PERMANENT — back up first if
# you care about the agent's history)
rm -rf ~/.jaeger

# That's it. No `site-packages` to clean, no console scripts to chase
# down. JROS leaves no other state on the host.
```

A `~/jaeger/.venv/` directory holds the Python deps — it goes away with
the clone.

---

## Multi-instance on one host

JROS supports multiple agents on the same machine (think macOS users —
the system is shared, each user gets their own home). Two patterns:

### Same clone, multiple agents

```
~/jaeger/                              ← shared System layer
└── src/jaeger_os/agents/
    ├── lilith/
    ├── eren/
    └── tars/

~/.jaeger/instances/
    ├── lilith/                        ← per-agent Runtime state
    ├── eren/
    └── tars/
```

Switch via `./run.sh --instance eren` or set
`JAEGER_INSTANCE=eren ./run.sh`.

### Multiple clones (for testing different JROS versions)

```bash
JAEGER_HOME=~/jaeger-stable JAEGER_REF=0.2.3 curl … | bash
JAEGER_HOME=~/jaeger-edge   JAEGER_REF=master curl … | bash
```

Each clone has its own `.venv/`. Runtime state at `~/.jaeger/` is still
shared — set `JAEGER_INSTANCE` per clone to keep them apart.

---

## Developer install

If you're hacking on JROS itself:

```bash
git clone https://github.com/JenkinsRobotics/JROS.git
cd JROS
./install.sh
# install dev tooling on top
.venv/bin/pip install pytest pytest-asyncio pytest-xdist mypy ruff
./scripts/run_tests.sh        # the fast tier
```

`pyproject.toml` carries pytest + ruff configuration. There is no
packaging config — JROS is not built as a wheel. Tests import
`jaeger_os` through `src/` via `PYTHONPATH` (set automatically by
`run.sh` and `conftest.py`).

---

## Troubleshooting

**`python3.12: command not found`** — install Python 3.12 first
(see Prereqs above). JROS also accepts 3.11.

**`fatal: not a git repository`** during upgrade — your `~/jaeger` was
created by something other than the installer. Move it aside and
re-run the curl one-liner.

**Audio / mic not working** — check PortAudio installed
(`brew list portaudio` or `dpkg -l | grep portaudio19`). After
install, run `.venv/bin/python -m sounddevice` to enumerate devices.

**Browser tool fails to launch** — Playwright needs its browser binary:
`.venv/bin/playwright install chromium`. (This isn't run automatically
because it's a 200MB download.)

**`from jaeger_os.main import …` fails** — should not happen on 0.2.3
(`main.py` is unchanged from 0.2.2). If it does, you may have a stale
`__pycache__/` — `find ~/jaeger -name __pycache__ -exec rm -rf {} +`
and re-run.

**Memory tier wizard recommends a model too big for my Mac** — set
`JAEGER_WIZARD_TIER` to the tier above or below your detected size.
Tiers: `12gb`, `24gb`, `32gb`, `64gb+`.

---

## See also

- [`system_runtime_user.md`](../reality/system_runtime_user.md)
  — the three-layer model in depth.
- [`deep_think_design.md`](../core/deep_think_design.md) — sleep-cycle and
  memory-tier ladder rationale.
- [`external_models.md`](../core/external_models.md) — point JROS at LM Studio,
  OpenAI, or Anthropic instead of (or alongside) the local LLM.
