# Jaeger Commands

The one reference for the `jaeger` command surface. `install.sh` puts
`jaeger` on PATH for product installs; in the dev repo use `./jaeger`.
(0.9.6 removed the legacy `jaeger instance` spelling — an agent IS an
instance, one word now.)

## Run / chat

| Command | What it does |
|---|---|
| `jaeger` | Run the active agent — the windowed app when built, else the terminal |
| `jaeger --instance NAME` | Run a specific agent |
| `jaeger --voice` | Run in voice mode |
| `jaeger "one-shot prompt"` | Single prompt, print the reply, exit |
| `jaeger --stream` | Streaming mode (OBS/YouTube renderer WebSocket) |

## Agents (create / manage)

| Command | What it does |
|---|---|
| `jaeger setup [name]` | Create an agent — opens the app's setup window (GUI-first) |
| `jaeger setup tui [name]` | Same, but force the terminal wizard |
| `jaeger agent create [--name N] [--tui] [--force]` | What `setup` routes to; `--force` rebuilds an existing agent |
| `jaeger agent list` | Every agent, active one starred |
| `jaeger agent use <name>` | Set the sticky default agent |
| `jaeger agent inspect <name>` | Identity + config + manifest, no model boot |
| `jaeger agent delete <name> [-f]` | Remove an agent |
| `jaeger agent clear <name> [-f]` | Wipe memory + logs, keep identity/config |
| `jaeger migrate [--agent N]` | Apply pending per-agent migrations |

## Operator console

| Command | What it does |
|---|---|
| `jaeger instances …` | Console extras: `show`, `edit`, `set-default`/`switch` (overlaps `agent` — being folded in) |
| `jaeger skills …` | List / manage the agent's skills |
| `jaeger personality …` | Persona / character settings |
| `jaeger status` | Instance + runtime status |
| `jaeger roadmap` | Show the roadmap |
| `jaeger avatar …` | Avatar controls |
| `jaeger prompt …` | Prompt inspection |
| `jaeger config …` | Config get/set |
| `jaeger memory …` | Agent memory tools |
| `jaeger settings …` | Runtime settings |
| `jaeger skill …` | Single-skill operations |

## Install / maintain

| Command | What it does |
|---|---|
| `jaeger --version` | Installed release number |
| `jaeger update` | Update to the latest release tag (dev checkout: git pull + rebuild) |
| `jaeger doctor` | Environment, permissions (TCC), skills, readiness check |
| `jaeger backup` / `jaeger restore` | Instance backup / restore |
| `jaeger reinstall` | Re-fetch the current release |
| `jaeger uninstall` | Remove the install |
| `jaeger autostart …` | Login-item autostart on/off |
| `jaeger kill` | Stop a stuck agent process |
| `jaeger stop` | Stop the running daemon |

## Developer (repo checkout)

| Command | What it does |
|---|---|
| `jaeger dev` | Build (if stale) + launch the app in the dev state (`jros-dev` instance) |
| `jaeger dev --tui` | Terminal dev agent |
| `jaeger dev --health` / `--status` / `--stop` | Dev toolbox verbs |
| `jaeger bench …` | Benchmarks (`run` / `timing` / `compare` / `history`) |
| `jaeger bridge` | Run the app bridge protocol on stdio |
| `jaeger mcp` | Run the MCP server |
| `jaeger launcher …` | Launcher plumbing |

There is ONE app bundle: `JaegerOS.app`. Dev is a launch state
(`jaeger dev`), not a separate app — one TCC permission grant covers
everything.
