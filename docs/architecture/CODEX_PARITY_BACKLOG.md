# Codex parity backlog

Everything identified in the installed Codex (extension `openai.chatgpt-26.908.40401`,
`~/.codex`) that Jaeger can port, with its evidence level and status. Working list:
update the Status column as items land. Jaeger's Gateway remains the single execution
owner; nothing here adds a second agent loop.

**Evidence:** *verified* = read from Codex's binary, config, or 378 real session logs.
*names* = UI component file names seen in the extension bundle; behavior not yet
inspected (record it with the running Codex panel before porting).

**Licensing:** the extension's license is a pointer to OpenAI's terms of use. Do not
copy its code or assets. Port behavior and measured timings only, as original Jaeger code.

## A. Tools (verified)

| # | Codex tool | Jaeger today | Port | Status |
|---|---|---|---|---|
| A1 | `exec_command` + `write_stdin` + `wait` (persistent PTY) | `terminal`, `start_background` | Persistent PTY sessions | todo |
| A2 | `exec` (code-mode host) | `execute_code`, `execute_with_tools` | Verify parity | todo |
| A3 | `apply_patch` (freeform multi-file) | `write_file` + find/replace `patch` | **Dropped by decision (2026-09-24)**: Jaeger edits files with plain tools; no special patch format | dropped |
| A4 | `update_plan` | `todo` | Plan steps as a streamed event | **done** (stateless tool → `turn.plan` event → IDE checklist) |
| A5 | `view_image` | `vision_analyze` | Real image into model context | todo |
| A6 | `request_user_input` | `clarify` | Answer in the IDE in the same turn | todo |
| A7 | `collaboration.*` (spawn, send, follow-up, wait, list) | `delegate_task`, durable child tasks | Send/follow-up/wait/list | todo |
| A8 | `tool_search` | `list_tools`, `load_tools` | Verify | todo |
| A9 | `web.run` | `web_search`, `web_extract` | Verify without paid key | todo |
| A10 | `clock.sleep` | none | Small wait tool | **done** (`wait`, capped, cancellable) |
| A11 | MCP tools and apps | MCP registration | Load configured servers; surface login-needed | todo |

## B. Slash commands (verified)

- Session: /new /resume /fork /rename /side /copy /export /clear /archive /cd /pwd
- Model/settings: /model /permissions /personality /fast /experimental /keymap /statusline
- Code: /review /diff /mention /init /worktree
- Context/planning: /compact /plan /goal
- Extensions: /skills /mcp /apps /plugins /hooks /memory
- Monitoring: /status /agent /ps /stop /usage
- Not portable: /logout /feedback, terminal-cosmetic commands

A command ships only when its Gateway route exists (no fake controls).

Status: **done** for /new /resume /rename /stop /copy /export /model /diff /status /skills
/agent(/ps) (IDE composer menu; `media/slash-commands.js`, `commands.js`). Unit-tested;
not yet exercised in the live IDE. **todo** (need a Gateway route first): /fork /compact
/plan /goal /init /review /mcp /permissions /memory /hooks /worktree /side /personality.

## C. Subsystems (verified)

| # | Subsystem | Port | Status |
|---|---|---|---|
| C1 | Hooks: PreToolUse PostToolUse UserPromptSubmit SessionStart SessionEnd Stop SubagentStop PreCompact | Extend PolicyKernel-owned hook points | todo |
| C2 | Rules file (`rules/default.rules`, command-approval policy) | Rules layer feeding approvals | todo |
| C3 | Goals (long-running goal tracking) | Gateway goal route + /goal | todo |
| C4 | Follow-up queue (messages queued behind the current turn) | Gateway queue | todo |
| C5 | Memories | Already owned by Jaeger memory; verify surface | todo |
| C6 | Auto-review approval nudges | Approval flow | todo |
| C7 | Import setup/chats from another agent | Import flow | todo |

## D. UI components (names only)

Composer overlay, floating composer, @-mention list, slash menu with review submenu,
project selector, run-location dropdown, utility/action bars, starter prompts.
Turn entries, "worked for" disclosure, tool-activity label/disclosure, reasoning rows,
conversation blocks, math blocks. Command-execution rows, background-terminal tab and
terminal panel, MCP tool items. Agent activity units, agent menu, subagent panel/rows.
Plan side panel, editable plan tab, plan summary, todo list, goal view. Diff, file diff,
diff comment cards, view-mode toggle, git review, branch picker, commit/PR flows.
Permissions dropdown, mode picker, denied dialog. Model picker, fast-mode control,
keyboard-shortcuts editor, hooks/memory settings. Skills page/grid, plugin picker, MCP
settings/app view. File/docx/image previews, charts, mermaid, math, annotation mode.
Command menu, home suggestions, sidebar tasks/history, hotkey window, notifications.
Voice overlay/waveform. Status: todo (inspect behavior first).

## E. Motion and tokens

| Item | Status |
|---|---|
| shimmer, chip-enter, rise/scale/fade enters, working-dot wave, changed highlight, focus/press feedback, plan/menu/result-card enters | done (`interfaces/ide/media/motion.css`) |
| per-word text arrival, completed-turn curtain, fast-mode tick/particles, popover enters, progress donut/usage-bar fills | todo |
| type/radius/spacing/easing token scales | todo |

## F. Skills

All 177 imported under `packages/jaeger-agent/jaeger_agent/skills/codex/` with
provenance (`dev/scripts/import_codex_skills.py`). Status: done. Re-run the importer
when Codex updates.

## G. Not ported

Account/cloud-bound features: billing, cloud environments and automations, business
workspaces, appgen, Codex-micro, pets, mobile setup (~150 chunks).

## Also landed with this backlog

- One execution path: `JAEGER_LEGACY_PATHS` (`jaeger_ai/contract/legacy_paths.py`) isolates the
  WebUI in-process agent, the `:8791` runner and the Gateway native-MCP-first branch. The
  Gateway is the single turn engine; the WebUI session store is a read-through mirror of it
  (`features/webui/api/gateway_mirror.py`); `PATCH /v1/sessions/{id}` makes titles Gateway-owned.
- `GET /v1/runtime/skills` (skills incl. the 177 imported Codex skills), for `/skills`.
