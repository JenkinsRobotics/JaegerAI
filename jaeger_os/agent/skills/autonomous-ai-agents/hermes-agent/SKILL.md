---
name: hermes-agent
description: "Set up, configure, extend, troubleshoot, or contribute to Hermes Agent (the Nous Research terminal/gateway AI agent). Load this when the user wants to install or configure Hermes, change its model/provider/tools/voice, run it on messaging platforms, spawn extra Hermes instances, or fix a Hermes CLI/gateway problem."
version: 2.2.0
platforms: [macos, linux, windows]
requires_tools: [terminal, read_file, write_file, patch, search_files]
metadata:
  jros:
    tags: [hermes, setup, configuration, cli, gateway, multi-agent, development]
    category: autonomous-ai-agents
    related_skills: [native-mcp, himalaya, claude-code, codex]
---

# HERMES AGENT

Hermes Agent is Nous Research's open-source AI agent that runs in the terminal, on
messaging platforms (Telegram, Discord, Slack, WhatsApp, Signal, Email, +more),
and in IDEs. It is provider-agnostic (OpenRouter, Anthropic, OpenAI, DeepSeek,
local models, 15+ others), self-improving through skills, and has persistent
cross-session memory. This skill helps you drive and extend it.

Everything Hermes-side is a CLI command or a config-file edit. You accomplish all
of it with a few JROS tools — you do NOT have Hermes-native tools here.

## TOOLS (call these)

- `terminal(command="hermes ...")` — run every `hermes` CLI command and any
  `tmux`/shell needed to spawn or drive an instance. Use `background=true` for
  long autonomous runs; `pty=true` / tmux for interactive sessions.
- `read_file(path="~/.hermes/config.yaml")` — inspect config; `.env` for keys.
- `patch(...)` / `write_file(...)` — edit config or source files.
- `search_files(...)` — grep the Hermes source under `~/.hermes/hermes-agent/`.
- `read_file("references/<file>.md")` — load the detail you need (below).

## REFERENCES (lazy-load — do NOT guess, read the file)

- `references/cli-and-slash.md` — every `hermes` subcommand + all in-session
  slash commands. Read for any "what's the command for X" question.
- `references/config-providers-toolsets.md` — key paths, `config.yaml` sections,
  20+ providers + their env vars, the full toolset list.
- `references/spawning-and-durable.md` — spawn extra Hermes instances (tmux/PTY,
  multi-agent), delegation, cron, curator, kanban, security toggles, voice/STT/TTS.
- `references/troubleshooting.md` — voice/tool/model/gateway/skill fixes, Windows
  quirks, "where to find things" map.
- `references/contributing.md` — project layout, adding a tool/slash command, the
  agent loop, testing (incl. Windows), commit conventions, key rules.

## QUICK START

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes                                  # interactive chat (default)
hermes chat -q "What is the capital of France?"   # one-shot
hermes setup                            # setup wizard
hermes model                            # change model/provider
hermes doctor                           # check health
```

## SOP — ROUTE BY TASK

1. Identify the task class, then load the matching reference before acting:
   - Install / health / any CLI command → `references/cli-and-slash.md`.
   - Change model, provider, tools, paths, memory → `references/config-providers-toolsets.md`.
   - Run on Telegram/Discord/etc. → gateway section of `references/cli-and-slash.md`.
   - Spawn/coordinate agents, cron, voice, security → `references/spawning-and-durable.md`.
   - Something's broken → `references/troubleshooting.md`.
   - Add/modify a tool, command, or send a PR → `references/contributing.md`.
2. Run the exact commands with `terminal`; edit config/source with `patch`/`write_file`.
3. Apply the golden rule of effect: config + tool/skill changes are read at
   STARTUP. After editing, the user must `/reset` (tools/skills) or restart the
   process (config/code) — `/restart` in gateway, exit+relaunch in CLI.
4. Verify: `terminal(command="hermes doctor")` or `hermes status --all`.

## STATE OFFLOADING

For a multi-step setup or migration (install → configure provider → enable
platforms → verify), `write_file` a short checklist of what's done and what's
left, updating it as you go so nothing is skipped across a long run.

## ERROR HATCH

- A config or tool change "didn't work" → you almost always skipped the restart.
  `/reset` for tools/skills, restart the process for config/code, then re-verify.
- Provider/model errors → `terminal(command="hermes doctor")` first, then
  `hermes login` (OAuth) or check the key in `.env`.
- If the same command fails twice, read `~/.hermes/logs/gateway.log` (gateway) or
  re-run with `-v`, and consult `references/troubleshooting.md`. If still stuck,
  `terminal(command="hermes debug")` uploads a report with shareable links.

## DONE WHEN

The requested Hermes state is achieved AND survives a restart — e.g. `hermes
doctor` is clean, the new model/provider answers, the target platform shows
connected in `hermes gateway status`, or the tests pass for a code change.
