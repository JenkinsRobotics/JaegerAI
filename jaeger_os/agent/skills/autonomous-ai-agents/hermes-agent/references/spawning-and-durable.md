# Spawning Hermes Instances + Durable Systems + Security & Voice

The ONLY JROS tool you call here is `terminal` (to run `hermes ...` and `tmux`).
`delegate_task`, `cronjob`, `kanban_*`, `curator` below are Hermes' OWN in-session
tools/features — documented so you understand the system, not JROS tools you call.

## Spawning Additional Hermes Instances

Run extra Hermes processes as fully independent subprocesses (separate sessions,
tools, environments).

Spawn vs. Hermes' built-in `delegate_task`:

| | `delegate_task` (Hermes-internal) | Spawn a `hermes` process |
|-|-----------------------------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-shot mode
```
terminal(command="hermes chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)
terminal(command="hermes chat -q 'Set up CI/CD for ~/myapp'", background=true)   # long tasks
```

### Interactive PTY mode (via tmux)
Hermes uses prompt_toolkit and needs a real terminal, so drive it with tmux:
```
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'hermes'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-agent coordination
```
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)   # relay context between them
```

### Session resume
```
terminal(command="tmux new-session -d -s resumed 'hermes --continue'", timeout=10)
terminal(command="tmux new-session -d -s resumed 'hermes --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Tips
- Prefer Hermes' `delegate_task` for quick subtasks — less overhead than a full process.
- Use `-w` (worktree) when spawned agents edit code — avoids git conflicts.
- Set generous timeouts for one-shot mode (complex tasks: 5–10 min).
- Use `hermes chat -q` for fire-and-forget; tmux for interactive (raw PTY has \r vs \n issues).
- For scheduled work, use a cron job, not a spawned process.

## Durable & Background Systems (Hermes-internal)

Full developer notes live in the Hermes repo `AGENTS.md` and `website/docs/`.

- **Delegation (`delegate_task`)** — synchronous subagent spawn; parent waits for
  the child's summary. Single `delegate_task(goal, context, toolsets)` or batch
  `delegate_task(tasks=[...])` (parallel, capped by
  `delegation.max_concurrent_children`, default 3). Roles: `leaf` (default) vs
  `orchestrator`. NOT durable — child dies if parent is interrupted.
- **Cron** — durable scheduler. Drive via the `cronjob` tool, `hermes cron` CLI, or
  `/cron`. Schedules: duration (`"30m"`), "every" phrase, 5-field cron, ISO
  timestamp. Per-job knobs: `skills`, model/provider override, `script`,
  `context_from` chaining, `workdir`, multi-platform delivery. 3-minute hard
  interrupt per run; `.tick.lock` prevents duplicate ticks.
- **Curator** — background lifecycle for agent-created skills (`created_by:
  "agent"` only; bundled/hub skills off-limits). Marks idle skills stale, archives
  them (NEVER deletes), keeps a tar.gz backup. CLI `hermes curator <verb>` / slash
  `/curator`. Telemetry sidecar `~/.hermes/skills/.usage.json`.
- **Kanban** — durable SQLite board for multi-profile/multi-worker collaboration.
  Users drive via `hermes kanban <verb>`; dispatcher-spawned workers get a focused
  `kanban_*` toolset gated by `HERMES_KANBAN_TASK`. Board is the hard isolation
  boundary; tenant is a soft namespace.

## Security & Privacy Toggles

Most need a fresh session (`/reset` or a new `hermes` launch) — they're read once
at startup.

- **Secret redaction in tool output** — OFF by default.
  `hermes config set security.redact_secrets true` (restart required; snapshotted
  at import — an env-var flip mid-session won't take). Disable with `false`.
- **PII redaction in gateway messages** — separate toggle; hashes user IDs, strips
  phone numbers. `hermes config set privacy.redact_pii true|false` (default false).
- **Command approval prompts** — `approvals.mode`: `manual` (default, prompts on
  destructive commands), `smart` (aux LLM auto-approves low-risk), `off` (= `--yolo`).
  `hermes config set approvals.mode smart`. Per-invocation bypass: `hermes --yolo`
  or `export HERMES_YOLO_MODE=1`. YOLO does NOT disable secret redaction.
- **Shell-hook allowlist** — `~/.hermes/shell-hooks-allowlist.json`, prompted the
  first time a hook fires.
- **Disable web/browser/image-gen tools** — `hermes tools`, toggle per platform,
  takes effect on `/reset`.

## Voice & Transcription

STT (voice → text) — messaging voice notes auto-transcribe. Provider priority:
1. Local faster-whisper (free) — `pip install faster-whisper`
2. Groq Whisper (free tier) — `GROQ_API_KEY`
3. OpenAI Whisper (paid) — `VOICE_TOOLS_OPENAI_KEY`
4. Mistral Voxtral — `MISTRAL_API_KEY`
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local: { model: base } # tiny, base, small, medium, large-v3
```

TTS (text → voice):

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | Paid |
| NeuTTS (local) | None (`pip install neutts[all]` + `espeak-ng`) | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice),
`/voice off`.
