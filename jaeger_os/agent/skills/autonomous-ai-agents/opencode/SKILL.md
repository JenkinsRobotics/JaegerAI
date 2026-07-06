---
name: opencode
description: "Delegate coding work to the OpenCode CLI (implement, refactor, review PRs) driven through JROS terminal + background tools — load this when the user asks to use OpenCode or wants an external coding agent to do a bounded code task."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [terminal, start_background, check_background, pending_background, stop_background]
metadata:
  jros:
    tags: [coding-agent, opencode, autonomous, refactoring, code-review]
    category: autonomous-ai-agents
    related_skills: [claude-code]
---

# OPENCODE CLI

Use [OpenCode](https://opencode.ai) — a provider-agnostic open-source coding agent
— as an autonomous worker. Drive it NON-INTERACTIVELY with `opencode run '...'`;
JROS cannot pilot the live TUI (there is no tool to type into a running session),
so use one-shot runs and continue state with `-c` / `-s`.

## WHEN TO USE
- User explicitly asks to use OpenCode.
- You want an external agent to implement / refactor / review code.
- Long-running or parallel coding tasks in isolated workdirs.

## TOOLS
- `terminal(command="...")` — run bounded `opencode run` tasks + all setup.
- `start_background(code="...")` — launch a long OpenCode run that outlives the turn
  (wrap the shell command in Python `subprocess`).
- `check_background(id=...)` / `pending_background()` — poll progress + finished jobs.
- `stop_background(id=...)` — kill a stuck run.

## SETUP / VERIFY
```
terminal(command="opencode --version")
terminal(command="opencode auth list")   # must show >=1 provider
```
Install if missing: `npm i -g opencode-ai@latest` (or `brew install anomalyco/tap/opencode`).
Auth: `opencode auth login`, or set provider env vars (e.g. OPENROUTER_API_KEY).
PATH check if behavior differs: `terminal(command="which -a opencode")`.

## ONE-SHOT TASKS (default — bounded, non-interactive)
```
terminal(command="cd ~/project && opencode run 'Add retry logic to API calls and update tests'")
```
Attach context files with `-f`:
```
terminal(command="cd ~/project && opencode run 'Review this config for security issues' -f config.yaml")
```
Useful flags: `--model provider/model` (force model), `--thinking` (show reasoning),
`--variant high|max|minimal` (effort), `--format json` (machine-readable),
`--agent build|plan`, `--title <name>`.

## ITERATIVE WORK (continue a session across one-shot runs)
OpenCode prints a session id after each run. Continue it on the next run — no live
TUI needed:
```
terminal(command="cd ~/project && opencode run 'Implement OAuth refresh flow and add tests'")
terminal(command="cd ~/project && opencode run 'Now add error handling for token expiry' -c")   # continue last
terminal(command="cd ~/project && opencode run 'Add tests for the expiry case' -s ses_abc123")   # specific session
```

## LONG / PARALLEL RUNS (background)
Wrap the shell command in Python for `start_background`:
```
start_background(code="import subprocess; subprocess.run(\"cd ~/proj-a && opencode run 'Fix issue #101 and commit'\", shell=True)")
start_background(code="import subprocess; subprocess.run(\"cd ~/proj-b && opencode run 'Add parser regression tests and commit'\", shell=True)")
check_background(id="<id>")      # poll one job's status + tail output
pending_background()             # drain jobs that finished since last check
```
Give each parallel run its OWN workdir — never share a working directory across
concurrent OpenCode runs.

## PR REVIEW
```
terminal(command="cd ~/project && opencode pr 42")
```
Or review an isolated clone:
```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && opencode run 'Review this PR vs main. Report bugs, security risks, test gaps, style issues.'")
```

## COST / SESSIONS
```
terminal(command="opencode session list")
terminal(command="opencode stats")
terminal(command="opencode stats --days 7")
```

## VERIFY IT WORKS (smoke test)
```
terminal(command="opencode run 'Respond with exactly: OPENCODE_SMOKE_OK'")
```
Pass = output contains `OPENCODE_SMOKE_OK` and no provider/model error.

## PITFALLS
- Always run OpenCode non-interactively (`opencode run`). Do NOT try to open the TUI —
  JROS has no tool to type into a live session.
- PATH mismatch can select the wrong binary/model config — pin `$HOME/.opencode/bin/opencode` if so.
- One workdir per concurrent run, or edits collide.
- If a background run looks stuck, `check_background(id=...)` for its log before `stop_background`.

## DONE WHEN
The requested code task ran, and you report concrete outcomes: files changed, test
results, session id (for follow-ups), and remaining risks.
