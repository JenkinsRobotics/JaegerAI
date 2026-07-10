# Hermes CLI/CUI → JROS TUI — Feature-Inventory & Port Checklist

Authoritative comparison of `src/python_hermes_agent/upstream/cli.py` (the
`HermesCLI` interactive terminal — 13,736 lines) against the JROS TUI
(`src/jaeger_os/interfaces/tui/*` + the agent loop in `src/jaeger_os/main.py`).

Every module-level function and every `HermesCLI` method is listed **in file
order**. JROS status is one of:

- **HAVE** — JROS has a real equivalent.
- **PARTIAL** — JROS has something weaker/different.
- **MISSING** — no equivalent.
- **SKIP** — hermes-internal plumbing that does not apply to JROS (skin engine,
  termux, git worktrees, OpenAI/Codex runtime, curses pickers, OSC52, session
  SQLite DB, multiplexer-resize recovery, etc.). JROS deliberately uses Rich +
  prompt_toolkit only and keeps its own vocabulary.

`port?` is YES / improve / no with a short reason.

JROS files referenced (all absolute):
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/app.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/slash_commands.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/status.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/ptk_input.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/completion.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/banner.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/voice_session.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/interfaces/tui/__main__.py`
- `/Users/jonathanjenkins/GITHUB/JROS/src/jaeger_os/main.py`

---

## 1. Module-level helpers (cli.py lines 128–2270)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_strip_reasoning_tags` (128) | strip `<think>`/`<reasoning>`/tool-call XML from displayed text | PARTIAL | `main.py:_strip_drift_markup` (1718) strips drift markup; reply rendered as plain `Text` so XML never interpreted | improve — fold think/tool-call tag stripping into `_strip_drift_markup` |
| `_assistant_content_as_text` (200) | flatten multimodal assistant content to a string | MISSING | JROS replies are plain strings; no multimodal content parts | no — not needed for local single-model |
| `_assistant_copy_text` (215) | strip+flatten for `/copy` | MISSING | no `/copy` command | no — see `/copy` row |
| `_load_prefill_messages` (223) | load ephemeral prefill messages from JSON | SKIP | hermes session-prefill plumbing | no |
| `_parse_reasoning_config` (252) | parse reasoning-effort string → OpenRouter config | SKIP | OpenRouter/Codex-specific | no |
| `_parse_service_tier_config` (261) | parse priority/fast tier string | SKIP | OpenAI priority-processing plumbing | no |
| `load_cli_config` (271) | load+merge `~/.hermes/config.yaml`, bridge to env vars | HAVE | JROS uses per-instance `config.yaml` via `core.schemas`/`InstanceLayout`; boot in `main.boot_for_tui` | no — JROS config model is its own |
| `_run_cleanup` (696) | atexit: tear down terminals/browsers/MCP/memory once | HAVE | `app.repl` finally block + `_boot.cleanup()`; `main.shutdown_extensions` | no |
| `_normalize_git_bash_path` (756) | translate Git-Bash paths on Windows | SKIP | git-worktree / Windows plumbing | no |
| `_git_repo_root` (785) | find git repo root | SKIP | git worktrees | no |
| `_path_is_within_root` (806) | path-containment check for worktree copy | SKIP | git worktrees | no |
| `_setup_worktree` (815) | create isolated git worktree per session | SKIP | git worktrees — JROS uses instance dirs | no |
| `_cleanup_worktree` (943) | remove worktree + branch on exit | SKIP | git worktrees | no |
| `_run_state_db_auto_maintenance` (1007) | prune/vacuum the session SQLite DB | SKIP | JROS has no session SQLite DB | no |
| `_run_checkpoint_auto_maintenance` (1061) | prune filesystem checkpoints | SKIP | JROS has no checkpoint manager | no |
| `_prune_stale_worktrees` (1085) | remove stale worktrees on startup | SKIP | git worktrees | no |
| `_prune_orphaned_branches` (1158) | delete orphaned `hermes/*` branches | SKIP | git worktrees | no |
| `_hex_to_ansi` (1244) | hex color → true-color ANSI escape | SKIP | skin engine; JROS uses Rich styles | no |
| `_SkinAwareAnsi` (1256) | lazy skin-resolving ANSI escape class | SKIP | skin engine | no |
| `_accent_hex` (1296) | active skin accent color | SKIP | skin engine | no |
| `_rich_text_from_ansi` (1305) | safely render text that may contain ANSI | PARTIAL | JROS wraps reply in plain `Text` (`app._render_answer`); no ANSI passthrough | no — JROS reply path is markup-safe already |
| `_strip_markdown_syntax` (1314) | best-effort markdown-marker removal | MISSING | JROS renders the reply verbatim in a panel — no strip/render/raw mode | improve — a `display.markdown` mode would help readability |
| `_preserve_windows_dot_segments_for_markdown` (1340) | keep Windows `\.` paths intact for markdown | SKIP | Windows + markdown rendering | no |
| `_terminal_width_for_streaming` (1357) | streamed-box content width budget | PARTIAL | JROS panels auto-size via Rich; no streaming box | no |
| `_render_final_assistant_content` (1375) | render reply as markdown / stripped / raw | PARTIAL | `app._render_answer` always renders plain `Text` in a panel | improve — add a markdown render mode |
| `_coerce_output_history_limit` (1423) | clamp the output-history line cap | SKIP | output-history replay (resize recovery) — N/A | no |
| `_configure_output_history` (1430) | configure recent-output replay buffer | SKIP | output-history replay | no |
| `_clear_output_history` (1438) | clear output-history buffer | SKIP | output-history replay | no |
| `_suspend_output_history` (1443) | ctx-mgr to suspend output recording | SKIP | output-history replay | no |
| `_record_output_history_entry` (1453) | append a callable/line to history | SKIP | output-history replay | no |
| `_record_output_history` (1459) | strip ANSI + append text lines to history | SKIP | output-history replay | no |
| `_replay_output_history` (1469) | repaint recent output after a screen clear | SKIP | output-history replay (Ctrl+L recovery) | no |
| `_cprint` (1494) | thread-safe ANSI print routed via prompt_toolkit | PARTIAL | JROS prints through Rich `Console` directly; no concurrent bg-thread prints to fight (REPL is single-threaded) — relevant only if concurrent input lands | improve — needed if process_loop architecture is ported |
| `_termux_example_image_path` (1590) | example media path for Termux | SKIP | termux | no |
| `_split_path_input` (1604) | split leading file-path token from trailing text | MISSING | no file-drop / image-attach support | no — JROS has no image input |
| `_resolve_attachment_path` (1647) | resolve user-supplied attachment path | MISSING | no file-drop / image-attach support | no |
| `_format_process_notification` (1708) | format a bg-process completion event | PARTIAL | JROS has `background` tools + `/stop`; no async completion-notification injection into the REPL | improve — async bg-completion notices would be nice |
| `_detect_file_drop` (1747) | detect a dragged/pasted file path in input | MISSING | no file-drop detection | no — local agent, lower priority |
| `_format_image_attachment_badges` (1819) | render attached-image badge row | MISSING | no image attachment | no |
| `_should_auto_attach_clipboard_image_on_paste` (1852) | true for image-only paste gestures | MISSING | no clipboard image attach | no |
| `_strip_leaked_bracketed_paste_wrappers` (1857) | strip leaked bracketed-paste markers | SKIP | terminal-quirk hardening; prompt_toolkit `PromptSession` handles paste | no |
| `_preserve_ctrl_enter_newline` (1913) | detect terminals where Ctrl+Enter must be newline | SKIP | terminal-quirk plumbing | no |
| `_bind_prompt_submit_keys` (1944) | bind Enter/c-j submit keys | SKIP | `PromptSession` handles submit keys | no |
| `_disable_prompt_toolkit_cpr_warning` (1963) | suppress CPR fallback warning | SKIP | terminal-quirk plumbing | no |
| `_strip_leaked_terminal_responses_with_meta` (1971) | strip leaked CPR / mouse-report escapes from input | SKIP | terminal-quirk hardening | no |
| `_strip_leaked_terminal_responses` (2014) | compat wrapper around the above | SKIP | terminal-quirk hardening | no |
| `_collect_query_images` (2020) | collect image attachments for single-query flows | MISSING | no image input | no |
| `ChatConsole` (2050) | Rich Console adapter routing through `_cprint` | PARTIAL | JROS uses a plain Rich `Console` (`app.console`); fine while REPL is single-threaded | improve — needed if concurrent input is ported |
| `_build_compact_banner` (2119) | width-aware compact banner | PARTIAL | `banner.py` has fixed `JAEGER_ASCII` + `TAGLINE`; `status.boot_panel` is the chrome — no narrow-terminal fallback | improve — add a compact banner for <80-col terminals |
| `_looks_like_slash_command` (2167) | distinguish a slash command from a pasted path | PARTIAL | `slash_commands.is_slash` is just `startswith("/")` — would misfire on a pasted `/Users/...` path | improve — adopt the "no second slash in first word" test |
| `_get_plugin_cmd_handler_names` (2198) | plugin-registered command names | SKIP | hermes plugin command system | no |
| `_parse_skills_argument` (2207) | normalize a `--skills` CLI flag | SKIP | hermes skill-flag plumbing | no |
| `save_config_value` (2231) | atomic dot-path write into config.yaml | HAVE | JROS persists via `core.schemas.dump_yaml` (e.g. `app._persist_voice_config`, `slash_commands._model_use`) | no |

