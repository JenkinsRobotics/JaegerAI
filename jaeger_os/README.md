# jaeger_os — self-improving local agent framework

Jaeger is a Pydantic-AI-based agent that can extend its own capabilities
by writing new skill files at runtime, with a hard safety boundary
between framework code (read-only) and agent state (writable).

## Phase-1 contract

**[`docs/unified_architecture.md`](../../docs/unified_architecture.md)
is the authoritative spec for what this package looks like at the end
of phase 1.** During phase 1, Jaeger-OS and Lilith are both being
aligned to share the same vocabulary, the same folder shape, and the
same patterns — but they remain two separate packages. Jaeger's source
hasn't been finalized yet; Lilith-flavored content does NOT migrate
into this package during phase 1.

If you're touching this package, read the unified arch doc first.
Jaeger's phase-1 changes are small (gains `embodiment/` layer and
`@requires_tier` on tools); most of the work in this phase lands in
the Lilith package.

## Directory tour

```
jaeger_os/
├── README.md            ← you are here
├── main.py              ← CLI entry point (`python main.py jaeger_os`)
│
├── core/                ← FRAMEWORK CODE — read-only at runtime
│   ├── instance.py        path resolution, lockfile, manifest gate
│   ├── schemas.py         Pydantic v2 schemas (identity, config, manifest)
│   ├── setup_wizard.py    first-run flow (interactive)
│   ├── credentials.py     get_credential + 0600 perm enforcement
│   ├── memory.py          per-instance facts / episodic / schedules I/O
│   ├── cron_runner.py     schedule firing + daily housekeeping
│   ├── log_rotation.py    daily rotation + retention enforcement
│   ├── migrations.py      discover + apply per-version migrations
│   ├── skill_loader.py    discover + register skills (core + instance)
│   ├── llm_model.py       in-process Gemma adapter for pydantic-ai
│   ├── prompts.py         system-prompt assembler
│   └── tools.py           built-in agent tools (file_write/read, get_time, …)
│
├── skills/              ← CORE SKILLS shipped with the framework (read-only)
│   └── hello_v1/          reference skill (SKILL.md + module + smoke test)
│
├── plugins/             ← OPT-IN EXTENSIONS (empty placeholder for M4+)
│
├── migrations/     ← per-version migration scripts (paired with core/migrations.py)
│
├── prompts/             ← system-prompt markdown content
│   └── agent_system_prompt.md    the v2 self-improvement contract
│
└── instance/            ← AGENT-WRITABLE state (created by the wizard)
    ├── .gitignore         keeps user state out of the repo
    ├── README.md          explains what lives under each instance
    └── <name>/            one dir per instance (default: `default/`)
        ├── identity.yaml      wizard-owned
        ├── config.yaml        wizard-owned
        ├── manifest.json      core_version pin
        ├── credentials/       0600 secrets (off-limits to agent)
        ├── skills/            agent's writable scratchpad
        ├── memory/            facts.json, episodic.jsonl, schedules.jsonl
        └── logs/              audit.log, latency.jsonl
```

## The safety boundary

There are TWO zones, and the framework enforces a hard line between them:

**Read-only to the agent** (everything in `jaeger_os/` except `instance/<name>/skills/`):
- All of `core/`, `skills/`, `plugins/`, `prompts/`, `migrations/`
- Everything in `instance/<name>/` EXCEPT the `skills/` subfolder
- `credentials/` is doubly protected — the sandboxed `file_read` tool
  refuses to read it; the agent must use `get_credential(name)` instead

**Writable by the agent** (its only writable zone):
- `instance/<name>/skills/` — where the agent authors new skill folders
  via the sandboxed `file_write` tool

The `file_write` tool resolves every path relative to `<instance>/skills/`,
rejects absolute paths and `..` escapes, and refuses any write that lands
outside the sandbox. See `core/tools.py` for the implementation.

## Skills: core vs instance

Two distinct kinds, both follow the same `<name>_v<N>/` versioned-folder
contract with `SKILL.md` + Python module + `tests/smoke_test.py`:

- **Core skills** (`jaeger_os/agent/skills/`) ship with the framework. Read-only.
- **Instance skills** (`<instance>/skills/`) are agent-authored. Writable.

On name collision, **instance wins over core** (override-via-versioning).
Within a zone, the highest `_v<N>` suffix wins. See `core/skill_loader.py`.

## Where the instance lives

The setup wizard creates the instance dir on first launch. Resolution
order (highest priority first):

1. `JAEGER_INSTANCE_DIR=/some/path` env var — explicit override (always wins)
2. `/var/lib/jaeger/<name>/` — when running as root (system service mode)
3. **`jaeger_os/instance/<name>/`** ← **default for dev / single-user**
4. `~/.jaeger/<name>/` — fallback when the bundled dir isn't writable
   (e.g. pip-installed in a system-wide site-packages tree)

The dev default lives inside the framework dir so you can SEE the agent's
state in your source tree. This is intentional and safe — the framework
dir is read-only to the agent (the v2 contract), so co-locating doesn't
weaken the safety boundary.

## Running

```bash
python main.py jaeger_os              # first run triggers the wizard, then chat loop
python main.py jaeger_os --self-test  # exercises sandbox + memory + skill loader (no LLM)
python main.py jaeger_os --setup      # re-run the wizard (backs up existing instance)
python main.py jaeger_os --migrate    # apply pending migrations and exit
python main.py jaeger_os --set-credential telegram_bot_token   # stdin / getpass
python main.py jaeger_os --list-credentials                    # names only

JAEGER_INSTANCE_DIR=/tmp/test_instance python main.py jaeger_os   # custom location
```

See `prompts/agent_system_prompt.md` for the v2 self-improvement contract
the agent operates under.
