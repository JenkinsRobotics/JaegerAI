---
name: skill-builder
description: "Create, review, or improve a JROS skill (a SKILL.md playbook). Load this whenever the task is to author a new skill, fix/tighten an existing one, or audit the skill library — it hands you the standard, the exact authoring tools, and the review + benchmark loop."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [write_file, patch, read_file, list_skill_dir, search_files, skill, use_skill, benchmark_skill, record_skill_revision, request_skill_review, skill_note, package_skill]
metadata:
  jros:
    tags: [skill, authoring, meta, review, standard, playbook]
    category: software-development
    related_skills: [hermes-agent-skill-authoring, requesting-code-review, writing-plans]
---

# SKILL BUILDER — author, review, and improve JROS skills

A skill is a CHEAT SHEET: it hands a small (4B) local model the knowledge, the
EXACT tool names, and a tight SOP for a task it would otherwise fumble. A skill
is a folder under `jaeger_os/agent/skills/<category>/<name>/` with a `SKILL.md`
(the recipe) and optional `references/`, `templates/`, `scripts/`, `tests/`.

## THE AUTHORING TOOLS (exact names — call with named args)
```
list_skill_dir(path="…")                     survey the skills tree
skill(action="list") / skill(action="search", query="…")   study peer skills
skill(action="view", name="…", file="references/x.md")     read a skill's files
use_skill(name="…")                          load a peer recipe to learn its shape
write_file(path="…", content="…")            create/overwrite a skills/ file
patch(path="…", old="…", new="…")            surgical edit of an EXISTING skills/ file (prefer this)
read_file(path="…")  /  search_files(…)      read + grep
benchmark_skill(name="…")                    run the skill's scored bench, track the delta
record_skill_revision(skill="…", version="…", summary="…", benchmark_delta="…")   log a KEPT revision
request_skill_review(skill="…")              queue a Deep Think improvement pass from usage notes
skill_note(skill="…", outcome="…", note="…") journal a post-use observation (feeds self-improvement)
package_skill(name="…")                       bundle a finished skill into a shareable .zip
```
`write_file`/`patch` are SANDBOXED to the skills/ tree — that is exactly where
skills live, so that's correct here. You cannot write a skill outside skills/.

## THE STANDARD (the 8 points — the bar every skill meets)
Full checklist + the exact frontmatter schema: `read_file("references/authoring-standard.md")`.
In one breath: 1) accurate NAME · 2) a description BOUNDARY (the WHEN-to-pick trigger) ·
3) a tight phased SOP · 4) TOOL COUPLING with EXACT registered tool names ·
5) STATE OFFLOADING (>3 steps → files/todo/kanban) · 6) an ERROR HATCH ·
7) a DONE-WHEN (definition of done) · 8) LAZY LOADING (heavy assets in
references/, fetched with read_file — never inline).

## HARD RULES (breaking these makes a skill worse than none)
- NEVER invent a tool name. Every tool the recipe tells the agent to CALL must be
  a REAL registered tool. Verify: `list_tools("keyword")` / `describe_tool("name")`,
  or check a real bench transcript (ground truth). A skill that documents a
  non-existent tool makes the model hallucinate that call. This is the #1 bug.
- Library/CLI names in examples (git, pip, npm, curl, a Python import) are fine —
  those are shell/library calls run via `terminal`/`execute_code`, not JROS tools.
- Restructure, don't redesign: keep the skill's domain facts and steps correct.
- Plain-terminal formatting: UPPERCASE headers, no nested tables, minimal bold.
  Target 50–130 lines for SKILL.md; overflow → references/.

## FLOW A — CREATE a new skill
1. STUDY: `skill(action="search", query=…)` for near-duplicates (don't rebuild an
   existing skill); `use_skill` the closest peer to copy its shape.
2. DRAFT: pick `<category>/<name>/`, `write_file` the SKILL.md to the schema in
   references/authoring-standard.md. Verify every tool name is real (rule 1).
   Put heavy tables/templates/examples in `references/` via write_file, link with
   read_file.
3. VERIFY: `benchmark_skill(name=…)` if the skill ships tests/benchmark.py; else
   walk the SOP mentally against the tool list. Fix what breaks.
4. RECORD: `record_skill_revision(skill=…, version="1.0.0", summary=…, benchmark_delta=…)`.
   Optionally `package_skill(name=…)` to share it.

## FLOW B — REVIEW an existing skill (audit against the standard)
1. `read_file` the SKILL.md. Score it against the 8 points.
2. TOOL AUDIT (the highest-value check): for every `word(` the recipe tells the
   agent to call, confirm it's a real tool (`describe_tool`/`list_tools`). Flag any
   that aren't — that's the hallucination bug.
3. Check: description has a WHEN-trigger? SOP tight + phased? state offloaded?
   error hatch + done-when present? heavy content lazy-loaded not inline?
4. Report findings ranked by severity (wrong tool names first). Fix in Flow C.

## FLOW C — IMPROVE a skill
1. Small fix (wrong tool name, tightened trigger, added hatch): `patch(path=…,
   old=…, new=…)`. Big rewrite: `write_file` the whole SKILL.md.
2. `benchmark_skill(name=…)` — keep the change only if the delta is ≥ 0 (never
   regress). If it ships no bench, re-walk the SOP.
3. `record_skill_revision(...)` with the delta. For a deeper, usage-driven rewrite
   you can't do inline, `request_skill_review(skill=…)` to queue a Deep Think pass.

## ERROR HATCH
- Unsure a tool exists / its args → `describe_tool("name")` before writing it. Never
  guess an arg name; a wrong JSON key gets the call rejected.
- `benchmark_skill` regresses → revert the change (`patch` back or restore), the
  prior version stands. A regression is information, not a reason to force it.
- Skill won't appear after authoring → the loader is cached per session; a new
  skill shows next session. Check the frontmatter parses (`---` fences, valid YAML).

## DONE WHEN
The SKILL.md meets all 8 points, every tool it names is real, it's ≤ ~130 lines
(overflow in references/), and — if it ships a benchmark — `benchmark_skill`
shows no regression. Then `record_skill_revision` logs the change.