---

## 2. HermesCLI — construction & status bar (2278–3185)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `HermesCLI.__init__` (2286) | build console, load display/streaming/busy config, init stream state | HAVE | `JaegerTUI.__init__` (app.py:163) — console, instance dir, model, session id, status-bar flag, context counters | no |
| `_invalidate` (2650) | throttled prompt_toolkit repaint | SKIP | JROS TUI is not a live `Application`; Rich prints + a `PromptSession` per turn | no |
| `_force_full_redraw` (2659) | clean full-screen repaint (Ctrl+L / `/redraw`) | SKIP | scrollback-drift recovery; not applicable to JROS's print model | no |
| `_clear_prompt_toolkit_screen` (2684) | clear terminal + reset renderer state | SKIP | full-screen-app plumbing | no |
| `_recover_after_resize` (2705) | reset renderer after SIGWINCH | SKIP | full-screen-app plumbing | no |
| `_schedule_resize_recovery` (2729) | debounce resize redraws | SKIP | full-screen-app plumbing | no |
| `_status_bar_context_style` (2774) | pick context-meter color from % used | PARTIAL | `status.status_bar` draws a context bar but with a fixed green style, no warn/critical tiers | improve — color the meter by % when ported |
| `_compression_count_style` (2785) | style class for compression pressure | SKIP | JROS has no context compression | no |
| `_build_context_bar` (2794) | render the `[███░░░]` context bar | HAVE | `status.status_bar` builds the same `█`/`░` bar | no |
| `_format_prompt_elapsed` (2800) | format per-prompt elapsed time (`⏱ 1m 5s`) | PARTIAL | `app.run_turn` measures elapsed and `status_bar` shows `elapsed_s`, but no live-ticking timer | improve — fine as-is for between-turns |
| `_get_status_bar_snapshot` (2837) | gather model/context/token/compression counters | PARTIAL | `app.render_status_bar` / `_bottom_toolbar` gather model + context + uptime + mic; no token/cost/compression counts | improve — real context-token tracking is the big gap (see Top Gaps) |
| `_status_bar_display_width` (2899) | terminal cell width of status text | MISSING | JROS status bar is a plain `Text`, never trimmed | no — Rich handles width |
| `_trim_status_bar_text` (2914) | trim status text to one row | MISSING | n/a | no |
| `_get_tui_terminal_width` (2942) | live prompt_toolkit width | PARTIAL | JROS reads `shutil`/Rich width implicitly | no |
| `_use_minimal_tui_chrome` (2955) | hide chrome on narrow terminals | MISSING | no narrow-terminal adaptation | improve — couples to compact-banner gap |
| `_tui_input_rule_height` (2961) | height of input separator rules | SKIP | full-screen-layout plumbing | no |
| `_agent_spacer_height` (2969) | spacer height while agent runs | SKIP | full-screen-layout plumbing | no |
| `_spinner_widget_height` (2975) | height of the spinner line | SKIP | full-screen-layout plumbing | no |
| `_render_spinner_text` (2989) | live spinner text + elapsed timer | PARTIAL | `app._run_text_turn` uses a Rich `Live` "ruminating…" spinner; no tool-name/elapsed in it | improve — show current tool + elapsed in the spinner |
| `_voice_record_key_label` (3008) | formatted push-to-talk key label | SKIP | JROS voice is always-on STT, not push-to-talk | no |
| `set_voice_record_key_cache` (3031) | cache the PTT key label | SKIP | always-on voice, no PTT key | no |
| `_get_voice_status_fragments` (3043) | voice status-bar fragments (REC/STT/idle) | PARTIAL | `status.status_bar` shows `mic on/off`; `voice_status_text` for `/voice` — no REC/transcribing live state | improve — surface live mic state |
| `_build_status_bar_text` (3062) | one-line status string for the footer | HAVE | `app._bottom_toolbar` (app.py:853) builds the prompt_toolkit bottom toolbar | no |
| `_get_status_bar_fragments` (3102) | styled status-bar fragments | HAVE | `status.status_bar` returns a styled Rich `Text`; `_bottom_toolbar` returns a plain string | no |
| `_normalize_model_for_provider` (3185) | normalize provider-specific model IDs | SKIP | OpenRouter/Codex/Copilot model-ID plumbing | no |

