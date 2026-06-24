# Instance layout

Where per-agent state lives on disk, and how the framework finds it.

This is the **user-state** half of JROS. The framework half is
under `site-packages/jaeger_os/` (a normal pip/pipx install). The
two are deliberately separate so that updating the framework
(`jaeger update`) doesn't touch user data, and so backups + multi-
instance work cleanly.

## The two universes

```
# Framework code — installed by pipx, shared across all instances
site-packages/jaeger_os/
├── core/  agent/  daemon/  plugins/  interfaces/  skills/
└── (no instance/ subdir — that's deliberately gone in 0.2.0)

# User state — written at runtime, per-instance
~/.jaeger/
├── instances/
│   ├── default/              ← one agent's complete workspace
│   ├── work/                 ← another agent, fully isolated
│   └── personal/             ← and another
├── backups/                  ← `jaeger backup` writes here
├── active_instance           ← sticky default (one-line file)
└── jaeger.env                ← sourceable shell exports (WIZ-4)
```

The OS analogy: framework code is `/usr/lib/` (shared, library-
installed); per-instance state is `/home/<user>/` (per-user,
private). Upgrading the library doesn't touch homedirs.

## What's inside an instance

```
~/.jaeger/instances/default/
├── identity.yaml             ← name, role, personality, voice
├── soul.md                   ← free-form character / values doc
├── config.yaml               ← model, ctx, permissions, voice, interaction, workspace
├── manifest.json             ← core_version pin + timestamps
├── distribution.yaml         ← install source + framework version
├── permissions.json          ← "always allow" grants the user accepted
├── .lock                     ← exclusive lockfile (active while running)
├── memory/                   ← what the agent knows
│   ├── facts.json
│   ├── episodic.jsonl
│   ├── episodic.embeddings.npz
│   └── schedules.jsonl
├── skills/                   ← code MODULES (SKILL.md + .py)
│   └── <name>_v<N>/
├── workspace/                ← agent scratch + outputs (INST-11)
│   ├── reports/              ←   generated reports
│   ├── downloads/            ←   files the agent fetched
│   └── *.{txt,md,csv,…}      ←   ad-hoc notes / data
├── credentials/              ← 0700 — API keys, tokens (off-limits to agent)
├── logs/                     ← audit.log, latency.jsonl, tool_results/
├── run/                      ← PIDs, daemon socket, log (runtime only)
├── home/                     ← per-instance HOME for subprocesses (INST-4)
│   ├── .gitconfig            ←   (optional) per-instance git identity
│   └── .ssh/                 ←   (optional) per-instance ssh keys
└── .git/                     ← skill version history (agent commits)
```

The agent can write to **two** places under its instance:

- **`skills/`** — code MODULES (a folder per skill with `SKILL.md`
  + `.py`). Use when authoring runnable code the skill loader will
  pick up.
- **`workspace/`** — general scratch + outputs (reports, generated
  data, downloads, ad-hoc notes). Use for any non-code file the
  user asked for.

The model picks by lead path component: `file_write("workspace/report.md", ...)`
lands in workspace; `file_write("my_skill_v1/SKILL.md", ...)` lands
in skills. Everything else under `<instance>/` is read-only to the
agent.

**Custom workspace location.** The default `<instance>/workspace/`
keeps everything self-contained for backup / restore. If you want
the agent's outputs somewhere convenient for Finder / Spotlight,
set `config.yaml`:

```yaml
workspace:
  location: ~/Documents/Jaeger Outputs
```

The agent writes `workspace/report.md` → ends up at
`~/Documents/Jaeger Outputs/report.md`. An external workspace is
NOT included in `jaeger backup` (it lives outside the instance
dir); back it up alongside your other documents.

## Resolver order

`resolve_instance_dir()` in `core/instance/instance.py` picks the
on-disk path. Priority, top to bottom:

1. **`--instance NAME`** CLI flag (always wins).
2. **`JAEGER_INSTANCE_DIR`** env var (explicit path — use for
   dev work that targets `sandbox/jros-dev/` via `dev/scripts/dev_env.sh`,
   or for tests that want a throwaway location).
3. **`JAEGER_INSTANCE_NAME`** env var → `~/.jaeger/instances/<name>/`.
4. **`~/.jaeger/active_instance` file** → `~/.jaeger/instances/<name>/`
   (sticky default written by `jaeger instance use <name>`).
5. **`~/.jaeger/instances/default/`** (the literal default).
6. **Wizard fires** if none of the above resolves to an existing
   instance (or `--setup` was explicitly passed).

The `/var/lib/jaeger/` system-service path and the editable-install
detection still work — the resolver checks `os.geteuid()` and looks
for `site-packages` ancestors on `PACKAGE_ROOT` to decide.

## Multi-instance

Run two daemons side by side:

```sh
jaeger -i work start          # boots work
jaeger -i personal start      # boots personal — different model, different keys
```

Each daemon has its own socket at `<instance>/run/jaeger.sock`,
its own model loaded in RAM, its own audit log. Memory is
**fully isolated** — work can't read personal's facts.

Switch the sticky default:

```sh
jaeger instance use work      # writes ~/.jaeger/active_instance
jaeger start                  # now boots "work" by default
```

## Backup & restore

```sh
jaeger backup --name work     # writes ~/.jaeger/backups/work-<ts>.zip
jaeger restore <archive>      # unpacks; refuses on name collision
                              # unless --force (backs up existing first)
```

Default backup excludes:
- `credentials/*` (use `--include-credentials` to opt in)
- `run/*` (runtime PID + socket)
- `memory/*.embeddings.npz` (regenerable from episodic.jsonl)
- Rotated audit logs

User-authored skills + memory + identity ARE included by default
(they're core to the agent's identity).

## Dev workflow

In-repo work uses `sandbox/jros-dev/` so writes don't land in the
user's real `~/.jaeger/`:

```sh
source dev/scripts/dev_env.sh     # exports JAEGER_INSTANCE_DIR=$REPO/sandbox/jros-dev
jaeger start
```

The sandbox path is explicit; it bypasses the
`~/.jaeger/instances/` nesting (the env var wins over the user-
home resolver branch).

## Migration

`manifest.json:core_version` is the schema version of the instance.
When the framework's `CORE_VERSION` is newer than the instance's,
boot prompts to run pending migrations:

```sh
jaeger migrate                # explicit
jaeger update                 # update framework, then auto-prompt-migrate
```

Migration scripts live in `src/jaeger_os/migrations/v<from>_to_v<to>.py`.
Each runs idempotently against a layout; the runner walks every
matching version step in order.

## Cleaning up

```sh
jaeger instance delete <name>      # removes the whole dir (asks first)
jaeger instance clear <name>       # wipes memory + logs, keeps identity
```

Or manually: `rm -rf ~/.jaeger/instances/<name>/`. The wizard
recreates from scratch on next launch.
