# Instance lifecycle — Hermes Agent vs JROS

**Status:** draft · **Authored:** 2026-05-25 · **Decision:** open

A side-by-side of how Hermes Agent handles per-user state and its
operational verbs (install / update / backup / multi-instance) vs.
what JROS does today. Captured during 0.2.0 design review; left as
a doc so we can sit with it before committing scope.

The 0.2.0 roadmap already shipped the *location* questions
(HYGIENE-1 to -5 — bundled vs `~/.jaeger/` vs sandbox) and the
*first-run* polish (WIZ-1 to -5). It did **not** discuss the
*operational* verbs around an installed instance. This doc fills
that gap so the next planning step starts from a shared picture.

---

## TL;DR

> **2026-05-25 update:** the proposed 0.2.0 layout nests instances
> under `~/.jaeger/instances/<name>/` (was flat at
> `~/.jaeger/<name>/`). See "Final 0.2.0 layout" section at the
> bottom of this doc. The table below describes the original 0.1.0
> shape so the comparison with Hermes is apples-to-apples.

| Layer | JROS 0.1.0 | Hermes today |
|---|---|---|
| Where state lives | `~/.jaeger/<name>/` (per-instance) | `~/.hermes/profiles/<name>/` (per-profile, default at `~/.hermes/`) |
| First-class multi-tenancy | Yes (`--instance` + env var) | Yes (`hermes -p` + `hermes profile use`) |
| Sticky default selection | `JAEGER_INSTANCE_NAME` env var + `~/.jaeger/jaeger.env` (sourceable) | `~/.hermes/active_profile` file (no env needed) |
| Install path | `pip install jaeger-os` | `curl \| sh` installer (handles uv, Python, ffmpeg, git, Node) |
| First-run | Wizard auto-fires when no instance exists | `hermes setup` wizard |
| State store | YAML/JSON + JSONL + per-instance `.git/` | SQLite `state.db` with FTS5 + auto-migrating schema |
| Update verb | Manual `pip install -U jaeger-os` + optional `--migrate` | `hermes update` (git pull + reinstall + re-seed bundled skills + optional pre-update zip) |
| Backup verb | None (only wizard's `<dir>.bak.<ts>` aside-rename) | `hermes backup` + `hermes profile export <name>` |
| Restore verb | None (manual filesystem) | `hermes import` + `hermes profile import` |
| Schema-mismatch behaviour | Refuse-to-start + offer `--migrate` | Auto-migrate on next state.db open |
| Subprocess HOME isolation | No | Yes — `~/.hermes/profiles/<name>/home/` |
| Docker image | None | Multi-stage Dockerfile |
| Distribution manifest | `manifest.json` (core_version + timestamps) | Optional `distribution.yaml` (install source) |

The pattern is clear: **JROS got the location right; Hermes got the
operations right.** The two designs aren't in conflict — JROS's
posture (refuse-to-start, explicit migrations, per-instance .git)
is *more conservative* than Hermes's (silent auto-migrate, single
home root), which is the right trade-off for a robot-bound platform
where surprising state mutations matter. The gap is that the
operational verbs that wrap our conservative core are missing.

---

## Where JROS is already strong

Don't change these. They're our design moat:

1. **Refuse-to-start on `core_version` mismatch.** Hermes silently
   auto-migrates SQLite. For a robot whose memory will eventually
   drive physical motion, a forced human-in-the-loop on schema
   changes is the right call.
2. **Per-instance `.git/` for skill history.** Hermes versions
   skills in the framework repo; we version them per instance.
   The agent's authoring history travels with the agent.
3. **Explicit `.lock` file with PID.** Stale-lock detection is
   tight; "is this instance already running" is unambiguous.
4. **Resolver priority is well-thought-out** (env > `/var/lib/`
   > `~/.jaeger/` > bundled dev). Hermes's `HERMES_HOME` is a
   single hop; ours distinguishes system-service, user-pip,
   and dev-checkout modes.