---

## 3. HermesCLI — streaming display & reasoning (3288–3848)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_on_thinking` (3288) | agent thinking-start/stop → update spinner | PARTIAL | JROS shows a static "ruminating…" spinner; no thinking-text updates | improve — feed live thinking/tool text into the spinner |
| `_current_reasoning_callback` (3298) | pick the active reasoning display callback | MISSING | JROS has no reasoning-display toggle | no — JROS strips drift markup instead |
| `_emit_reasoning_preview` (3306) | render a buffered `[thinking]` block | MISSING | no inline thinking display | improve — a `thinking_panel` exists (status.py:174) but is unused |
| `_flush_reasoning_preview` (3341) | flush buffered reasoning at natural boundaries | MISSING | no reasoning buffering | no |
| `_format_submitted_user_message_preview` (3390) | multi-line user-message preview (head/tail) | PARTIAL | `app._render_turn_header` prints the whole user line on a `●` bullet, no head/tail collapse | improve — collapse long pasted prompts |
| `_expand_paste_references` (3426) | expand `[Pasted text #N → file]` placeholders | SKIP | paste-collapse plumbing | no |
| `_print_user_message_preview` (3445) | print the `────` + `●` turn header | HAVE | `app._render_turn_header` (app.py:391) — identical `─×48` + glyph bullet | no |
| `_stream_reasoning_delta` (3454) | stream reasoning tokens into a dim box | MISSING | JROS does not stream tokens | no — local model returns whole reply |
| `_close_reasoning_box` (3490) | close the live reasoning box | MISSING | no streaming | no |
| `_stream_delta` (3508) | line-buffered token streaming + tag suppression | MISSING | JROS renders the whole reply at once in a panel | improve — token streaming would feel faster (see Top Gaps) |
| `_emit_stream_text` (3648) | emit filtered streamed text + table re-align | MISSING | no streaming | improve — couples to streaming gap |
| `_flush_stream` (3743) | flush remaining stream buffer, close box | MISSING | no streaming | no |
| `_reset_stream_state` (3793) | reset streaming state per turn | MISSING | no streaming | no |
| `_slow_command_status` (3809) | user-facing status text for slow slash commands | PARTIAL | JROS uses `console.status(...)` per slow command ad hoc (e.g. `/download`, `/instance`) | no — adequate |
| `_command_spinner_frame` (3830) | spinner frame for slow slash commands | HAVE | JROS uses Rich `console.status(spinner="dots")` | no |
| `_busy_command` (3835) | ctx-mgr exposing a busy state during a slash command | PARTIAL | JROS wraps slow commands in `console.status(...)`; no shared busy flag | no — adequate |

---

## 4. HermesCLI — agent init, credentials, banner & session (3849–4592)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_open_external_editor` (3849) | open the input buffer in `$EDITOR` (Ctrl+G) | MISSING | no external-editor handoff | improve — handy for long prompts; low priority |
| `_ensure_runtime_credentials` (3882) | re-resolve provider creds (key rotation, fallback) | SKIP | OpenAI-provider credential plumbing; JROS is local llama-cpp or a fixed external model | no |
| `_resolve_turn_agent_config` (4024) | build per-turn model/runtime config (`/fast`) | SKIP | provider/fast-mode plumbing | no |
| `_init_agent` (4068) | build the `AIAgent`, restore resumed history | HAVE | `app._ensure_agent` (app.py:220) → `main.boot_for_tui`; lazy, cached, eager-booted by `_boot_eager` | no |
| `_show_security_advisories` (4235) | startup supply-chain advisory banner | SKIP | hermes security-advisory feed | no |
| `show_banner` (4260) | clear screen + render welcome banner + tool list | HAVE | `app.render_boot` (app.py:195) → `JAEGER_ASCII` + `TAGLINE` + `status.boot_panel` (tools-by-category) | no |
| `_preload_resumed_session` (4340) | load a resumed session's history early | SKIP | session SQLite DB / resume — JROS has no session DB | no |
| `_display_resumed_history` (4417) | render a compact recap of prior messages | SKIP | session resume | no |
| `_render_resume_history_panel_lines` (4577) | render resume panel for resize replay | SKIP | session resume + output-history | no |
| `_try_attach_clipboard_image` (4594) | save clipboard image + attach for next prompt | MISSING | no image attachment | no — local agent |

---

