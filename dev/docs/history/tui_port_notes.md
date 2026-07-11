# TUI port — hermes-feature parity

Porting hermes-agent's TUI features into JROS's TUI
(`src/jaeger_os/interfaces/tui/`).

**Decision:** all-Python via `prompt_toolkit` — feature parity with
hermes, *not* the React/Ink `ui-tui` (that is a TypeScript frontend +
a WebSocket Python gateway; a client-server, two-language stack that
fights JROS's in-process design). `prompt_toolkit` is what hermes's own
earlier `hermes_cli` TUI uses, so it is a proven path.

## Done

- **Slash autocomplete** — `completion.py`: `SlashCompleter` (a filtered
  `/command` dropdown with one-line summaries + subcommand completion)
  and `SlashAutoSuggest` (dim inline ghost text predicting the rest of
  the command). Built from the slash-command registry.
- **prompt_toolkit input layer** — `ptk_input.py`: a `PromptSession`
  with the completer, autosuggest, command history (↑/↓), and a
  persistent bottom status bar. Replaces the Rich `Prompt.ask` input.
  Falls back to plain `input()` on a non-TTY (pipes, tests).
- **Bottom status bar** — `JaegerTUI._bottom_toolbar()`: model, context,
  uptime, mic state — re-rendered on every keystroke. Toggle with
  `/statusbar`.
- **New slash commands** — `/status`, `/statusbar`, `/stop`, `/save`.
- Already present before the port: banner + toolset catalog, the
  slash-command set, Ctrl-C / spoken-word turn interruption, voice mode.

## Deferred — notes to complete

- **Type-to-interrupt** (type a new message mid-turn to interrupt it).
  `PromptSession.prompt()` is blocking — the input isn't live while a
  turn runs. Needs the full `prompt_toolkit.Application` (UI thread +
  agent worker thread + queues — hermes's pattern). *Interruption today:
  Ctrl-C aborts the turn; speaking interrupts a voice turn.*
- **Auto-idle Deep Think on the typed path** — the old select-based
  `_read_line` self-timed and could auto-enter Deep Think; a plain
  `PromptSession.prompt()` has no timeout. The voice poll loop still
  honors auto-idle. To restore for the typed path: a watchdog thread
  that calls `app.exit()` on the session, or move to the full
  `Application`.
- **`/sessions` / `/resume` / `/snapshot`** — browsing and resuming past
  sessions. Needs a persistent session store (hermes uses a SQLite
  `SessionDB`). `/save` (export the current conversation to markdown)
  is done; durable cross-session history is the missing piece.
- **`/skin`** — display themes. No theme system yet; `prompt_toolkit`
  supports a `Style` a skin could drive, and Rich a theme.
- **`/steer` / `/subgoal`** — inject mid-turn guidance / extra goal
  criteria. Belong with MAIN LOOP work (need agent steer/subgoal hooks).
- **`/skills`** — a skill browser/inspector. JROS loads skills but has
  no list/inspect slash command yet.
- **Multiline input** — single-line for now; `prompt_toolkit` supports
  multiline (e.g. Shift+Enter inserts a newline) as a later nicety.

## Architecture note

The full `prompt_toolkit.Application` (custom layout, the UI on its own
thread) would unlock type-to-interrupt and a turn-time live status bar.
It is the larger follow-up; the current `PromptSession` approach gives
autocomplete + ghost text + status bar + history robustly and without a
risky rewrite of the REPL, voice loop, and goal/Deep-Think loops.