5. **Manifest pinning + migrations module.** The plumbing for
   schema evolution exists (`core/instance/migrations.py`); it
   just hasn't been exercised yet (CORE_VERSION pinned at 1.0.0).

---

## Where Hermes is clearly ahead

Each of these is a real platform feature we're missing:

### Tier 1 — small, high-leverage

1. **`hermes profile use <name>` sticky default.** Writes
   `~/.hermes/active_profile`; CLI reads it without env-var
   memorisation. JROS has WIZ-4 (`~/.jaeger/jaeger.env`) which
   is half a step in that direction but still requires the user
   to `source` it.
   - **JROS equivalent:** `jaeger instance use <name>` →
     writes `~/.jaeger/active_instance`; resolver reads it
     after `JAEGER_INSTANCE_DIR` and before
     `JAEGER_INSTANCE_NAME` (or below — designer's call).
2. **`hermes profile inspect`** — read identity + config without
   booting the model. Useful for "which instance is this again?"
   and for tooling.
   - **JROS equivalent:** `jaeger instance inspect <name>` →
     dump identity.yaml + config.yaml + manifest.json. Probably
     ~30 lines; reuses existing schema loaders.
3. **`hermes backup`** — zip the instance dir, excluding regen-
   erable caches + secrets. Default output path in user dir.
   - **JROS equivalent:** `jaeger backup <name> [--output PATH]`
     → zip `~/.jaeger/<name>/` excluding:
     - `credentials/*` (secrets — backup separately with a
       deliberate `--include-credentials` flag)
     - `run/*` (PID + socket — runtime)
     - `memory/*.embeddings.npz` (large + regenerable from
       episodic.jsonl)
     - `logs/audit.log.*` (rotated logs)
     - `.git/objects/pack/*` (compressed already, but pull
       in the loose index)
     Default output: `~/.jaeger/backups/<name>-<ts>.zip`.
4. **`hermes import` / `hermes profile import`** — restore from a
   backup file.
   - **JROS equivalent:** `jaeger restore <archive> [--name NEW]`
     → unzip into `~/.jaeger/<name>/`; refuse if name already
     exists unless `--force` (and back the existing one up with
     the wizard's `<dir>.bak.<ts>` rename first).
5. **`hermes update`** — `git pull && pip install -e .`. Even if
   we don't replicate the git path, a documented `jaeger update`
   verb that runs `pip install -U jaeger-os && jaeger --migrate`
   is friendlier than telling users to remember the two-step
   sequence.

### Tier 2 — bigger, can wait

6. **Per-instance HOME jail for subprocesses.** Hermes gives each
   profile its own `~/.gitconfig`, `~/.ssh/`, etc. This is the
   right answer for Docker multi-tenancy and for users who run
   one Jaeger per project. Significant scope — touches every
   `subprocess.run` call site that should respect it.
7. **One-shot installer (`curl | sh`).** Useful for non-Python
   users. Means we'd own a brittle shell script across mac /
   linux / windows. Probably wait for 0.3.0+.
8. **Docker image.** Hermes ships one. **Out of scope for JROS** —
   Docker on Mac (Docker Desktop) is heavy + slow + a poor UX
   match for a personal-agent / robot-bound platform. Local
   robots run the agent natively; macOS users want native too.
   Revisit if/when we have a server-deployment story; not before.
9. **`distribution.yaml`** — optional install-source manifest.
   Cosmetic; mirror later.

### Already there, underused

10. **The migration runner.** `core/instance/migrations.py` exists
    and is wired to `--migrate`. Zero migrations have been written.
    Until we actually ship one (even a trivial `v1.0.0_to_v1.0.1`
    no-op) the runner is dead code; it should be exercised before
    we trust it on a real schema bump.

---

## Recommended scope cuts

Three tiers, written so the next-session decision is concrete:

### A. Land in 0.2.0 (proposed Group 8)

Five new verbs, each ~1–3 hours, no schema changes:

```
jaeger instance use <name>      → writes ~/.jaeger/active_instance
jaeger instance inspect <name>  → prints identity + config + manifest
jaeger backup <name>            → zips instance dir (exclusions list above)
jaeger restore <archive>        → unzips into ~/.jaeger/<name>/
jaeger update                   → pip install -U + --migrate, one verb
```

Each gets a focused unit test + a doc line in
`docs/lifecycle.md` (new). Total budget: half-day to one day.

### B. Defer to 0.3.0

- `curl | sh` installer (when we want non-Python users)
- Homebrew tap
- `.app` bundle (py2app)

### Out of scope (not deferred — won't fit)

- **Docker image.** Mac is JROS's primary platform; Docker Desktop's
  UX on Mac is poor. Embodied robots run native. Revisit only if a
  server-deploy story emerges.

### C. Reject (don't copy from Hermes)

- Silent auto-migrate on schema bumps. Our refuse-to-start
  posture is correct; the friction is intentional.
- Single `~/.hermes/` root with profiles underneath. Our
  per-instance dir already at `~/.jaeger/<name>/` is structurally
  flatter and avoids the `default` profile being a special case.

---

## Open questions

1. **Sticky-default semantics.** If both
   `~/.jaeger/active_instance` and `JAEGER_INSTANCE_NAME` env var
   are set, which wins? Proposal: env var wins (explicit beats
   sticky), but `--instance` flag on the CLI beats both. Matches
   Hermes's precedence story.
2. **What does "update" mean when JROS is in a dev checkout?**
   `pip install -U` on an editable install no-ops. The verb
   should either:
   - Detect editable install and print "you're on a dev checkout
     — git pull yourself"
   - Or run `git pull` for the user (matches Hermes — opinionated)
3. **Backup of credentials.** Default-exclude is right for the
   "I'm syncing to Dropbox" case. But the "I'm migrating to a new
   laptop" case wants credentials. `--include-credentials` flag
   with a stderr warning?
4. **Where do backups live?** `~/.jaeger/backups/` is convenient
   but the user might want them on an external drive. Default
   path + flexible `--output` is the right shape.
5. **Restore + name conflict.** Auto-rename to `<name>-restored-<ts>`,
   or refuse + require `--force` (and back up the existing one)?
   Proposal: refuse + force, never silently rename.

---

## How this lands in the roadmap

If we approve (A):
- Add `### Group 8 — Instance lifecycle verbs` to
  `docs/ROADMAP_0.2.0.md`, after Group 5.
- The five verbs become INST-1 through INST-5.
- This doc stays as the design rationale; the roadmap entries
  link back here.

If we go (B) — defer all — this doc becomes the seed for the
0.3.0 roadmap entry. No code changes for 0.2.0 beyond what's
already landed.

---

## Final 0.2.0 layout (2026-05-25)

Decisions in this session settled the structural shape. The
roadmap (`docs/ROADMAP_0.2.0.md` → Group 8) carries the
implementation plan; this section is the authoritative diagram
the work has to land at.

### The two universes

The OS analogy: framework code is shared across instances (like
`/usr/lib/` on Linux); each instance has its own private workspace
(like `/home/<user>/`).

```
# FRAMEWORK CODE — shared, installed once via pipx
site-packages/jaeger_os/             ← the library
├── core/                            ←   agent loop, tools, skills, safety
├── agent/                           ←   adapters, drift parser, registry
├── daemon/                          ←   server, lifecycle, chat ops
├── plugins/                         ←   voice loop, messaging, MCP
├── interfaces/                      ←   tui, rich_tui, tray, gui (0.3+)
└── skills/                          ←   bundled core skills

# (no more `instance/` subdir under jaeger_os — see INST-10)


# USER STATE — per-user, written at runtime, survives upgrades
~/.jaeger/                           ← user-state root (hidden dot-dir)
├── instances/                       ← every agent workspace lives here
│   ├── default/                     ← one instance — the agent's "home"
│   │   ├── identity.yaml            ← name, role, personality, voice
│   │   ├── soul.md                  ← free-form character / values
│   │   ├── config.yaml              ← model, ctx, permissions, voice, …
│   │   ├── manifest.json            ← core_version, timestamps
│   │   ├── distribution.yaml        ← install source + framework version
│   │   ├── permissions.json         ← "always allow" grants
│   │   ├── memory/                  ← facts, episodic, embeddings
│   │   ├── skills/                  ← skills this agent authored
│   │   ├── credentials/             ← 0700 — API keys, tokens
│   │   ├── logs/                    ← audit.log, latency.jsonl, tool_results/
│   │   ├── run/                     ← PIDs, daemon socket, log (runtime)
│   │   ├── home/                    ← per-instance HOME for subprocesses
│   │   │   ├── .gitconfig           ←   (optional) per-instance git
│   │   │   └── .ssh/                ←   (optional) per-instance ssh
│   │   └── .git/                    ← agent-side skill version history
│   ├── work/                        ← another instance, fully isolated
│   └── personal/                    ← and another
├── backups/                         ← jaeger backup writes here
│   ├── default-20260825T1430.zip
│   └── work-20260820T0915.zip
├── active_instance                  ← sticky default (one-line file)
└── jaeger.env                       ← sourceable shell exports (WIZ-4)
```

### Why this shape

1. **One word, one meaning.** "Instance" exclusively refers to a
   `~/.jaeger/instances/<name>/` directory. There's no namesake
   collision in the source tree.
2. **OS analogy holds.** Framework = `/usr/lib/`; per-user state
   = `/home/`. Updating the framework doesn't touch the per-user
   data, exactly like a Linux package upgrade doesn't rewrite your
   `/home/`.
3. **Meta vs data separation.** `instances/` holds workspaces;
   `backups/`, `active_instance`, `jaeger.env` are meta-files
   about instance selection / archives. Nothing else can collide
   with a directory name a user might pick (you can name an
   instance "backups" and the layout still works).
4. **Migration-friendly.** Anyone on 0.1.0 with
   `~/.jaeger/<name>/` (flat) gets auto-migrated to
   `~/.jaeger/instances/<name>/` on first 0.2.0 boot via the
   v1.0.0 → v1.1.0 migration (INST-8). The migration is the
   first real exercise of the migration runner.
5. **Dev workflow unchanged.** Dev checkouts still use
   `sandbox/jros-dev/` via `JAEGER_INSTANCE_DIR` and
   `dev/scripts/dev_env.sh` (HYGIENE-3). The sandbox path is explicit;
   the `instances/` nesting is for user-mode only.

### Resolver order (0.2.0)

```
1. --instance NAME       (CLI flag — always wins)
2. JAEGER_INSTANCE_DIR   (env — explicit path, bypasses nesting)
3. JAEGER_INSTANCE_NAME  (env → ~/.jaeger/instances/<name>/)
4. ~/.jaeger/active_instance file (→ ~/.jaeger/instances/<that_name>/)
5. ~/.jaeger/instances/default/
6. Run wizard (no fallback to a writable temp; the user gets the
   first-run experience).
```

Note `BUNDLED_INSTANCE_ROOT` no longer appears in the resolver
— it's deleted entirely.

### What the wheel ships under `jaeger_os/`

Before INST-10:
```
jaeger_os/instance/.gitignore
jaeger_os/instance/README.md
jaeger_os/instance/default/.gitignore
jaeger_os/instance/default/memory/.gitkeep
jaeger_os/instance/default/logs/.gitkeep
jaeger_os/instance/default/skills/.gitkeep
jaeger_os/instance/default/credentials/.gitkeep
```

After INST-10:
```
(nothing — `jaeger_os/instance/` doesn't exist)
```

The layout documentation moves to `docs/instance_layout.md` (or
this design doc) — it's a docs concern, not a wheel concern.