## 5. HermesCLI — checkpoints, snapshots, copy/image, status (4613–5199)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_handle_rollback_command` (4613) | `/rollback` — list/diff/restore filesystem checkpoints | SKIP | no checkpoint manager | no |
| `_resolve_checkpoint_ref` (4707) | resolve a checkpoint number/hash | SKIP | checkpoints | no |
| `_handle_snapshot_command` (4720) | `/snapshot` — Hermes-config state snapshots | PARTIAL | `slash_commands._factoryreset` resets state; no snapshot/restore — but JROS has `/board`, `/deepthink` queues persisted to disk | no — different lifecycle model |
| `_handle_stop_command` (4807) | `/stop` — kill all background processes | HAVE | `slash_commands._stop` (slash_commands.py:1039) — lists + stops every bg process | no |
| `_handle_agents_command` (4826) | `/agents` — show bg processes + agent status | PARTIAL | `/stop` lists bg procs; no read-only `/agents` view; `delegate_task` exists | improve — small read-only `/agents` view is cheap |
| `_handle_paste_command` (4846) | `/paste` — check clipboard for an image | MISSING | no image attachment | no |
| `_write_osc52_clipboard` (4871) | copy text to clipboard via OSC 52 | SKIP | OSC52 niche | no |
| `_recover_terminal_input_modes` (4888) | reset terminal modes after leaked mouse reports | SKIP | terminal-quirk hardening | no |
| `_handle_copy_command` (4919) | `/copy [n]` — copy assistant output to clipboard | MISSING | no `/copy`; `/save` writes the whole transcript to a file | improve — `/copy` of the last reply is a nice QoL win |
| `_handle_image_command` (4957) | `/image <path>` — attach a local image | MISSING | no image attachment | no |
| `_preprocess_images_with_vision` (4981) | pre-analyze images via the vision model | MISSING | JROS has a `vision_analyze` tool but no CLI image-attach path | no — agent can call the tool itself |
| `_show_tool_availability_warnings` (5047) | warn about tools disabled by missing API keys | PARTIAL | `/plugins` shows install/credential status; no startup warning | improve — a startup line for unavailable tools |
| `_show_status` (5069) | compact startup status line (model · tools · provider) | HAVE | `status.boot_panel` shows model + tools-by-category at boot | no |
| `_show_session_status` (5109) | `/status` — full session info panel | HAVE | `slash_commands._status` (slash_commands.py:1001) — model, instance, session, uptime, context, mic | no |
| `_fast_command_available` (5162) | whether the model supports fast mode | SKIP | provider fast-mode plumbing | no |
| `_command_available` (5171) | gate a slash command by availability | PARTIAL | JROS `/help` always lists all commands | no — small registry, fine |
| `show_help` (5176) | `/help` — categorized command menu | HAVE | `slash_commands._help` (slash_commands.py:75) — categorized boxed menu via `_HELP_CATEGORIES` | no |
| `show_tools` (5215) | `/tools` — tools grouped by toolset | HAVE | `slash_commands._tools` → `status.TOOL_GROUPS` / `_format_tool_group` | no |
| `_handle_tools_command` (5257) | `/tools list|disable|enable` — toggle toolsets | PARTIAL | `/tools` lists only; no enable/disable; JROS has `load_toolset` tool + `/skills` | improve — `/tools enable/disable` would be useful |
| `show_toolsets` (5336) | `/toolsets` — list toolsets with enabled markers | PARTIAL | `/tools` shows tool groups; `/skills` lists skills | no — overlaps existing commands |
| `_handle_profile_command` (5367) | `/profile` — show active profile + home dir | PARTIAL | `/instance` shows the active instance dir | no — instances are JROS's "profiles" |
| `show_config` (5380) | `/config` — show model/terminal/agent/session config | MISSING | no `/config` view | improve — a read-only config dump is cheap |
| `_list_recent_sessions` (5430) | list recent CLI sessions | SKIP | session SQLite DB | no |
| `_show_recent_sessions` (5444) | render recent sessions inline | SKIP | session SQLite DB | no |
| `show_history` (5473) | `/history` — show conversation history | PARTIAL | `/save` exports the transcript; no inline `/history` view | improve — inline `/history` from the session buffer is cheap |

---

## 6. HermesCLI — session lifecycle (5540–6149)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_notify_session_boundary` (5540) | fire session-boundary plugin hooks | SKIP | plugin hook system | no |
| `new_session` (5556) | `/new` — fresh session id + cleared agent state | PARTIAL | `slash_commands._reset` is an explicit "future feature" placeholder; `/reboot` reboots the whole pipeline | improve — a real in-process session reset (see Top Gaps) |
| `_handle_handoff_command` (5657) | `/handoff <platform>` — transfer session to a gateway | SKIP | gateway/messaging handoff | no |
| `_handle_resume_command` (5807) | `/resume <id>` — switch to a prior session | SKIP | session SQLite DB | no |
| `_handle_branch_command` (5920) | `/branch [name]` — fork the current session | SKIP | session SQLite DB | no |
| `save_conversation` (6054) | `/save` — export conversation to JSON | HAVE | `slash_commands._save` (slash_commands.py:1072) — exports the transcript to a markdown file under `<instance>/logs/` | no |
| `retry_last` (6089) | `/retry` — re-send the last user message | MISSING | no `/retry`; would need session-history mutation | improve — useful, needs history-edit support |
| `undo_last` (6118) | `/undo` — drop the last user/assistant exchange | MISSING | no `/undo` | improve — pairs with a real session-reset |

---

