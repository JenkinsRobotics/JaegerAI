# JROS Skill Authoring Standard — the full 8-point checklist + frontmatter schema

A skill hands a small local model the knowledge, the exact tool names, and the
SOP to do a task it would otherwise fumble. Every SKILL.md meets this bar.

## Frontmatter schema (exact)
```
---
name: <folder-name, kebab-case, accurate — no cute codenames>
description: "<ONE sentence: what it does + the WHEN-to-pick-this trigger. This is
  the single biggest factor in whether the agent SELECTS the skill. Name the tasks
  that should load it, e.g. 'Load this for X / Y / Z'.>"
version: <semver, e.g. 1.0.0 — bump on every kept revision>
platforms: [linux, macos, windows]         # drop any it genuinely can't run on
requires_tools: [<real JROS tool names this recipe CALLS>]   # for integration/hints
metadata:
  jros:
    tags: [<3-6 keywords — feed skill(action="search"); the loader reads jros.tags>]
    category: <the folder's category>
    related_skills: [<skills a user might chain — best-effort>]
---
```
Notes:
- The loader reads `metadata.jros.tags` (then `metadata.hermes.tags`, then top-level
  `tags:`). Prefer the jros namespace for new skills.
- `category` is also derived from the folder path; keep them consistent.
- `requires_tools` documents integration; it does not currently hide the skill.

## The 8 points
1. NAMING — an explicit, accurate name. No vague "helper" titles, no codenames that
   hide the function (a bad example from history: `dogfood` → renamed `web-app-qa`).
2. BOUNDARY (the WHEN) — the 1-sentence trigger lives in the frontmatter
   `description`. Keep it there (surfaced by skill search on demand), NOT stuffed
   into any always-on tool enum — measured: descriptions in the always-visible
   surface REGRESSED accuracy (they bury the signal).
3. STRICT SOP — phased/numbered, plain-terminal formatting (UPPERCASE headers, no
   nested markdown tables, minimal **bold**). Punchy and scannable. A 4B must not
   get lost mid-recipe.
4. TOOL COUPLING (the cheat sheet) — list the EXACT registered tool names the
   recipe calls, inline, with NAMED args. THE #1 RULE. Real failure: a skill said
   `computer_do` while the tool was registered as `_computer_do` → the model
   hallucinated the documented name and the call was rejected. Verify names against
   the registry (`describe_tool`, `list_tools`) or a real bench transcript.
5. STATE OFFLOADING — if a procedure has >3 steps or >3 outputs, MANDATE
   `append_file`/`write_file`/`todo`/`kanban` for intermediate state. A 4B cannot
   juggle a growing list in context. "Append each finding to `workspace/x.md` now."
6. ERROR HATCH — a fallback for the common failure. "If `execute_code` errors twice,
   don't retry a third time — `web_search` the correct syntax." Skill-level hatches
   stop the panic earlier than the loop backstop.
7. VERIFICATION GATE (Definition of Done) — the final step states exactly what the
   deliverable is, so the agent knows when to STOP. "Done when `report.md` exists
   and the kanban card is `done`."
8. LAZY LOADING — SKILL.md is a lightweight router. Heavy templates, big tables,
   long examples, taxonomies live in SEPARATE files under `references/` /
   `templates/`, fetched on demand with `read_file("references/…")`. Don't drag a
   40-line template through every turn. Target SKILL.md ≤ ~130 lines.

## Verify tool names BEFORE writing them
The single most common bug is documenting a tool that isn't registered under that
name. A skill that names a phantom tool teaches the model to hallucinate it.
Ground truth, in order of trust: a real bench transcript > `describe_tool("name")`
> `list_tools("keyword")`. Library/CLI names inside `terminal`/`execute_code`
command strings (git, pip, npm, a Python import) are NOT JROS tools — those are fine.

## write_file is sandboxed to skills/
`write_file` and `patch` only write inside the skills/ tree — correct for authoring
skills. A skill whose TASK writes project/source/test files must tell the agent to
use `execute_code` or `terminal` for those, not `write_file`.

## The lifecycle (tools)
study (`skill`/`use_skill`/`list_skill_dir`) → author (`write_file`/`patch`) →
verify (`benchmark_skill`) → record (`record_skill_revision`) → journal in use
(`skill_note`) → deep improve (`request_skill_review`) → share (`package_skill`).
Rule: keep a change only if `benchmark_skill` shows no regression.
