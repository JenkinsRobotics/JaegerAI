# Skill Unification — one Skill, one loader

Status: **DONE (presence-based)** (2026-07-02). A skill is now presence-based: a
folder with a `SKILL.md` is a recipe (indexed for `use_skill`), a folder with a
module registers tools — and a folder with BOTH is BOTH. The mutual exclusion
(`_is_code_skill`) is gone. `computer_use` + `macos_computer` now surface as
recipes AND register their tools. 87→89 skills in `use_skill`. 1440 tests green.

What was intentionally NOT touched: the manifest `package` enum + reserved types
(`mcp_server`, …) stay — MCP works via the plugin system (`plugins/mcp/`) +
the `native-mcp` playbook, NOT the reserved package type, so it's unaffected.
The two loader FUNCTIONS also stay (they're clean typed dispatch, not tangle —
merging them would add coupling for zero agentic gain; see the assessment below).
This IS bench-gated because the `use_skill` surface grew by 2.

## Problem

Two loaders, two schemas, a false category split:
- `skill_loader.py` — discovers skill folders with a **module**, execs it, and
  registers the tools it defines (`DiscoveredSkill`: version/zone/manifest/legacy
  `_vN`/smoke-test). "Tool-skills." 2 today.
- `playbook_skills.py` — discovers folders with a **SKILL.md**, parses frontmatter
  into `PlaybookSkill`, indexes for `use_skill`. "Playbook skills." 87 today.

There is no "tool-skill" class the way it reads in logs — just two passes over
the same tree extracting different things. And most tool-reference metadata is
inert (see below).

## Ground truth (verified)

- **Both loaders scan the same roots:** core `agent/skills/` + the instance
  `skills_dir`. A folder with a module *and* a SKILL.md is seen by both — it
  registers tools AND indexes a recipe.
- Tools register into the **one global registry** (`register_tool_from_function`)
  regardless of which folder defined them — so a skill's tools are never caged to
  that skill; they join the shared pool. Unification is removing a false wall.

## Unified model

**One `Skill`** = a folder that may carry any combination of:
- **A module** (optional) → registers tools into the shared global pool at boot.
- **A recipe** (`SKILL.md`, optional) → the playbook the agent loads via `use_skill`.
- **Frontmatter** (optional, all N/A-normal): `name`, `description`, `category`,
  `tags`, `platforms`, `tier`, `requires_tools`.

"Tool-skill" and "playbook" stop being categories: a skill *has a module*, *has a
recipe*, or *both*. Tools are a shared pool; skills reference by name.

## What is wireable TODAY vs gated on scoping (be honest — no phantom fields)

| Field | Behavior | Buildable now? |
|---|---|---|
| `requires_tools` | **hide the skill if its tools aren't registered** | **YES** — wire into the live `use_skill` enum + index |
| `recommended_tools` | inject the tool if present, ignore if absent | NO — needs scoping (all tools already visible today → nothing to inject). Do NOT add the field until then. |
| `fallback_for_tools` / intercept | reroute a raw-tool reflex to the skill | NO — needs a routing layer; inert today. **CUT** it (YAGNI) rather than keep a dead field. |

Rule (yours): a field ships only with a reader the same week. So this change
**wires `requires_tools`**, **drops the inert `fallback_for_tools`**, and does
**not** add `recommended_tools`/intercept until the scoping/auto-load-on-intent
work lands.

## Implementation (safe order — lowest risk first)

1. **Wire `requires_tools` (hide-if-absent).** `available_playbooks()` already
   supports an `available_tools` filter; the live `use_skill` enum + `skill_index`
   just don't pass it. Pass the registered-tool set so a skill whose required
   tools aren't present is dropped from the enum. Small, isolated, real. Test:
   a skill requiring an absent tool is not offered.
2. **One `Skill` data model.** A single dataclass that carries both the module
   handle (optional) and the recipe/frontmatter (optional). The two discovery
   passes populate it; nothing else changes yet. Terminology in logs → "N skills
   (M register tools)".
3. **Merge discovery into one pass.** One scan of the roots; per folder: if it has
   a registerable module → exec+register (the existing `skill_loader` protocol);
   if it has a SKILL.md → parse+index (the existing `playbook_skills` protocol).
   Keep BOTH protocols' behavior identical — this is a refactor, not a rewrite.
4. **Drop `fallback_for_tools`** from the schema, `skill(view)` output, and the
   backlog vocabulary. Standardize frontmatter (retire the legacy `metadata.hermes`
   nesting; read a flat/`metadata.jros`-consistent shape).

## Migration

The 87 existing `SKILL.md` keep parsing unchanged (name/description/tags/platforms/
requires_tools). Legacy `_vN/` folders + `manifest.yaml` stay handled by the merged
loader's module path. Only removals: the inert `fallback_for_tools` field and the
legacy `metadata.hermes` nesting (both no-ops today).

## Then: per-skill cleanup (step 2, separate)

Once the reader is unified, optimize the 87 SKILL.md (starting with `dogfood`):
purge redundant tool tables (tools are in the native schema), file-back long state
(`append_file`), inline short references, plain-terminal formatting. Those are
content edits that don't depend on the loader — but they land AFTER unification so
any new metadata they declare has a live reader.

## Risk

Boot/loading is load-bearing — a broken loader breaks everything. Mitigation:
steps 1–2 don't touch discovery; step 3 preserves both protocols' behavior
verbatim and is gated behind the full unit suite (skill discovery, tool
registration, toolset-scoping, boot). No behavior change is the acceptance bar.