## 7. HermesCLI — pickers, model switch, prompts (6150–6877)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_run_curses_picker` (6150) | run a curses single-select picker | SKIP | curses pickers — JROS uses Rich + prompt_toolkit only | no |
| `_prompt_text_input` (6180) | thread-aware free-text input prompt | PARTIAL | JROS uses `console.input(...)` directly (e.g. `_TuiConfirmationProvider`, `/goal`) — REPL is single-threaded so no thread-aware guard needed | no |
| `_prompt_text_input_modal` (6224) | prompt_toolkit-native modal text input | SKIP | full-screen-app modal | no |
| `_submit_slash_confirm_response` (6289) | submit a `/new`-style confirm response | SKIP | full-screen-app modal | no |
| `_normalize_slash_confirm_choice` (6298) | normalize 1/2/3/once/always/cancel | SKIP | full-screen-app modal | no |
| `_get_slash_confirm_display_fragments` (6332) | render the destructive-confirm panel | SKIP | full-screen-app modal | no |
| `_open_model_picker` (6412) | open the prompt_toolkit `/model` picker modal | PARTIAL | `slash_commands._model` lists every model (JROS/Ollama/LM Studio) as text + `/model use ...` to switch — no interactive picker | improve — text-list works; an arrow-key picker is polish |
| `_close_model_picker` (6427) | close the model picker | SKIP | model-picker modal | no |
| `_compute_model_picker_viewport` (6433) | scroll math for the model picker | SKIP | model-picker modal | no |
| `_apply_model_switch_result` (6460) | apply a model switch (state + agent swap) | HAVE | `slash_commands._model_use` writes `external_model` config + `tui.switch_instance` reboots | no |
| `_handle_model_picker_selection` (6544) | handle a model-picker selection | SKIP | model-picker modal | no |
| `_handle_model_switch` (6607) | `/model` — show/switch model | HAVE | `slash_commands._model` + `_model_use` (slash_commands.py:247) — show all, switch local/ollama/lmstudio | no |
| `_handle_codex_runtime` (6781) | `/codex-runtime` — toggle the Codex app-server | SKIP | OpenAI Codex runtime | no |
| `_should_handle_model_command_inline` (6821) | route `/model` onto the UI thread | SKIP | full-screen-app threading | no |
| `_should_handle_steer_command_inline` (6833) | route `/steer` inline while the agent runs | MISSING | no `/steer`; no concurrent-input architecture | improve — part of the steer/busy-mode gap (see Top Gaps) |
| `_output_console` (6857) | pick a prompt_toolkit-safe console when TUI is live | PARTIAL | JROS uses one `Console` everywhere — fine while single-threaded | no |
| `_console_print` (6863) | print through the active console | HAVE | `app.console.print` used throughout | no |
| `_resolve_personality_prompt` (6868) | string/dict personality value → prompt string | PARTIAL | JROS persona lives in the instance's `identity.yaml` (soul/role), not a `/personality` overlay | no — JROS instances are per-personality |

---

## 8. HermesCLI — cron / curator / kanban / skills / goal / process_command (6879–8480)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_handle_gquota_command` (6879) | `/gquota` — Gemini Code Assist quota usage | SKIP | Google OAuth quota | no |
| `_handle_personality_command` (6925) | `/personality` — set a predefined personality | PARTIAL | JROS personality = the booted instance's `identity.yaml`; `/instance <name>` switches it | no — instances cover this |
| `_handle_cron_command` (6970) | `/cron` — manage scheduled tasks | PARTIAL | JROS has `schedule_prompt`/`list_schedules`/`cancel_schedule` *tools* and a cron runner; no `/cron` slash command | improve — a `/cron` (or `/schedules`) view would help |
| `_handle_curator_command` (7215) | `/curator` — skill-maintenance pass | PARTIAL | JROS has Deep Think + `reflection.py` for skill maintenance; no `/curator` | no — Deep Think is the JROS analogue |
| `_handle_kanban_command` (7237) | `/kanban` — kanban board CLI | HAVE | `slash_commands._board` (slash_commands.py:791) — full show/add/approve/done/block/move board | no |
| `_handle_skills_command` (7258) | `/skills` — skills hub (search/browse/install) | PARTIAL | `slash_commands._skills` lists loaded skills; install/search is the `skill`/`package_skill`/`benchmark_skill` tools + `marketplace_spec` | improve — a `/skills install` from a marketplace would help |
| `_show_gateway_status` (7263) | `/platforms` — messaging-platform status | PARTIAL | `slash_commands._plugins` lists bundled plugins (discord/telegram/...) with setup status | no — `/plugins` covers it |
| `process_command` (7320) | the slash-command dispatcher (giant if/elif) | HAVE | `slash_commands.dispatch` (slash_commands.py:1167) + `REGISTRY` table — cleaner registry than hermes's if/elif | no |
| `_handle_background_command` (7770) | `/background <prompt>` — run a prompt in a bg session | PARTIAL | JROS has `start_background`/`check_background` *tools* + `/stop`; no `/background` slash command spawning a side agent | improve — a `/background` side-turn is a real feature gap |
| `_try_launch_chrome_debug` (7923) | launch Chrome with remote debugging | SKIP | browser CDP plumbing | no |
| `_handle_browser_command` (7933) | `/browser connect/disconnect/status` — live Chrome via CDP | SKIP | browser CDP; JROS has its own `browser` tool | no |
| `_get_goal_manager` (8151) | build/cache the per-session `GoalManager` | HAVE | `main.get_goal`/`set_goal`/`clear_goal` (main.py:414+) — process-global goal state | no |
| `_handle_goal_command` (8184) | `/goal` set/status/pause/resume/clear | HAVE | `slash_commands._goal` (slash_commands.py:489) — clarify → disposition (start/board/deepthink) → set; richer than hermes | no |
| `_handle_subgoal_command` (8250) | `/subgoal` add/remove/clear criteria | MISSING | no subgoals; JROS goals are a single condition | improve — subgoal criteria would refine the goal loop |
| `_maybe_continue_goal_after_turn` (8325) | after-turn goal judge + re-queue | HAVE | `app._post_turn_goal_check` (app.py:663) + `main.evaluate_goal` — runs the evaluator after each turn, re-fires the loop | no |
| `_handle_skin_command` (8441) | `/skin` — change the display skin | SKIP | skin engine | no |
| `_handle_footer_command` (8482) | `/footer` — toggle the runtime footer | PARTIAL | `slash_commands._statusbar` toggles the bottom status bar | no — `/statusbar` covers it |

---

