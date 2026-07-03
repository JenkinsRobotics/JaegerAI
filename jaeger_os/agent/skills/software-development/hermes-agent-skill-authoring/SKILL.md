---
name: hermes-agent-skill-authoring
description: "Author or edit an in-repo JROS SKILL.md to the 8-point standard — frontmatter, tool-coupling, phased SOP. Load this when creating a new skill, rewriting one, or fixing a skill that names tools that don't exist."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [write_file, read_file, patch, append_file, list_skill_dir, search_files, skill, benchmark_skill, record_skill_revision, request_skill_review, skill_note, package_skill]
metadata:
  jros:
    tags: [skills, authoring, skill-md, conventions, meta]
    category: software-development
    related_skills: [writing-plans, requesting-code-review]
---

# AUTHORING JROS SKILLS

A skill is a CHEAT SHEET a small (4B) local agent must be able to follow: knowledge +
exact tool names + a tight SOP. Skills live at
`jaeger_os/agent/skills/<category>/<name>/SKILL.md` and are committed source, not
runtime state. `write_file` writes into the sandboxed `skills/` tree.

## WHEN TO USE
- Creating a new skill, or rewriting/tightening an existing one.
- Fixing a skill that references tools that are not in the JROS registry.
- Splitting an oversized SKILL.md into `references/` and routing to them.
- Don't use for: authoring product code, or editing skills of another agent framework.

## TOOLS (real JROS names — never invent one)
- `list_skill_dir(path="jaeger_os/agent/skills/<category>")` — survey peers.
- `list_skills(action="list")` / `list_skills(action="view", name=…)` — discover + read skills.
- `read_file(path=…)` — read 2-3 peer SKILL.md files to match tone.
- `search_files(query=…)` — find how a tool is actually used across skills.
- `write_file(path=…, content=…)` — create/rewrite SKILL.md or a `references/…` file.
- `patch(path=…, old=…, new=…)` — small surgical edits; `append_file` to extend a file.
- `benchmark_skill(name=…)` — run the skill's `tests/benchmark.py` and track the score delta (only if it ships one).
- `record_skill_revision(name=…)` — log the change AFTER you keep a new version.
- `request_skill_review(name=…)` / `skill_note(name=…, note=…)` — queue a Deep Think improvement pass / journal a post-use summary.
- `package_skill(name=…)` — bundle a finished skill into a shareable `.zip`.

There is no `skill_manage` tool in JROS. Create and edit skills with `write_file` /
`patch`; there is no separate "create" verb.

## THE 8-POINT STANDARD (what makes a good skill)
1. FRONTMATTER — exact schema (below). Registry parses the leading `---…\n---` YAML block; `metadata.jros.tags` is the standard namespace.
2. HEADERS — UPPERCASE section headers, no nested markdown tables, minimal `**bold**`. Plain and scannable for a 4B model.
3. TOOLS BLOCK — list the exact tool calls with NAMED args, e.g. `web_extract(url=…)`. Every tool named must exist in the JROS registry (verify with `describe_tool` / `list_tools`). If a capability has no tool, tell the agent to use `execute_code` / `terminal` / `web_search` — do NOT fabricate a tool.
4. SOP — phased and numbered, tight enough that a small model can't get lost.
5. STATE OFFLOADING — if the task has >3 steps/outputs, mandate `append_file` / `write_file` / `todo` / `kanban` instead of holding state in context.
6. ERROR HATCH — the one common failure and its escape ("if X fails twice, do Y").
7. DONE WHEN — the concrete deliverable, so the agent knows when to stop.
8. LAZY LOAD — heavy templates/tables/examples go in `references/…` and are pulled with `read_file("references/…")`, not inlined. Target 50-130 lines for SKILL.md.

## FRONTMATTER SCHEMA
```yaml
---
name: my-skill-name                # folder name, kebab-case, no cute codenames
description: "One sentence: what it does + the WHEN-to-pick-this trigger."
version: 1.0.0
platforms: [macos, linux, windows] # normalized; drop any the skill can't run on
requires_tools: [real, jros, tool, names]
metadata:
  jros:
    tags: [three, to, six, keywords]
    category: <existing category>
    related_skills: [skills-a-user-might-chain]
---
```
Must start with `---` at byte 0 and close with a `\n---` line; the body after it must be
non-empty. Pick an existing category — run `list_skill_dir(path="jaeger_os/agent/skills")`
and don't invent a top-level category casually.

## SOP
1. SURVEY — `list_skill_dir` the target category; `read_file` 2-3 peers to match structure.
2. VERIFY TOOLS — for every tool the recipe will CALL, confirm it exists via `describe_tool` or `list_tools`. Fix legacy/wrong names before writing.
3. DRAFT — `write_file` the SKILL.md to `skills/<category>/<name>/SKILL.md` against the 8-point standard.
4. OFFLOAD BULK — move heavy tables/appendices/examples into `skills/<category>/<name>/references/<file>.md` with `write_file`; link them with `read_file("references/…")`. Preserve any shipped `scripts/`/`templates/` — reference, don't inline.
5. BENCHMARK — if the skill ships `tests/benchmark.py`, run `benchmark_skill(name=…)` and keep the change only if the score holds or improves.
6. LOG — `record_skill_revision(name=…)` after you keep the new version; add a `skill_note` if there's a lesson. Optionally `request_skill_review` to queue a Deep Think improvement pass.
7. COMMIT — `git add` + commit on the active branch (skills are source). Optionally `package_skill(name=…)` to share.

## STATE OFFLOADING
When rewriting a large skill, don't hold the old body in context — slice it into
`references/` files with `write_file`, then fix tool names in each with `patch`. Track
the rewrite steps with `todo` if it spans several files.

## ERROR HATCH
- A tool name you're unsure about: run `describe_tool(name=…)`. If it errors, the tool
  doesn't exist — reroute to `execute_code` / `terminal` / `web_search`. Never guess.
- The current session won't see a newly-written skill: the loader is cached at session
  start. That's expected — verify in a fresh session or `read_file` the exact path.

## DONE WHEN
SKILL.md is at `skills/<category>/<name>/SKILL.md`, frontmatter validates (starts `---`,
closes `\n---`, has name + description + `metadata.jros`), every named tool exists in the
registry, the body follows the 8-point standard within ~50-130 lines, heavy content is in
`references/`, and the change is committed (and `record_skill_revision` logged).
