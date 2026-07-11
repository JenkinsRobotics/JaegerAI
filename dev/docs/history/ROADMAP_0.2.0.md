# JROS 0.2.0 — roadmap

**Status:** open · **Branched:** 2026-05-25 off `0.1.0` (commit `d31b703`)
**Theme:** **make `jaeger start` actually start Jaeger.** Headless
agent in the daemon, menu-bar icon as the "she's alive" indicator,
CLI / TUI / GUI as interchangeable clients. Plus the floating GUI
chat window ported from Lilith.

The 0.1.0 release proved the framework works end-to-end. 0.2.0 is
about making it FEEL like a product: one mental model, not five
flags.

---

## What 0.1.0 taught us (the user-facing rough edges)

These came out of the first real boot of Lilith on a clean install:

1. **`jaeger start` doesn't start Jaeger.** It forks a lifecycle
   scaffold but the agent only lives in the TUI process. The name
   lies; this is the headline confusion.
2. **`JAEGER_INSTANCE_DIR` is a load-bearing env var with no UI.**
   New shell, no env var, suddenly you're talking to "Jarvis" in
   the bundled placeholder instance instead of your Lilith.
3. **Default ctx (16K) + full tool surface = guaranteed overflow.**
   Tool schemas alone eat 14K. Every first message refuses with a
   ContextOverflow.
4. **Always-on voice mic grabs background audio.** Without
   `speexdsp`, the mic listens during agent idle and pulls in
   podcast/youtube playing nearby.
5. **Setup wizard chains into the TUI with a stale `--setup`
   flag**, hits the TUI's argparse, error-exits despite a
   successful instance creation.
6. **Role field has a silent 256-char limit.** Long roles crash
   with a pydantic ValidationError.
7. **Banner footer still says "pydantic-ai core."** Stale since
   Phase 9; nothing in the agent loop uses it.

Every one of these is a fixable 0.2.0 item.

---

## The 0.2.0 model — "one mental model, not five flags"

```
   ┌──────────────────────────────────────────────────────┐
   │   jaeger start    ← the only command you usually need │
   └────────────────────────┬─────────────────────────────┘
                            │ forks
                            ▼
          ┌──────────────────────────────────┐
          │  daemon — hosts the agent loop   │
          │  + Unix-domain socket            │
          │  + menu-bar tray (🤖)             │
          │  + model loaded ONCE             │
          └──────────────────────────────────┘
                ▲          ▲          ▲
                │          │          │ NDJSON over UDS
                │          │          │
        ┌───────┴───┐ ┌────┴────┐ ┌───┴────────┐
        │ jaeger    │ │ jaeger  │ │ jaeger     │
        │ tui       │ │ chat    │ │ gui        │
        │ (Rich)    │ │ (CLI)   │ │ (PyQt6)    │
        └───────────┘ └─────────┘ └────────────┘

   pick any client; quit it; open another; all the same agent
```

`jaeger start` runs the daemon, loads the model, lights up the
menu bar. The agent is **autonomous from that moment** — picks up
kanban cards, fires cron prompts, runs idle Deep Think — without
any client window open. The user opens a client (TUI / CLI / GUI)
when they want to chat or watch. Quit the client; the agent keeps
running.