## 9. HermesCLI — toggles, compress, usage, mcp/skills reload (8534–9344)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_toggle_verbose` (8534) | `/verbose` — cycle tool-progress mode | PARTIAL | JROS `show_tool_activity` is a pipeline flag (`main._pipeline`); no `/verbose` toggle | improve — a `/verbose` toggle for tool-activity lines |
| `_toggle_yolo` (8562) | `/yolo` — skip all approval prompts | PARTIAL | JROS permission mode (`confirm`/`allow`) is set at first-boot and persisted; no live `/yolo` toggle | improve — a session `/yolo` (allow-all) toggle is handy |
| `_handle_reasoning_command` (8581) | `/reasoning` — effort level + display toggle | SKIP | reasoning-effort plumbing; JROS strips drift markup | no |
| `_handle_busy_command` (8642) | `/busy` — Enter behavior while agent works (queue/steer/interrupt) | MISSING | no concurrent input — Ctrl-C is the only interrupt | improve — core of the concurrent-input gap (see Top Gaps) |
| `_handle_fast_command` (8684) | `/fast` — toggle fast/priority mode | SKIP | OpenAI priority processing | no |
| `_on_reasoning` (8727) | intermediate reasoning-display callback | MISSING | no reasoning display | no |
| `_manual_compress` (8734) | `/compress [focus]` — manual context compression | MISSING | no context compression in JROS | improve — only if context overflow becomes a problem (8k window) |
| `_handle_debug_command` (8833) | `/debug` — upload a debug report + logs | MISSING | no `/debug` upload | no — JROS keeps logs locally |
| `_show_usage` (8841) | `/usage` — rate limits + token usage + cost | PARTIAL | `main.print_latency` shows per-turn latency when enabled; no session token/cost totals | improve — token accounting (couples to status-bar context gap) |
| `_show_insights` (8959) | `/insights` — usage analytics over session history | SKIP | session SQLite analytics | no |
| `_check_config_mcp_changes` (8995) | watch config.yaml for mcp_servers changes | SKIP | MCP hot-reload | no |
| `_confirm_destructive_slash` (9051) | confirm a destructive slash command (/new etc.) | PARTIAL | JROS `_factoryreset` does a typed `reset` confirmation; no generic destructive-confirm | improve — pairs with a real session-reset |
| `_confirm_and_reload_mcp` (9117) | `/reload-mcp` with confirmation | SKIP | MCP plumbing | no |
| `_reload_mcp` (9184) | reload MCP servers | SKIP | MCP plumbing | no |
| `_reload_skills` (9269) | `/reload-skills` — re-scan the skills dir | PARTIAL | JROS has a `reload_skills` *tool*; no `/reload-skills` slash command (Deep Think reload happens via `switch_model`) | improve — a `/reload-skills` slash command is cheap |
| `_on_tool_gen_start` (9345) | model began generating tool args → status line | PARTIAL | JROS shows tool activity *after* the turn (`_render_answer` tool-activity lines); not live | improve — live tool-call lines (see Top Gaps) |

---

## 10. HermesCLI — tool callbacks & voice (9365–9935)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_on_tool_progress` (9365) | tool lifecycle events → spinner + scrollback lines | PARTIAL | JROS collects `tool_activity` in `main._run_turn` and prints it after the turn; not streamed live | improve — live tool-progress lines (see Top Gaps) |
| `_on_tool_start` (9463) | capture before-state for write tools (inline diff) | MISSING | no inline diff previews | improve — inline write diffs are nice; low priority |
| `_on_tool_complete` (9474) | render an inline diff after a write tool | MISSING | no inline diffs | improve — low priority |
| `_voice_start_recording` (9494) | start mic capture (push-to-talk) | PARTIAL | `voice_session.VoiceController.start` (voice_session.py:118) — always-on VAD-segmented STT, not PTT | no — JROS voice model is different (and arguably better) |
| `_voice_stop_and_transcribe` (9611) | stop recording, transcribe, queue transcript | PARTIAL | `VoiceController.poll` yields committed phrases; `app._read_input` polls mic + stdin together | no — JROS architecture differs |
| `_voice_speak_response_async` (9711) | schedule TTS playback in a thread | HAVE | `VoiceController.speak` (voice_session.py:224) — barge-in-aware TTS | no |
| `_voice_speak_response` (9722) | speak the reply via TTS (strips markdown) | HAVE | `VoiceController.speak` + `core.tools.speak` | no |
| `_handle_voice_command` (9774) | `/voice on/off/tts/status` | HAVE | `slash_commands._voice` (slash_commands.py:966) — `/voice`, on/off, wake/followup/bargein | no |
| `_voice_beeps_enabled` (9797) | whether to play record start/stop beeps | HAVE | `VoiceController.chime` + `ChimePlayer` (wake/follow-up earcons) | no |
| `_enable_voice_mode` (9808) | enable voice mode after checking requirements | HAVE | `app.start_voice` (app.py:500) — builds `VoiceController`, prints a banner | no |
| `_disable_voice_mode` (9868) | disable voice, cancel recording, stop TTS | HAVE | `app.stop_voice` (app.py:541) | no |
| `_toggle_voice_tts` (9900) | toggle TTS output | PARTIAL | JROS TTS is always on with voice; `text_to_speech` tool works regardless | no — JROS voice is always-embodied |
| `_show_voice_status` (9917) | `/voice status` — voice mode status | HAVE | `app.voice_status_text` (app.py:584) — mic/wake/followup/bargein state | no |
| `_clarify_callback` (9936) | clarify-tool callback — interactive Q&A UI | PARTIAL | JROS has a `clarify` tool; `/goal` uses `console.input` for clarifying questions; no full arrow-key clarify panel | improve — a richer clarify prompt would help |

---

