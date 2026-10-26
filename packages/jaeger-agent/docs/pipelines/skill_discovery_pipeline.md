# Pipeline: Skill / Tool Discovery (push → pull)

**What it is:** how the agent finds and selects the right *tool* or *playbook
skill* for a task. As of 2026-07-01 this is **pull-based** (was push-based).
Improvement backlog: `dev/docs/roadmap/agentic_skill_pipeline_backlog.md`.

## Vocabulary
- **Tool** — a callable function (`agent/tools/*.py`), in the registry
  (`agent/schemas/tool_registry.py`; `get_tools()`).
- **Tool-skill** — a skill that *registers tools* (`computer_use`,
  `macos_computer`). Loaded by `skill_registry/skill_loader.py`.
- **Playbook skill** — a `SKILL.md` process doc that registers **no** tools;
  discovered by `skill_registry/playbook_skills.py`, surfaced via the `skill`
  tool (`agent/tools/skills.py`).

## The flow

```
system prompt (every turn):
  • core tool schema (the model's immediate verbs; specialist tools load on demand)
  • ONE lean skill hint  ← build_skill_index()  (count + category breadth + cue)
        │
   turn arrives
   • conversational → answer. ~0 skill tokens.
   • non-trivial task → the agent's RESEARCH step ↓
        │
   RESEARCH:  skill(action="list")            ← agent/tools/skills.py
      → curator-served FULL active catalog, enriched per skill:
          name · category · description · tier · tools · fallback_for
      (no coordinator filtering — the agent is the intelligence)
        │
   ├─ match → skill(action="view", name) → full SKILL.md recipe
   │          tier steers the pick (native > fallback)
   └─ no match → use tools directly, NOTE the gap
        │
   PLAN → EXECUTE (follow the recipe / chain tools) → VERIFY → REFLECT
```

## Key functions
- `playbook_skills.build_skill_index()` → the **lean always-on hint**: count +
  category list + "call skill(action=list) when starting a task." (~136 tokens;
  was the full ~349-token names index.) Keeps *ambient awareness* skills exist
  (anti-reinvention) without the per-turn cost.
- `agent/tools/skills.py :: skill(action=...)`:
  - `list` — the full active catalog, each entry `{name, category, description,
    tier, tools, fallback_for}`. Full by default (no limit = all); optional
    `category=`/pagination, but the curator does **not** filter by relevance.
  - `view`/`use` — the full SKILL.md of one skill (the recipe); may auto-load its
    toolset.
  - `search`, `stats`.
- `playbook_skills.PlaybookSkill` — the parsed metadata: `name, category,
  description, tags, path, platforms, requires_tools, requires_toolsets,
  fallback_for_tools, tier`. All from the SKILL.md YAML frontmatter.

## Metadata that drives routing (in each SKILL.md frontmatter)
- `tier: native | preferred | standard | fallback` — steers selection (a **hint**,
  not a hard router; routing is all soft).
- `fallback_for_tools: [toolA]` — "this is the higher-tier alternative to toolA."
- `requires_tools: [...]` — the tools the skill chains (fills the `tools` field).
- `platforms: [...]` — hidden on non-matching OS.
- `archived: true` — **retired**; excluded from discovery (metadata flag, no folder
  move; git holds old versions).

Example (`apple/macos-computer-use/SKILL.md`): `tier: native`,
`fallback_for_tools: [computer_use]`, `requires_tools: [computer_use, computer_do,
computer_look]` — so on a macOS task the agent prefers the native path over the
generic `computer_use` fallback.

## Why pull (efficiency + quality)
- **Efficiency:** conversational turns pay ~0 for skills; the detailed catalog is
  fetched once per task, not pushed every turn. At equal quality, push would cost
  ~thousands of tokens every turn.
- **Quality:** the pulled catalog is **complete + enriched** (descriptions, tier,
  tools) exactly when the agent decides — vs the old names-only, truncated index.
- **Reliability (reinvent-the-wheel):** pull removes the old ambient name-index, so
  it depends on the agent actually researching. Countered by (a) the lean hint's
  count+categories+cue and (b) the post-task **reflect-check** (P4, *not yet built*)
  that flags "a matching skill existed and was ignored."

## Status
- **Done:** lean hint, enriched `skill(list)` (tier/tools/fallback), `tier` +
  `archived` metadata, archived-skip in discovery.
- **Owed:** live agent-behaviour test (does it research + route native?); populate
  `requires_tools` across more SKILL.md; the reflect-check (P4); tool-skill rename
  (P5). See the backlog.
