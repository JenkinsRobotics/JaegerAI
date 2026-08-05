# JROS Tooling for the Research Pipeline

How to drive the research-paper pipeline with REAL JROS tools. Every tool below is in
the JROS registry — do not substitute names from other agents. JROS HAS
`delegate_task` (fan out to sub-agents), `clarify` (ask a blocking question),
`schedule_prompt` (periodic/scheduled), and `start_background` (long processes). It has
NO `cronjob`, `send_message`, or `process` tool — use the JROS names above instead.

## Tool map

| Need | JROS tool(s) |
|------|--------------|
| Compile LaTeX, git, launch scripts, ps/tail/ls | `terminal` |
| Background experiments that outlive the turn | `start_background`, `check_background`, `list_background`, `pending_background`, `stop_background` |
| Python: citation verification, stats, aggregation | `execute_code` (or `run_in_venv` for the instance venv) |
| Install a Python dependency | `install_package` / `list_venv_packages` |
| Read / write / edit paper + result files | `read_file`, `write_file`, `patch`, `append_file`, `search_files`, `list_skill_dir` |
| Literature discovery | `web_search`, then `web_extract` on the chosen URLs |
| Persistent cross-session state | `todo` (granular tasks), `memory` (key decisions), `remember` / `recall` |
| Scheduled monitoring / deadline pings | `schedule_prompt`, `list_schedules`, `cancel_schedule` |
| Load a companion recipe | `use_skill(name=...)`, browse with `list_skills(action="view", ...)` |

**Parallel/subagent work:** `delegate_task([...])` hands focused subtasks to fresh
sub-agents (no parent history; shared memory/tools; max 2 concurrent, turns serialize)
— draft sections or run analyses in isolation. For a long crawl/experiment, offload to
`start_background` and poll with `check_background`. Ask blocking questions with the
`clarify` tool (or just ask in your reply).

## Companion skills

Load with `use_skill(name=...)`; browse a skill's files with `list_skills(action="view", name=...)`.

| Skill | Phase | Load |
|-------|-------|------|
| arxiv | 1 — arXiv / Semantic Scholar search + BibTeX | `use_skill(name="arxiv")` |
| subagent-driven-development | 5 — staged section drafting + review | `use_skill(name="subagent-driven-development")` |
| plan | 0 — structured plan before execution | `use_skill(name="plan")` |
| data-science | 4 — interactive analysis + plotting | `use_skill(name="data-science")` |

This skill supersedes `ml-paper-writing` (all its content plus the full
experiment/analysis pipeline and autoreason methodology).

## Common tool patterns

**Experiment monitoring loop:**
```
terminal("ps aux | grep <pattern>")
terminal("tail -30 <logfile>")
terminal("ls results/")
execute_code("aggregate results JSON, compute metrics")
terminal("git add -A && git commit -m '<descriptive message>'")
# then report the results table + next step in your chat reply
```

**Long experiment that must outlive the turn:**
```
start_background(code="<python that runs the sweep and writes results/*.json>")
# later turns:
check_background(id=<id>, lines=40)
pending_background()      # drain anything that finished since last check
```

**Section drafting (sequential — no parallel subagents):** draft Methods, then
Related Work, then Experiments in turn. For each, `read_file` the relevant scripts /
configs / result files first, write with `write_file`, then `patch` for edits. Use
the `subagent-driven-development` skill if you want the staged spec-then-quality review.

**Citation verification** (`execute_code`, never from memory):
```python
from semanticscholar import SemanticScholar
import requests
sch = SemanticScholar()
for paper in sch.search_paper("attention mechanism transformers", limit=5):
    doi = paper.externalIds.get("DOI")
    if doi:
        print(requests.get(f"https://doi.org/{doi}",
                           headers={"Accept": "application/x-bibtex"}).text)
```

## State management

**`memory`** — persist key decisions across sessions (contribution framing, venue,
reviewer feedback):
```
memory(action="add", text="Paper: autoreason. Venue: NeurIPS 2025 (9 pages). "
       "Contribution: structured refinement works when the generation-evaluation gap is wide. "
       "Status: Phase 5 — drafting Methods.")
```

**`todo`** — granular progress: `todo(action="add", ...)`, `todo(action="update", ...)`,
`todo(action="list")`.

**Session startup protocol:**
```
1. todo(action="list")                     # current task list
2. memory(action="read")                   # recall key decisions
3. terminal("git log --oneline -10")       # recent commits
4. terminal("ps aux | grep python")        # running experiments
5. pending_background()                     # anything that finished off-turn
6. terminal("ls results/ | tail -20")      # new results
7. Report status, ask for direction
```

## Scheduled monitoring

Use `schedule_prompt` for periodic experiment checks and deadline pings (there is no
`cronjob`):
```
schedule_prompt(cron="*/30 * * * *", prompt="Check experiment status: ps aux | grep run_experiment; "
  "tail -30 logs/experiment.log; ls results/. If complete: read results, compute scores, "
  "git add -A && git commit -m 'Add results'. Report a results table + next step. "
  "If nothing changed since last check, reply with exactly [SILENT].")
```
The `[SILENT]` convention suppresses a no-op notification: reply with exactly `[SILENT]`
when nothing changed. List/cancel with `list_schedules` / `cancel_schedule`.

## When to ask vs. act

Ask the user directly (in chat) only when genuinely blocked: target venue, contribution
framing when multiple valid framings exist, experiment priority under time pressure,
final submission readiness. Do NOT ask about word choice, section ordering, which
results to highlight, or citation completeness — make the call and flag it in the draft.