## 11. HermesCLI — sudo/approval/secret callbacks (10003–10369)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_sudo_password_callback` (10003) | prompt for a sudo password via the UI | PARTIAL | JROS has a permission/confirmation flow (`_TuiConfirmationProvider`); no dedicated sudo-password capture | no — JROS tier-gating covers risky ops |
| `_approval_callback` (10049) | dangerous-command approval (once/session/always/deny) | HAVE | `_TuiConfirmationProvider.confirm` (app.py:103) — y(es)/N(o)/a(lways) per-skill grant, persisted to `permissions.json` | no |
| `_approval_choices` (10104) | build approval choices for a command | HAVE | `_TuiConfirmationProvider` offers yes/no/always | no |
| `_computer_use_approval_callback` (10111) | adapt approval UI for the computer_use tool | HAVE | same `_TuiConfirmationProvider` gates `computer_use` via tier check | no |
| `_handle_approval_selection` (10132) | process the selected approval choice | HAVE | inline in `_TuiConfirmationProvider.confirm` | no |
| `_get_approval_display_fragments` (10158) | render the approval panel | PARTIAL | JROS prints a `⚠ permission needed` line + `console.input`; no boxed panel | improve — a boxed approval panel is polish |
| `_secret_capture_callback` (10322) | secure secret capture for skill setup | PARTIAL | JROS has `get_credential`/`list_credentials` tools + `setup_plugin`; no masked in-TUI secret capture | improve — masked secret entry for plugin setup |
| `_capture_modal_input_snapshot` (10325) | snapshot the input buffer before a modal | SKIP | full-screen-app modal | no |
| `_restore_modal_input_snapshot` (10339) | restore the input buffer after a modal | SKIP | full-screen-app modal | no |
| `_submit_secret_response` (10352) | submit the captured secret | SKIP | full-screen-app modal | no |
| `_cancel_secret_capture` (10360) | cancel secret capture | SKIP | full-screen-app modal | no |
| `_clear_secret_input_buffer` (10363) | clear the secret input buffer | SKIP | full-screen-app modal | no |

---

## 12. HermesCLI — chat() & exit (10370–11013)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `chat` (10370) | run one turn: agent thread + interrupt monitor + streaming + TTS | PARTIAL | `app.run_turn`/`_run_text_turn`/`_run_voice_turn` (app.py:344) → `main.run_for_voice` → `_run_turn`; Ctrl-C aborts the turn via `begin_turn_cancel_scope`/`request_turn_cancel`; **no concurrent typing while the agent works** | improve — the concurrent-input architecture is the biggest gap (see Top Gaps) |
| `_print_exit_summary` (10970) | print resume hint + session stats on exit | PARTIAL | `app.repl` finally just runs cleanup + prints `bye.`; no session summary | improve — a small exit summary (turns, uptime) is cheap |

---

## 13. HermesCLI — TUI prompt/layout helpers (11013–11198)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `_get_tui_prompt_symbols` (11013) | resolve the prompt symbol from skin/profile | PARTIAL | `ptk_input._PROMPT` is a fixed yellow `›` | no — fixed prompt is fine |
| `_audio_level_bar` (11052) | render a live audio-level bar | MISSING | no audio-level indicator | no — low value |
| `_get_tui_prompt_fragments` (11064) | build prompt fragments for the current state | PARTIAL | `ptk_input.read_prompt` uses a fixed prompt + `bottom_toolbar` | no |
| `_get_tui_prompt_text` (11104) | plain-text prompt for width math | SKIP | full-screen-layout plumbing | no |
| `_build_tui_style_dict` (11108) | build the prompt_toolkit style dict | SKIP | skin/style plumbing | no |
| `_apply_tui_skin_style` (11118) | re-apply skin style live | SKIP | skin engine | no |
| `_get_extra_tui_widgets` (11128) | hook for subclasses to add layout widgets | SKIP | full-screen-layout plumbing | no |
| `_register_extra_tui_keybindings` (11137) | hook for subclasses to add keybindings | SKIP | full-screen-layout plumbing | no |
| `_build_tui_layout_children` (11152) | assemble the root `HSplit` children | SKIP | full-screen-layout plumbing | no |

---

## 14. HermesCLI — run() and main() (11199–13619)

| hermes symbol (line) | what it does | JROS status | JROS location / notes | port? |
|---|---|---|---|---|
| `run` (11199) | the interactive loop — banner, keybindings, layout, `process_loop`/`spinner_loop` threads, `app.run()` | PARTIAL | `app.repl` (app.py:947) is a simple single-threaded read→run-turn→goal-check loop; hermes runs the agent in a thread with a concurrent input loop, busy-input routing, modal panels, full keybinding set | improve — see Top Gaps #1–#3 |
| `run().handle_enter` (11408) | route Enter by UI state (sudo/secret/approval/clarify/model-picker/agent-running) | MISSING | JROS Enter just submits a line to the REPL; modal states use blocking `console.input` | improve — part of the concurrent-input gap |
| `run().process_loop` (13064) | bg thread: pull queued input, dispatch slash/file-drop, run `chat()`, drain bg notifications, goal continuation | PARTIAL | JROS's `app.repl` does the same *sequentially* on the main thread (read → slash dispatch → `run_turn` → `_post_turn_goal_check`); no queue, no concurrency | improve — the concurrent loop is the headline gap |
| `run().spinner_loop` (13044) | bg thread: periodic repaint while a command runs | MISSING | JROS uses Rich `Live`/`console.status` per turn — no separate repaint thread | no — Rich `Live` handles it |
| `run()._signal_handler` (13214) | SIGHUP/SIGTERM → interrupt agent + graceful cleanup | PARTIAL | `app.repl` finally block cleans up; no explicit SIGHUP/SIGTERM handler | improve — a SIGTERM handler for clean shutdown is cheap |
| `main` (13420) | fire-based CLI entry: parse flags, build `HermesCLI`, run | PARTIAL | `interfaces/tui/__main__.main` (`__main__.py:22`) — `--banner-only` + `--instance`; `python -m jaeger_os` is the fuller entry | no — JROS entry split is intentional |

---

## Top gaps, ranked

Ranked by user-visible impact on TUI parity. Each line is a one-line port sketch.

