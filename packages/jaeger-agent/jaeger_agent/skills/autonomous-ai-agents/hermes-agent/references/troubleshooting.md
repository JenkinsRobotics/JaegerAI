# Hermes Troubleshooting + Windows Quirks + Where to Find Things

Run all commands below through the JROS `terminal` tool.

## Troubleshooting

### Voice not working
1. `stt.enabled: true` in config.yaml
2. `pip install faster-whisper` or set a provider API key
3. Gateway: `/restart`. CLI: exit and relaunch.

### Tool not available
1. `hermes tools` — is the toolset enabled for your platform?
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `hermes doctor` — check config + deps
2. `hermes login` — re-auth OAuth providers
3. Check `.env` has the right key
4. Copilot 403: `gh auth login` tokens do NOT work for the Copilot API — use the
   Copilot OAuth device-code flow via `hermes model` → GitHub Copilot.

### Changes not taking effect
- Tools/skills: `/reset` (new session with updated toolset)
- Config: gateway `/restart`; CLI exit + relaunch
- Code: restart the CLI or gateway process

### Skills not showing
1. `hermes skills list` — verify installed
2. `hermes skills config` — check platform enablement
3. Load explicitly: `/skill name` or `hermes -s name`

### Gateway issues
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```
- Dies on SSH logout → `sudo loginctl enable-linger $USER`
- Dies on WSL2 close → needs `systemd=true` in `/etc/wsl.conf`
- Crash loop → `systemctl --user reset-failed hermes-gateway`

### Platform-specific
- Discord bot silent → enable **Message Content Intent** (Bot → Privileged Gateway Intents)
- Slack bot only in DMs → subscribe to the `message.channels` event

### Auxiliary models failing silently
The `auto` provider can't find a backend. Set `OPENROUTER_API_KEY` or
`GOOGLE_API_KEY`, or configure per task:
```bash
hermes config set auxiliary.vision.provider <provider>
hermes config set auxiliary.vision.model <model>
```

## Windows-Specific Quirks

### Input / keybindings
- **Alt+Enter doesn't insert a newline** — Windows Terminal intercepts it for
  fullscreen. Use **Ctrl+Enter** (delivered as LF/`c-j`; the CLI binds `c-j` to
  newline on win32 in `_bind_prompt_submit_keys`). Ctrl+J also inserts a newline
  (harmless side effect). mintty/git-bash: same, or disable Alt+Fn in Options→Keys.
- Diagnose keystrokes: `python scripts/keystroke_diagnostic.py` (repo root).

### Config / files
- **HTTP 400 "No models provided" on first run** — `config.yaml` saved with a
  UTF-8 BOM. Re-save as UTF-8 without BOM (`hermes config edit` writes clean;
  Notepad is the usual culprit).

### execute_code / sandbox
- **WinError 10106** from the sandbox child — it can't create an `AF_INET`
  socket. Root cause is usually Hermes' env scrubber dropping `SYSTEMROOT` /
  `WINDIR` / `COMSPEC`; Python's `socket` needs `SYSTEMROOT` to find `mswsock.dll`.
  Fixed via `_WINDOWS_ESSENTIAL_ENV_VARS` in `tools/code_execution_tool.py`. If it
  recurs, echo `os.environ` in an execute_code block to confirm `SYSTEMROOT` is set.

### Path / filesystem
- Git may warn `LF will be replaced by CRLF` — cosmetic; `.gitattributes`
  normalizes. Don't let editors auto-convert committed POSIX-newline files.
- Forward slashes work almost everywhere (`C:/Users/...`) — prefer them to avoid
  backslash escaping in bash.

(Windows testing/contributing details are in `references/contributing.md`.)

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Config options | `hermes config edit` |
| Available tools | `hermes tools list` |
| Slash commands | `/help` in session |
| Skills catalog | `hermes skills browse` |
| Provider setup | `hermes model` |
| Platform setup | `hermes gateway setup` |
| MCP servers | `hermes mcp list` |
| Profiles | `hermes profile list` |
| Cron jobs | `hermes cron list` |
| Memory | `hermes memory status` |
| Env variables | `hermes config env-path` |
| CLI commands | `hermes --help` |
| Gateway logs | `~/.hermes/logs/gateway.log` |
| Session files | `~/.hermes/sessions/` or `hermes sessions browse` |
| Source code | `~/.hermes/hermes-agent/` |

Docs hub: https://hermes-agent.nousresearch.com/docs/