This is the model real LLM products converged on (Claude Desktop,
Cursor's agent mode, ChatGPT on Mac all do versions of this).
JROS 0.1.0 has all the pieces (daemon, tray, TUI) but doesn't
connect them; 0.2.0 connects them.

---

## TODO — 0.2.0

Grouped by sequence. Items inside a group can be parallel;
groups should land in order so each one builds on the last.

### Group 1 — Daemon hosts the agent (BG-4 from prior roadmap)

The blocking item. **Done 2026-05-25.** `jaeger start` actually
starts Jaeger now — the daemon owns the model + agent, and clients
attach via NDJSON over the Unix socket.

- [x] **DAEMON-A** — `boot_for_daemon` in `main.py` mirrors
      `boot_for_tui`; daemon's child process owns the LLM lock,
      the agent registry, the tool dispatch. Required a side fix:
      switched spawn model from `os.fork()` to `subprocess.Popen`
      because macOS aborts a forked child the first time it
      touches an Obj-C class the parent initialized — Metal's
      `ggml_metal_device_init` was dying silently. Subprocess
      starts a fresh interpreter with
      `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` pre-set in env.
- [x] **DAEMON-B** — `chat.send(text, session_key=None)`,
      `chat.subscribe()` (streaming Events through the same
      socket), `chat.history(session_key, limit)`,
      `status.snapshot()`. Streaming required extending the
      server with `register(op, fn, streaming=True)` — the
      handler gets an `emit(name, **payload)` callback. The
      per-daemon `EventBus` fans out tool-progress / turn events
      to every subscriber (bounded queues, drop-oldest on full
      so a slow client can't stall the agent).
- [x] **DAEMON-C** — `jaeger attach` in `daemon/attach.py`. Two
      connections per session: one for `chat.subscribe`, one
      per-turn for `chat.send`. Quit attach (Ctrl-D); daemon
      keeps running. Tested end-to-end against a real Gemma
      model — Kokoro TTS spoke a response out loud.
- [x] **DAEMON-D** — **NEW** `jaeger rich-tui` in
      `interfaces/rich_tui/`. The existing `jaeger tui` (0.1.0
      surface) is **untouched** — `rich-tui` lives alongside as
      a separate Rich+prompt-toolkit client that requires a
      running daemon. No in-process fallback; if no daemon is
      up, prints a clear error and exits 1. See the
      "preserve 0.1.0 surfaces" feedback memory for the
      additive-not-replace policy. Slash commands: `/help`,
      `/status`, `/history`, `/clear`, `/quit`.
- [x] **DAEMON-E** — `Server.on_connect` / `on_disconnect`
      callbacks; `chat_ops` wires audit writers that append
      JSON lines (`daemon.client.connect` /
      `daemon.client.disconnect`) to `<instance>/logs/audit.log`
      with `client_id`, `duration_s`, `ops_called`.

**Result:** 77 daemon tests + 9 rich-tui tests added (was 13);
1088 default-tier tests still pass (was 1049 pre-Group 1).

**Live-tested commands:**
```sh
jaeger start --no-tray     # boots daemon (subprocess, model loaded)
jaeger status              # running (pid=…, uptime=…)
jaeger attach              # headless CLI; type, send, see tool events
jaeger rich-tui            # Rich UI; same daemon, banner + boot panel
jaeger stop                # clean shutdown
```

### Group 2 — Wizard + first-run UX

User-facing polish. **Done 2026-05-25.** The wizard is now 6 steps
(identity / model / permissions / interaction / warm-up / review)
and no longer crashes on long role strings or chains into an
argparse-error.

- [x] **WIZ-1** — `main.py` strips ``--setup`` (and
      ``--setup=…``) from ``sys.argv`` right after the wizard
      returns. The chain into ``tui_main`` used to argparse-error
      because the TUI's parser doesn't know ``--setup``, so a
      perfectly-finished setup looked broken.
- [x] **WIZ-2** — Role prompt shows ``[≤256 chars]`` AND a
      long answer is split gracefully: ``identity.role`` gets the
      first sentence (or a hard-cut + ellipsis if there's no
      sentence boundary), and the full original text lands in
      ``soul.md`` so nothing the user typed is lost. The pydantic
      ValidationError crash from 0.1.0 can't happen anymore.
- [x] **WIZ-3** — New Step 4 "Interaction" question writes
      ``config.yaml:interaction.default_mode``. Schema:
      ``InteractionConfig.default_mode: Literal["tui", "gui",
      "voice"]`` (default ``"tui"``). Voice + GUI both print an
      "experimental / landing in 0.2.0 Group 3" warning so the
      user knows what they're picking.
- [x] **WIZ-4** — Wizard writes ``~/.jaeger/jaeger.env``
      (``export JAEGER_INSTANCE_DIR=…`` + ``…_NAME=…``, mode
      0600). Final wizard output prints the file path and the
      ``source ~/.jaeger/jaeger.env`` one-liner so the user can
      paste it into their shell rc.
- [x] **WIZ-5** — Default ``model.ctx`` 16384 → 32768. The 0.1.0
      default plus the full tool surface guaranteed a
      ContextOverflow on the first message (tool schemas alone
      ate ~14K). Existing on-disk configs are unchanged; this is
      the new-instance default only.

**Result:** 15 new wizard tests; 1103 default-tier tests pass
(was 1088 post-Group 1).

### Group 3 — PyQt6 floating GUI (port from Lilith)

The Claude-style floating chat window. Live text conversation —
no permanent terminal, no Dock entry, just a small window you
pop open with a hotkey.

Salvage path: Lilith already has the PyQt6 code at
`Lilith-AI/src/jaeger_os/instance/lilith/gui/`:
- `chat_window.py` — the floating chat bubble
- `tray.py` — Qt-side tray (we already have a rumps tray in JROS;
  pick one — keeping rumps since it's lighter)
- `_brand.py` — brand styling helpers
- `studio_window.py` — Persona Studio (defer to 0.3+)
- `radar_chart.py` — analytics (defer)

The chat_window is the only piece needed for 0.2.0.

- [ ] **GUI-A** — Move `chat_window.py` + `_brand.py` into JROS
      under `src/jaeger_os/interfaces/gui/`. Strip the
      Persona-Studio entry points; keep the chat window only.
- [ ] **GUI-B** — Connect the chat window to the daemon (Group 1's
      NDJSON protocol) — sends user input, subscribes to streamed
      events. Same shape as the TUI's bind.
- [ ] **GUI-C** — Visual parity with the TUI's response panel —
      "thinking" indicator while she ruminates, response body in
      a soft panel, tool-activity dots at the bottom. Reuse
      TUI's status-string format so users don't relearn.
- [ ] **GUI-D** — Voice **OUTPUT** on by default (she speaks her
      response via Kokoro); voice **INPUT** off by default (no
      always-on mic). Both togglable in the window.
- [ ] **GUI-E** — `jaeger gui` CLI command — launches the window
      against the running daemon. Hotkey to summon/hide is
      Option+Space (Lilith's pattern); writable in config.
- [ ] **GUI-F** — Tests: chat-window unit tests, paste handling,
      streaming-event rendering, mic toggle.

Cost: ~2 days. The biggest chunk after Group 1.

### Group 4 — Voice defaults & robustness

**Done 2026-05-25.** The mic-grabs-podcast bug + install-time AEC
story are both fixed; the always-on mic is now strictly opt-in.

- [x] **VOICE-1** — `VoiceConfig.enabled` schema default flipped
      `True → False`. The wizard only writes `enabled=True` when
      the user explicitly picks voice as the default interaction
      mode AND opts in to the always-on mic via a y/n prompt. The
      other voice toggles (wake_word / follow_up / barge_in) stay
      ON so the safe defaults are in place when voice DOES turn on.
- [x] **VOICE-2** — Wizard probes for `speexdsp` (via
      `importlib.util.find_spec`) when the user picks voice. If
      missing, offers a one-tap `pip install speexdsp` (120s
      timeout, non-fatal on failure); if installed, prints a
      "echo cancellation will work" confirmation. Either way the
      user gets a clear y/n on enabling the mic immediately.
- [x] **VOICE-3** — `_find_wake_in_text` and continuous-mode
      `_extract_command` both gated to the FIRST N tokens of the
      transcript (matching the wake-phrase token count). "yes I
      think hey jaeger is cool" no longer triggers. Fuzzy fallback
      still works for Whisper mishearings ("yeager", "jager") on
      the same head window.
- [x] **VOICE-4** — `_commit` in continuous mode and the
      no-wake-match branch in two-pass mode both now print
      `[mic heard X — not sent]` when the wake gate rejects a
      transcript. Previously the rejection was silent, making
      the always-on mic feel broken on every utterance that
      didn't open with a wake phrase.

### Group 5 — Bug + polish sweep

**Done 2026-05-25 (except POLISH-3, deferred — see below).**

- [x] **POLISH-1** — TAGLINE in `interfaces/tui/banner.py` no
      longer says "pydantic-ai core" (stale since Phase 9). Now
      reads "framework-free Phase-9 loop". Shared by both the
      0.1.0 `jaeger tui` and the new `jaeger rich-tui` since they
      import the same banner.
- [x] **POLISH-2** — `status._visible_tool_groups()` filters
      `TOOL_GROUPS` to the `CORE` intersection when
      `JAEGER_TOOLSET_SCOPING` is on; the header annotation reads
      "(17/55 · lean surface ON · others load on demand)" so the
      user sees both the active count and the total registry.
      No-op when scoping is off — the existing panel renders
      unchanged.
- [ ] **POLISH-3** — **DEFERRED.** The roadmap text says "bench
      held 96% at the new CORE — safe", but `toolsets.py`'s own
      docstring records a routing regression on Gemma 4 26B
      (100% → 67.6%) under the new lean default. The conflicting
      evidence means a flip needs a fresh bench before it can
      land. Tracking as a separate item; the env-var override
      (`JAEGER_TOOLSET_SCOPING=1`) still works.
- [x] **POLISH-4** — `skill(action="view")` now auto-calls
      `enable_toolset(...)` for every entry in the skill's
      `requires_toolsets` list. The response carries
      `auto_loaded_toolsets` + the updated `active_toolsets` so
      the model can see what just became visible. Saves one
      `load_toolset` round-trip per `skill(view)`. No-op when
      scoping is off.
- [x] **POLISH-5** — `scripts/generate_agent_contract.py` reads
      every public `RULE_NAME = """..."""` constant from
      `core/prompts/rules.py` and writes a 7-section
      `docs/agent_contract.md`. `--check` mode exits 1 if the
      doc is out of date — wire it into CI to catch drift.
- [x] **POLISH-6** — `test_docstring_purity.py` is the linter
      `rules.py` already referenced. Pattern set tuned to skip
      input-spec language ("must be a key", "must appear once")
      while catching real behavioural directives. Currently runs
      as a **scoreboard** (6 baseline findings — all in
      `credentials.py`, `identity_tools.py`, `memory.py`,
      `meta.py`, `time_and_math.py`); a future sweep moves them
      into `rules.py` and flips `ENFORCE_CEILING=True`.

### Group 8 — Instance lifecycle verbs

The platform layer. **Done 2026-05-25.** 0.2.0 now wraps the
installed instance with real operational verbs: explicit setup,
sticky default, backup, restore, update with migration,
per-instance subprocess HOME, and a distribution manifest. The
0.1.0 → 0.2.0 layout move (`~/.jaeger/<name>/` → `~/.jaeger/instances/<name>/`)
runs automatically on first 0.2.0 boot, with a pre-migration
backup so the user can always roll back.

**Design rationale + Hermes Agent comparison:** see
[docs/lifecycle_design.md](lifecycle_design.md). All decisions
recorded there came out of the 2026-05-25 design session.

**Decisions taken:**
- Concept name stays **instance** (not "profile").
- Install path: **pipx** documented + pip for devs.
  `curl | sh` deferred to 0.3.0+; Docker out of scope (Mac is
  primary, Docker UX on Mac is poor).
- Sticky-default precedence: `--instance` flag >
  `JAEGER_INSTANCE_DIR` env > `JAEGER_INSTANCE_NAME` env >
  `~/.jaeger/active_instance` file > literal `"default"`.
- `jaeger update` finds N stale instances and prompts per-instance
  (interactive, with auto-backup) — not silent batch.
- CORE_VERSION bump 1.0.0 → 1.1.0 with a no-op migration ships in
  this group so the migration runner is exercised before a real
  schema change rides on it.
- `jaeger backup` includes user-authored skills by default
  (they're core to the agent's identity); excludes credentials,
  runtime state, regenerable caches.
- `jaeger update` prints "restart to apply" rather than
  auto-restarting a running daemon.
- Per-instance subprocess HOME is in scope; wizard adds an
  optional Step 7 for per-instance git identity.

**Item plan:**

- [x] **INST-1** — Resolver order, top to bottom:
      1. `--instance NAME` CLI flag
      2. `JAEGER_INSTANCE_DIR` env var (explicit path)
      3. `JAEGER_INSTANCE_NAME` env var → `~/.jaeger/instances/<name>/`
      4. `~/.jaeger/active_instance` file → `~/.jaeger/instances/<name>/`
      5. `~/.jaeger/instances/default/`
      6. Run wizard.

      Drop the `BUNDLED_INSTANCE_ROOT` branch — `src/jaeger_os/instance/`
      no longer exists post-INST-10. ``USER_ROOT`` becomes
      `~/.jaeger/instances/`.
- [x] **INST-2** — Verb consolidation. New verbs (with the old
      flags kept as deprecated aliases for one release):
      ```
      jaeger setup [--name N] [--force]
      jaeger instance list / use / inspect / delete / clear
      jaeger migrate
      ```
- [x] **INST-3** — `DistributionConfig` Pydantic model +
      `distribution.yaml` per instance. Fields:
      `created_with_framework`, `install_method` (Literal
      `pip|pipx|dev-checkout|imported`), `install_source`,
      `created_at`, `last_updated_with_framework`. Wizard
      writes it; `jaeger update` rewrites
      `last_updated_with_framework`; restore writes
      `install_method=imported` + `restored_from: <archive>`.
- [x] **INST-4** — Per-instance subprocess HOME jail.
      `InstanceLayout` gains `home_dir = root / "home"`. New
      helper `subprocess_env_for_instance(layout)` returns
      `os.environ.copy()` with `HOME` swapped — ONLY when
      `home_dir/.gitconfig` (or any populated marker) exists,
      otherwise falls back to user's real `HOME` so existing
      instances are undisturbed. Audit + reroute every
      `subprocess.run` / `subprocess.Popen` site:
      `core/tools/{terminal,files,code,packages,
      remote_terminal}.py`, `core/skills/skill_loader.py`,
      `plugins/messaging_gateway.py`. Wizard Step 7 (optional):
      per-instance git name + email + optional SSH key path.
- [x] **INST-5** — `jaeger backup [--name N] [--output PATH]
      [--include-credentials]`. Default output
      `~/.jaeger/backups/<name>-<ISO8601>.zip`. Default
      excludes: `credentials/*`, `run/*`,
      `memory/*.embeddings.npz`, `logs/audit.log.[0-9]*`,
      `logs/tool_results/*`, `home/.cache/`,
      `home/.npm/_cacache/`. Zip carries `MANIFEST.json` with
      framework version + included-files list so restore can
      validate.
- [x] **INST-6** — `jaeger restore <archive> [--name NEW]
      [--force]`. Refuse on name conflict unless `--force` (in
      which case back the existing one up first, wizard
      pattern). Validate the archive's manifest: refuse if
      `created_with_framework` is newer than current
      `CORE_VERSION`; auto-prompt to migrate if older. Write
      `restored_from` to `distribution.yaml` post-restore.
- [x] **INST-7** — `jaeger update [--check] [--no-migrate]`.
      Detect install method (pipx > pip > editable > unknown);
      run the appropriate upgrade. After install, scan every
      `~/.jaeger/<name>/` for `manifest.json` with a
      `core_version` != current `CORE_VERSION`; for each, an
      **interactive** "back up + migrate? [Y/n]" prompt.
      `--check` exits without installing. `--no-migrate` runs
      the framework upgrade but skips migration scan. Prints
      "Restart `jaeger` to apply" rather than auto-restarting
      a running daemon.
- [x] **INST-8** — `src/jaeger_os/migrations/v1_0_0_to_v1_1_0.py`
      — the **real** migration that moves `~/.jaeger/<name>/`
      (0.1.0 flat layout) to `~/.jaeger/instances/<name>/`
      (0.2.0 nested layout per INST-10). Walks
      `~/.jaeger/`, identifies each directory containing an
      `identity.yaml` (skip `instances/`, `backups/`,
      `active_instance`, `jaeger.env`), and moves it under
      `instances/`. After move, updates the moved instance's
      `manifest.json:core_version` to `"1.1.0"`.
      `schemas.py:CORE_VERSION` bumps `"1.0.0"` → `"1.1.0"`.

      Failure modes: refuse if `~/.jaeger/instances/<name>/`
      already exists (caller picks; either rename or merge).
      Pre-migration backup written to
      `~/.jaeger/backups/pre-1.1.0-<ts>.zip` automatically.

      First-run on 0.2.0 → user sees:
      ```
      [migrate] found 0.1.0 layout — moving 2 instance(s) into
                ~/.jaeger/instances/
      [migrate] backing up to ~/.jaeger/backups/pre-1.1.0-….zip
      [migrate] default → ~/.jaeger/instances/default/
      [migrate] work    → ~/.jaeger/instances/work/
      [migrate] manifest bumped to 1.1.0
      ```
- [x] **INST-9** — README + `--doctor` install hints. README
      install section leads with `pipx install jaeger-os`,
      mentions `pip install jaeger-os` under "for contributors".
      `jaeger --doctor` detects when the running install is
      pip-on-system-Python (not pipx, not editable) and
      suggests pipx for cleaner isolation; advisory, never
      blocking.
- [x] **INST-10** — Structural rename. Drop
      `src/jaeger_os/instance/` from the source tree entirely;
      nest user instances under `~/.jaeger/instances/<name>/`
      so the word "instance" appears only in the user-state
      path + CLI verbs (never in the framework source).
      Subtasks:
      - Remove `src/jaeger_os/instance/` (was the bundled
        skeleton; HYGIENE-1 already reduced it to 4 .gitkeep
        files + README; INST-10 finishes the job).
      - Move the layout diagram from
        `src/jaeger_os/instance/README.md` to
        `docs/instance_layout.md` (or merge into
        `docs/lifecycle_design.md`).
      - Update `core/instance/instance.py`: drop
        `BUNDLED_INSTANCE_ROOT`; `USER_ROOT` becomes
        `~/.jaeger/instances/`; resolver simplifies per INST-1.
      - Update `MANIFEST.in` (drop `instance/**` includes /
        excludes since the dir is gone).
      - Update `pyproject.toml` `package-data` /
        `exclude-package-data` (drop `instance/*` entries).
      - Update `scripts/check_wheel.py`'s
        `ALLOWED_INSTANCE_FILES` (now empty for
        `jaeger_os/instance/`).
      - Update every test that hardcodes
        `instance/default/` paths.
      - Update `dev/scripts/dev_env.sh` if it references the bundled
        location (it shouldn't — already points at
        `sandbox/jros-dev/`).
      - The 0.1.0 → 1.1.0 move happens in INST-8 (which
        becomes the *real* migration instead of a no-op).

**Cost estimate held:** ~2 days of work; shipped on 2026-05-25
in one session. **Test count delta:** +52 new tests
(test_legacy_migration: 10, test_subprocess_env: 13,
test_backup_restore: 17, test_update_verb: 12) on top of
test_instance_resolver's 20.

**Final tally for Group 8:** 1175 default-tier tests pass
(was 1133 pre-INST-1); no regressions across integration,
subprocess, or smoke tiers.

**Implementation notes:**

- Per-roadmap, INST-8's legacy-layout move runs **before** the
  resolver fires (one-shot bootstrap in
  ``core/instance/legacy_migrations.py``). The per-instance
  ``migrations/v1_0_0_to_v1_1_0.py`` script the runner picks up is
  small — it ensures the migrated instance's ``config.yaml``
  carries the new ``interaction`` field explicitly. The
  manifest-version bump happens automatically when the runner
  walks the migration plan.
- INST-4 wires the per-instance HOME jail at TWO call sites
  (``core/tools/_common.py`` audit-log git commit, and the wizard's
  initial git init). Other subprocess call sites (run_python
  sandbox, browser, web fetch) have their own purpose-built env
  and intentionally stay on the user's real HOME. The helper
  (``subprocess_env_for_instance``) is exported so future call
  sites can opt in case-by-case.
- INST-7's auto-restart was rejected per the design decisions —
  the verb prints "Restart `jaeger` to apply" rather than killing
  the user's running daemon mid-flow.

**Open questions resolved in implementation:**
1. `jaeger update` on an editable install — print "run `git pull`
   yourself" or actually run it? Proposal: print, don't act
   (matches the conservative posture).
2. Restore from an archive whose `created_with_framework` is the
   same as current but `manifest.core_version` is older —
   migrate after restore? Proposal: yes, in the same flow.
3. The `.gitconfig` we write in INST-4 — read from user's real
   `~/.gitconfig` as defaults? Or always start blank? Proposal:
   start blank; user opts in to filling it.

### Group 9 — Data layer (SQLite migration)

**Status:** plan locked in 2026-05-26; implementation pending.

The user's training-data ambitions (LLM + neural network work
soon) push the memory store beyond what JSON/JSONL handles
cleanly. Episodic at training scale (100K+ rows) is the breaking
point: append latency, semantic search over embeddings, and joins
across episodic + tool_calls + sessions all favour SQL.

Scope decision (2026-05-26): **full SQLite, not hybrid**. The
hybrid plan was a faster win but locks us out of clean training-
data export queries that span multiple stores.

**Item plan:**

- [x] **DB-1** — `core/memory/sqlite_store.py` shipped 2026-05-26.
      All 7 tables created on first open (`facts`, `episodic`,
      `episodic_embeddings`, `schedules`, `sessions`, `tool_calls`,
      `schema_version`). WAL + foreign-keys + 5s busy-timeout pragmas
      pinned. `sqlite-vec` extension load attempted on bind with a
      clean fall-through to Python-cosine when the extension is
      missing (most platforms today). `writer()` context manager
      serialises writes with a thread lock + BEGIN IMMEDIATE +
      ROLLBACK-on-exception. Schema version 1; future-version DBs
      refuse-to-open. **16 unit tests** in
      `tests/jaeger_os/core/memory/test_sqlite_store.py`.
- [x] **DB-2** — Facts table rewired 2026-05-26.
      `remember` / `recall` / `forget` / `list_facts` /
      `list_facts_by_category` all SQL-backed; public API
      unchanged so the tool layer + agent prompts don't notice.
      Each row carries `category`, `created_at`, `updated_at`;
      INSERT-OR-REPLACE preserves `created_at` on overwrite.
      Lazy-import on bind moves existing `facts.json` into SQL
      (handles both shapes: old flat ``{k: v}`` and 0.1.x
      ``{schema_version, facts, categories}``); skipped when SQL
      already has rows. **18 new unit tests** in
      `tests/jaeger_os/core/memory/test_facts_sql.py`; two
      legacy-JSON tests in `test_memory_categories.py` rewritten
      for the new contract.
- [x] **DB-3** — Episodic table rewired 2026-05-26. ``append_episodic``
      and ``load_recent_turns`` are SQL-backed; session_key
      filtering preserved; tool_activity / latency / skipped_final
      land in typed columns; unknown keys are bundled into
      ``meta_json`` so schema evolution never drops a field. Lazy
      import from ``episodic.jsonl`` runs on first bind. **16
      tests** in `test_episodic_sql.py`.
- [x] **DB-4** — Embeddings + ``sqlite-vec`` shipped 2026-05-26.
      Each episodic row gets a vector row in ``episodic_embeddings``
      (BLOB float32, dim + model recorded). ``search_memory`` runs
      cosine over BLOBs (Python fallback) when ``sqlite-vec`` isn't
      loaded. Encoder is lazy-loaded only when there's something to
      search. **13 tests** in `test_search_memory_sql.py` (model
      mocked to keep the default tier model-free).
- [x] **DB-5** — Schedules rewired 2026-05-26. ``add_schedule`` /
      ``list_schedules`` / ``cancel_schedule`` /
      ``claim_due_schedules`` all SQL-backed; lazy-import handles
      legacy ``schedules.jsonl`` shape including mid-replay
      cancellations. **18 tests** in `test_schedules_sql.py`.
- [x] **DB-6** — Tool-call log shipped 2026-05-26.
      ``record_tool_call`` redacts via ``redact_obj``, JSON-encodes
      with ``default=str`` fallback, links optional ``episodic_id``
      (FK to episodic), and is best-effort (DB failure never
      crashes a turn). Wired into the agent via a new
      ``tool_done`` callback on ``AgentCallbacks``; ``main.py``'s
      ``_run_turn_via_jaeger_agent`` provides the closure that
      captures session_key. **24 tests** in `test_tool_calls_sql.py`.
- [x] **DB-7** — Audit log shipped 2026-05-26 as a **dual-write**:
      ``logs/audit.log`` JSONL stays canonical (forensic
      append-only); SQL ``audit_log`` table mirrors every event for
      queryability. ``_audit()`` writes both, redacted once. Lazy
      import from existing JSONL on first bind. **19 tests** in
      `test_audit_log_sql.py`. Decision on binary tool-result
      spills: keep on disk under ``logs/tool_results/`` (no BLOB
      storage) — paths land in audit/tool_calls rows as references.
- [x] **DB-8** — Migration ``v1_1_0_to_v1_2_0.py`` shipped
      2026-05-26. Triggers all four lazy importers via
      ``mem.bind(layout)`` then renames every successfully-imported
      legacy file to ``<name>.legacy`` (facts.json, episodic.jsonl,
      schedules.jsonl, episodic.embeddings.npz). ``audit.log``
      stays in place — canonical record. Idempotent; never
      overwrites an existing ``.legacy`` backup. **10 tests** in
      `tests/jaeger_os/migrations/test_v1_1_0_to_v1_2_0.py`.
- [x] **DB-9** — Cross-cutting tests shipped 2026-05-26. **13
      tests** in `test_sqlite_cross_cutting.py` covering: WAL +
      foreign_keys + busy_timeout pragmas, concurrent reader during
      writer, two writers serialised via the write lock,
      ``sqlite-vec`` graceful fallback (verified by forcing
      ``has_vec_extension`` False and running the Python-cosine
      path), schema-version refuse-to-open, bind idempotence,
      rebind to a different instance isolates data,
      writer-rollback-on-exception.
- [x] **DB-10** — ``jaeger memory export`` / ``stats`` verbs
      shipped 2026-05-26. ``daemon/memory_verbs.py`` registered in
      ``cli.dispatch``. Export writes per-table json/jsonl/csv
      files + a manifest; JSON columns (args_json, result_json,
      payload_json, meta_json, tool_activity) are decoded into
      structured fields so the consumer doesn't have to parse
      JSON-in-JSON. Second-pass ``redact_obj`` for belt-and-braces
      on rows that pre-date the current redactor. ``stats`` shows
      DB path + size + per-table row counts + vec-extension state.
      **16 tests** in `tests/jaeger_os/daemon/test_memory_verbs.py`.

**Cost:** ~3 days focused, possibly more if `sqlite-vec`
packaging is awkward on the user's platform.
**Actual:** completed 2026-05-26 in one session. **1491
default-tier tests passing** (was 1282 at end of DB-5 → +209 over
DB-6..DB-10).

**CORE_VERSION:** bumped 1.1.0 → 1.2.0 with this group.

### Group 6 — Release hygiene (urgent — 0.1.0 ship bug)

The `src/jaeger_os/instance/default/` directory in the JROS repo
is currently a dev playground. It got bundled into the 0.1.0
wheel — every `pip install jaeger-os` ships ~2.7 MB of stale memory,
agent-test artifacts, dev logs, and leftover credentials placeholder
slots. New installs find this writable site-packages location FIRST
in the path resolver, so they unknowingly load OUR dev junk instead
of their own fresh state.

What needs to happen:

- [x] **HYGIENE-1** — Clean `src/jaeger_os/instance/default/` to a
      minimal skeleton. **Done 2026-05-25** — dev state moved to
      `sandbox/jros-dev/`; bundled tree now holds only
      `default/{memory,logs,skills,credentials}/.gitkeep`. The wizard
      writes `config.yaml` / `identity.yaml` / `soul.md` /
      `manifest.json` on first run, so no template files are needed
      in the skeleton.
- [x] **HYGIENE-2** — `.gitignore` rules so runtime-writable
      subdirs don't accumulate. **Done 2026-05-25** — extended
      `src/jaeger_os/instance/.gitignore` with `*/run/` (PID + socket
      + log scratch). The existing `*/memory/*`, `*/logs/*`,
      `*/skills/*`, `*/credentials/*`, `*/.git/` rules already covered
      the rest; only `run/` was missing.
- [x] **HYGIENE-3** — `sandbox/` directory + dev shim. **Done
      2026-05-25** — `sandbox/` added to the root `.gitignore`;
      `dev/scripts/dev_env.sh` exports `JAEGER_INSTANCE_DIR=$REPO/sandbox/jros-dev`
      (sourced) or runs a subcommand with the var set. The dev
      instance now lives at `sandbox/jros-dev/` (including its
      `.git/` skills-audit history).
- [x] **HYGIENE-4** — Instance-dir resolver priority. **Done
      2026-05-25** — `is_pip_installed()` checks for a
      `site-packages` / `dist-packages` ancestor on `PACKAGE_ROOT`;
      `resolve_instance_dir()` picks `~/.jaeger/<name>/` over the
      bundled location whenever that's true. Editable installs
      (`pip install -e .`) still resolve to the source checkout, so
      they correctly stay in DEV mode.
- [x] **HYGIENE-5** — Wheel manifest audit. **Done 2026-05-25** —
      `scripts/check_wheel.py` enforces an ALLOWED_INSTANCE_FILES
      list (parent .gitignore + README + four `.gitkeep`s); refuses
      anything else under `jaeger_os/instance/`. Covered by 11 unit
      tests under `tests/jaeger_os/core/test_instance_resolver.py`.
      The 0.1.0 wheel is flagged with 7 known leaks; the fresh build
      is clean.

      Adjacent fix: `pyproject.toml`'s `setuptools.packages.find`
      now excludes `python_hermes_agent*` (the vendored Hermes
      reference clone). 0.1.0 didn't ship that dir; it was about to
      sneak into 0.2.0's wheel (+~8 MB).

Cost: half day total. **Should land in 0.2.0 first item** so all
subsequent dev work lands in the sandbox, not the bundled tree.

### Group 7 — Future-Lilith / future-Jaeger (deferred again)

These stay deferred for after 0.2.0 ships:

- BG-1: Three Laws + safeguard hardening (gating before
  Jaeger physical-port)
- BG-2: Move 67 wrappers out of `main.py`
- BG-3: `.app` bundling with py2app for Launchpad
- macos_computer per-app dispatch expansion
- `--doctor-deep` live API probes
- Unify `agent/schemas/toolsets.py` + `core/skills/toolsets.py`

---

## What 0.2.0 looks like when done

The new-user flow becomes:

```bash
pip install jaeger-os                  # one command
jaeger --setup                         # interactive wizard, picks
                                       # interaction mode + model
jaeger start                           # boots the agent in background
                                       # — 🤖 in menu bar
                                       # — model loaded once
                                       # — autonomous from now on
```

From here the user can:
- **Click the menu-bar 🤖** → Open TUI / Open GUI / Quit
- **Run `jaeger gui`** for the floating chat window
- **Run `jaeger tui`** for the terminal interface
- **Run `jaeger attach`** for a headless CLI tail
- **Run `jaeger chat "hi"`** for one-shot exchanges

The agent runs autonomously the whole time — works the kanban,
fires cron, deep-thinks when idle, persists what matters. The
client is "how I talk to her right now," not "the thing that
contains her."

That's the 0.2.0 promise.

---

## Bench bar for 0.2.0

Same as before — 0.1.0 numbers held or improved on every suite,
hermetic mode. Adding one new gate for the daemon path:
**connect-disconnect cycles must not regress agent state** (run
the bench against the daemon-hosted agent and confirm hermetic
mode still works when the test client is `jaeger attach` instead
of in-process).

---

## Receipts

Append SHA / PR / bench reference as items land. Same shape as
the 0.1.0 commit history we just put together.