> **Progress (2026-05-21)** — gaps 1–5 are DONE:
> - **1** concurrent input — `app._turn_worker` daemon + always-live prompt.
> - **2** `/steer` — interrupts at the next tool boundary, continues with the
>   guidance (partial work kept in history → full context preserved).
> - **3** `/busy` + `display.busy_input_mode` — interrupt / queue / steer.
> - **4** live tool progress — `_run_via_iter` fires a per-tool callback;
>   the TUI prints `┊ 🔧 tool …` lines + a live toolbar spinner.
> - **5** the bottom toolbar is now hermes-shaped: `✦ model │ 27.8K/262K │
>   [█░░░] 11% │ 4m │ ⏲ 23s` (context gauge is a chars/4 estimate).
> Also: the turn is now framed hermes-style (user message between two rules,
> the answer in a `✦ <name>` rule-labelled box with an indented body), and
> **Ollama Cloud** model selection landed — `/model use ollama-cloud <model>`
> (prompts for the API key, stores it 0600 in the credential store).

1. ~~**Concurrent input while the agent works**~~ — **DONE.** `app.repl` now
   starts a daemon turn worker (`_turn_worker`) draining a `queue.Queue`; the
   main thread stays in the prompt_toolkit input loop. Output scrolls above the
   prompt via `patch_stdout`; the "ruminating" spinner moved into the bottom
   toolbar. Mid-turn permission prompts route through `run_in_terminal`
   (`_run_on_terminal`). 14 tests in `test_concurrent_turns.py`.

2. **`/steer` mid-run injection** (`_handle_busy_command` 8642, steer branch of
   `process_command` 7624, `_should_handle_steer_command_inline` 6833).
   `/steer` and `steer` busy-mode exist but currently run the message as the
   *next* turn. TODO: a `steer_turn()` hook on the JROS turn + a steer-slot
   check in `_run_via_iter` so the running agent loop picks the directive up
   between tool calls.

3. ~~**Busy-input mode (`/busy` — queue / steer / interrupt)**~~ — **DONE.**
   `DisplayConfig.busy_input_mode` + the `/busy` slash command; `_submit_turn`
   routes a mid-turn message by mode.

4. **Live tool-progress display** (`_on_tool_progress` 9365, `_on_tool_gen_start`
   9345, `_render_spinner_text` 2989). JROS only shows `tool_activity` *after*
   the turn. Port sketch: have `_run_turn`/`_run_via_iter` emit a callback per
   tool call so the Rich `Live` spinner shows `▸ <tool> … (3.2s)` live, then
   leave a stacked scrollback line — `status.tool_activity` already renders the
   line, it just needs to be called during the turn.

5. **Real context-token metering in the status bar** (`_get_status_bar_snapshot`
   2837, `_build_context_bar` 2794, `_status_bar_context_style` 2774).
   `status.status_bar` draws a context bar but `_context_tokens` is never
   updated. Port sketch: after each turn read the model's prompt-token count
   (llama-cpp exposes it) into `tui._context_tokens` and color the meter by %.

6. **Token / cost usage view (`/usage`)** (`_show_usage` 8841). Track per-session
   input/output token totals on the pipeline and add a `/usage` command showing
   tokens + per-turn latency (JROS already has `LatencyReport`/`print_latency`).

7. **Streaming token display** (`_stream_delta` 3508, `_emit_stream_text` 3648,
   `_flush_stream` 3743). JROS prints the whole reply at once. Port sketch: use
   pydantic-ai's streaming run + a line-buffered `_emit_stream_text` to print
   the answer into an open Rich panel as tokens arrive — big perceived-latency
   win on a local model.

8. **Real in-process session reset (`/new`)** (`new_session` 5556). `_reset` is
   an explicit placeholder. Port sketch: clear the `_DEFAULT_SESSION_KEY`
   history in `main._SESSION_HISTORIES`, rotate the session id, and reset
   counters — no pipeline reboot needed.

9. **`/background` side-turn** (`_handle_background_command` 7770). JROS has
   `start_background` *tools* but no slash command that spins a second agent
   turn in a separate session. Port sketch: a `/background <prompt>` that calls
   `run_for_voice` on a fresh `session_key` in a daemon thread and prints the
   result panel when done.

10. **`/copy` last reply** (`_handle_copy_command` 4919). Add a `/copy [n]`
    that pushes the n-th assistant reply to the clipboard (pyperclip, or OSC52
    fallback) — small, high-frequency QoL win.

11. **Inline `/history` view** (`show_history` 5473). JROS only has `/save`
    (writes a file). Add a `/history` that renders the recent
    `_get_session_history` turns inline — reuses the same iteration `_save`
    already does.

12. **`/undo` and `/retry`** (`undo_last` 6118, `retry_last` 6089). Once gap 8
    gives history-edit primitives, add `/undo` (drop the last exchange) and
    `/retry` (drop + re-fire the last user message).

13. **Compact banner for narrow terminals** (`_build_compact_banner` 2119,
    `_use_minimal_tui_chrome` 2955). `JAEGER_ASCII` wraps below ~80 columns.
    Add a width check in `app.render_boot` that prints a one-line banner when
    the terminal is narrow.

14. **`/verbose` tool-activity toggle** (`_toggle_verbose` 8534). `show_tool_activity`
    is a pipeline flag with no UI. Add a `/verbose` slash command that flips
    `main._pipeline["show_tool_activity"]` (cycle off/on) at runtime.

15. **Session `/yolo` (allow-all) toggle** (`_toggle_yolo` 8562). Permission
    mode is fixed at boot. Add a `/yolo` that swaps the installed policy to
    `AllowAllProvider` for the rest of the session (and back), reusing
    `_install_confirmations`.

16. **`/config` read-only dump** (`show_config` 5380). Add a `/config` command
    that prints the booted instance's model / voice / permissions / deep-think
    config from the live `_pipeline["config"]`.

17. **`/reload-skills` slash command** (`_reload_skills` 9269). JROS has a
    `reload_skills` *tool* but no slash command; surface it as `/reload-skills`
    so the user can pick up Deep-Think-authored skills without a reboot.

18. **Startup unavailable-tool warnings** (`_show_tool_availability_warnings`
    5047). After `boot_panel`, print a dim line listing tool groups that are
    inert because a credential/dependency is missing — JROS already has the
    data in `core.tools.plugins.list_plugins`.
