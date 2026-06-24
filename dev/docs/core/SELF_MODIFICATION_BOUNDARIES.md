# JROS Self-Modification Boundaries

The agent can write code. This document tells the agent — and any
operator reviewing what the agent did — **which parts of the
filesystem are safe to modify, which need care, and which are
off-limits**. The short version lives in the agent's system prompt so
the policy is in scope every turn; this longer reference is for
post-hoc review.

## Why bother

An agent that edits its own runtime needs the same safety culture a
human engineer needs around a production database: most changes are
fine, some are risky, a few will break the system irrecoverably. The
goal here is to make the boundary **legible** — both to the agent
(via the system-prompt summary) and to the human reviewing the
`<instance>/audit/self_modification.jsonl` log later.

## The four tiers

| Tier | What | Modification policy |
|---|---|---|
| **A — Workspace** | The agent's own scratch space | Edit freely; no audit row |
| **B — Framework extensions** | Built-in skills + plugin packages | Add freely; edit with care; audited |
| **C — Framework core** | The agent loop, adapters, tools | Read first, plan, minimal patches; **always audited** |
| **D — Infrastructure** | Dependencies, install scripts, anything outside the repo | Requires explicit user approval |

### Tier A — Workspace (always safe)

```
<instance>/skills/         the agent's own skills (where file_write lands)
<instance>/memory/         facts.json, episodic.jsonl
<instance>/logs/           latency, audit, episodic outputs
<instance>/credentials/    API keys (encrypted at rest)
benchmark/baseline/        captured benchmark rows
scripts/                   ad-hoc scripts the agent generates
docs/                      documentation the agent writes (this file is C)
```

The `file_write` / `append_file` / `edit_file` / `delete_file` tools
are sandbox-locked to `<instance>/skills/` and physically can't escape
it. Writes here are normal operation, no audit row in the
self-modification log (regular `audit.log` still records them).

### Tier B — Framework extensions (safe to add; careful to modify)

```
src/jaeger_os/skills/      built-in skills shipped with JROS
plugins/                   plugin packages (tts, vision, browser, …)
src/jaeger_os/instance/    base instance templates
```

Adding a NEW skill folder under `src/jaeger_os/skills/<your_skill>/`
is fine. Modifying an existing built-in skill is fine but **gets
audited** — the change might affect other instances on next pull.

### Tier C — Framework core (careful: this is your runtime)

```
src/jaeger_os/agent/       the agent loop, adapters, registry, toolsets
src/jaeger_os/core/        instance machinery, schemas, prompts, tools
src/jaeger_os/main.py      pipeline state + entry points
src/jaeger_os/interfaces/  TUI, voice, REPL drivers
tests/                     the test suite
```

**Editing here changes how the agent itself runs.** Discipline:

1. **Read first.** Use `read_file` on the target before patching — you
   need to understand the surrounding contract.
2. **Plan.** State what you're about to change and why. The audit row
   carries this reason so a reviewer can follow the intent.
3. **Minimal patches.** Prefer `edit_file` (one region) over
   `write_file` (full rewrite). A truncated rewrite of `main.py` is
   catastrophic.
4. **Test immediately.** Run `pytest` after the change. If it goes
   red, revert via `git checkout`.
5. **Every edit is audited.** Path-classified writes here log to
   `<instance>/audit/self_modification.jsonl` automatically.

### Tier D — Infrastructure (requires explicit user approval)

```
pyproject.toml             dependencies, version, console_scripts
setup.sh, install scripts  system bootstrap, venv creation
.venv/                     installed packages
~/.zshrc, ~/.bashrc, etc.  shell config outside the repo
anything outside the repo  full stop
```

Changing these can break the install for everyone. The agent should
ask the user before touching them — explicitly, in chat — and only
proceed when granted. The audit log surfaces the request whether
approved or not.

## Audit log shape

`<instance>/audit/self_modification.jsonl` — one JSON object per line:

```json
{
  "timestamp": "2026-05-24T11:34:02Z",
  "tier": "C",
  "tool": "edit_file",
  "path": "src/jaeger_os/agent/jaeger_agent.py",
  "bytes": 312,
  "reason": "fix length-retry loop missing finish_reason check",
  "tool_call_id": "call_a1b2c3"
}
```

`reason` is the model's stated rationale if it provided one (via a
preceding `<plan>` block or similar). `tier` is computed by the path
classifier in `jaeger_os.core.self_modification_audit`.

## What gets audited where

| Where the write came from | What we log | Where it goes |
|---|---|---|
| `file_write` / `append_file` / `edit_file` / `delete_file` (sandbox tools) | Already sandboxed to Tier A → no extra audit | `logs/audit.log` only |
| `terminal` / `execute_code` / `run_python` / `start_background` | The command + the working directory (best-effort path classification) | `audit/self_modification.jsonl` when the command pattern suggests a write outside `<instance>/skills/` |
| Manual git operations from inside a skill | Not currently tracked | Git history itself is the record |

The audit is **observational, not enforcement** — the sandbox is the
enforcement layer (sandbox tools refuse Tier C-D writes; tier-gated
tools require confirmation). The audit answers "what did the agent
do" after the fact.

## What this is NOT

- Not a security perimeter. A determined model with shell access can
  bypass any in-process audit. The defenses against that are the
  permission tiers (`@requires_tier`), the skills_guard scan, and the
  Three Laws prompt-level layer.
- Not a license. The agent shouldn't read this and feel encouraged to
  edit Tier C "as long as it's audited" — the Three Laws still apply.
- Not a substitute for tests. Every Tier C edit should be followed by
  a test run.

## See also

- [docs/agent_refactor_phase_9.md](agent_refactor_phase_9.md) — the
  last big self-modification (pydantic-ai removal) is recorded here
  for context on what a deliberate Tier C operation looks like.
- `<instance>/audit/self_modification.jsonl` — the live log on the
  running system.
- `src/jaeger_os/core/self_modification_audit.py` — the classifier +
  log writer (Tier C: when you change it, log the change).
