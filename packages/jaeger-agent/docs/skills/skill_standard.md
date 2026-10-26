# JROS Skill Standard — authoring cheat sheets for a 4B agent

A skill is a **cheat sheet**: it hands a small local model the knowledge, the
exact tool names, and the SOP to do a task it would otherwise fumble. Every
`SKILL.md` is rewritten against this checklist. Measured basis: this session's
benchmark work (see `session_retrospective_2026_07.md`).

## The 8-point checklist
1. **Naming** — an explicit, accurate name. No vague "helper" titles, no cute
   codenames that hide the function (`dogfood` → `web-app-qa`).
2. **Boundary (the WHEN)** — a 1-sentence trigger in the frontmatter
   `description`: when to pick THIS over a similar tool/skill. This is what makes
   the agent *select* it. NOTE: keep it in frontmatter (surfaced by `skill(list)`
   on demand) — NOT stuffed into the always-visible `use_skill` enum (measured:
   descriptions in the always-on surface regressed −4).
3. **Strict SOP** — phased, plain-terminal formatting (UPPERCASE headers, no
   nested markdown tables, no `**bold**`). Punchy and scannable.
4. **Tool coupling (the cheat sheet)** — list the EXACT registered tool names the
   recipe calls, inline. This is the #1 rule: `pf_macos_do` failed because the
   skill documented `computer_do` while the tool was actually registered as
   `_computer_do` — the agent hallucinated the documented-but-unregistered name.
   (Fixed both ways: the skill now lists the real names AND the tool was renamed
   to drop its odd leading underscore.) Names must be correct and inline (cheap);
   heavy assets go external (rule 8).
5. **State offloading** — if a procedure has >3 outputs or >3 steps, MANDATE
   `append_file`/`write_file`/`kanban` for intermediate work. A 4B can't juggle a
   list in context. "Append each finding to `workspace/x.md` immediately."
6. **Error hatches** — a fallback for the common failure. "If `execute_code`
   errors twice, don't retry a third time — `web_search` the correct syntax."
   (JROS also has a loop backstop, but skill-level hatches stop the panic earlier.)
7. **Verification gate (Definition of Done)** — the final step states exactly what
   the deliverable is, so the agent knows when to stop. "Done when `report.md`
   exists and the kanban card is `done`."
8. **Lazy loading** — the `.md` is a lightweight routing/logic engine. Heavy
   templates, large examples, taxonomies live in SEPARATE files, fetched on demand
   with `read_file`. Don't drag a 40-line template through every turn.
   "Phase 5: if you need the format, `read_file('templates/report.md')`."

## Verify the tool names before you write them
The single most common bug is documenting a tool that isn't registered under that
name. Confirm against the registry / how the agent actually calls it (a bench
transcript is ground truth) before listing a tool in a skill.

## Rollout — DONE (2026-07-03), tiered
- **Tier 1 (correctness):** fixed stale JROS tool names across ~8 skills
  (`skill_view`/`skill_manage`→`use_skill`/`skill`, `computer_do` names) and
  dropped the odd `_computer_*` underscore. `e71f9d0`, `6ec91b8`.
- **Tier 2 (integrated/selected skills):** rewrote 17 skills to the 8-point
  standard (arxiv, ascii-art, codebase-inspection, research-paper-writing,
  spike, node-inspect-debugger, native-mcp, opencode, himalaya, hermes-agent,
  systematic-debugging, test-driven-development, writing-plans, plan,
  requesting-code-review, subagent-driven-development, hermes-agent-skill-authoring).
  Removed the fabricated `delegate_task` tool everywhere; split the 2377- and
  1013-line monsters into `references/`. Every tool name verified against the
  registry.
- **Tier 3 (the tail):** all 70 tail skills already had descriptions; 63 had
  loader-readable tags. Added tags to the 7 that lacked them. Migrating the
  hermes→jros tag namespace was skipped as cosmetic (the loader now reads both,
  see `_tags_of`).
- **skill-builder** (new meta-skill): the canonical create/review/improve SOP +
  the full authoring standard (references/authoring-standard.md).

## Bench note (2026-07-03): 77 → 75/81, two borderline flips
The full unscoped bench went 77→75 after the skill work. Both losses are the
same phenomenon — a knife-edge case flipping *deterministically* because the
skill-index prompt changed (17 rewritten descriptions + skill-builder added),
NOT a broken skill:
- `skill_native_tier` — the agent DRIVES the desktop correctly via the
  CORE-visible `computer_*` tools but skips `use_skill(macos-computer-use)`, so
  the skill-loading scorer fails it. It *plans* `use_skill` then executes the
  tool directly — the deferred planning/runner lever (make `PLAN:` obligate the
  stated first action).
- `selfimprove_curate` — expects the `skill` tool but the agent picks
  `skill_notes` (whose own description — "blank → a tally of which skills are
  stale/unused" — matches the prompt "check for stale/unused skills"); the call
  then halts. skill-builder's "audit the skill library" description likely
  primes this. A defensible choice the scorer doesn't credit.
Neither was fixed by loosening a case (that would be gaming). Both are recovered
by the deferred planning-lever work, not more skill edits.

## Status
- `macos-computer-use` — rewritten with the correct tool NAMES **and arg shapes**
  (`computer_open_app(name=…)`, `computer_do(goal=…)`, named args throughout).
- `dogfood` → renamed `web-app-qa`; its verbose report format moved to an external
  template fetched on demand (the lazy-load example).

## What the bench proved (2026-07-03, E4B, scoped) — and what it didn't
The scrub WORKED at the skill layer, and doing so isolated the real blockers:
- `pf_macos_plan` now **loads `macos-computer-use` and calls the real `computer_do`**
  (was: hallucinated `computer_do`, no skill loaded). The skill cheat sheet fixed
  selection + naming.
- `pf_macos_do` still can't *complete* — the computer_use tools have **no
  Accessibility/GUI to drive in the headless bench** ("failed to claim an action").
  That's an environment limit, not a skill or model bug; the case scores the
  action it can't perform. Candidate for a scorer that credits "loaded right skill
  + attempted right tool" (like the harness false-negative fixes).
- `skill_native_tier` / `skill_codebase_inspect` **already pass unscoped** (the
  committed default). They failed only under the opt-in **scoped** path, where the
  planning mandate makes Gemma narrate `PLAN: use_skill(...)` as prose (or emit a
  tool call missing its closing token) and halt at iter 1. Two distinct non-skill
  issues:
    1. **Parser** — Gemma sometimes drops the closing `<tool_call|>` token, so a
       real call leaked as text. Added a tolerant fallback in `dialects/gemma.py`
       (only when the strict patterns match nothing). Flips scoped
       `codebase_inspect` ✗→✓. Genuine parse-layer false-negative recovery.
    2. **Planning narration** — `native_tier` emits a bare `PLAN:` prose line with
       NO tool-call token; nothing to salvage. This is the scoped planning mandate
       pushing a 4B to narrate instead of act. Belongs to the "gentler runner /
       nudge-don't-mandate" thread, not the skill scrub.

Takeaway: skills are now correct cheat sheets. The residual scoped-path losses are
runner/prompt + harness-environment problems, tracked separately.
