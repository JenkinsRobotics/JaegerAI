# Retrospective — persona + skill/tool scaling work (2026-07-02/03)

E4B (gemma-4-e4b), corpus v1.3 (81 cases). All-time high: **76/81** (persona-era,
a ~75-76 peak). Current committed default: **73-74/81** (two post-fix samples:
73, 74; avg 73.5 — record band, and ~560s vs the record's ~580s, so faster).

## Where the stack landed
| Surface | Score | Speed | State |
|---|---|---|---|
| Unscoped default (HEAD) | **73/81** | 561s | committed |
| **Scoped + search-first** | **73/81** | **461s** | committed, opt-in (`JAEGER_TOOLSET_SCOPING=1`) — **beats the 96-tool full surface (70) by +3** |

The scoped path is the headline: **record-band accuracy on a 60%-smaller surface,
~24% faster** — the scaling architecture.

## What we LEARNED (all measured, not assumed)
1. **Persona in the worker context taxes a 4B ~7-10%** (A/B/C: vanilla 75.5, voice-tag 70, full 68). The "drop persona when executing" boundary rule does NOT hold at any persona size.
2. **The tool schema is a cached prefix** — its cost is the model's *attention*, not tokens/latency. So "less context" helps by reducing distraction, not compute.
3. **Agent-driven tool loading fails on a 4B.** Left optional, the model *never* calls `load_toolset` — it improvises with a visible tool (weather → `web_search`). Of 16 lost cases in the lean-18 run, 0 loaded.
4. **A single prompt line was sabotaging scoping:** "don't call load_toolset unless asked" (written for the unscoped default) told the scoped agent NOT to load.
5. **Forcing the search fixes it:** a searchable `list_tools` + a "search before you act" mandate → the model finds `get_weather` and loads it. weather 4→9/9.
6. **More text buries the signal.** The skill-description catalog (6.4k in `use_skill`) *regressed* −4 and *lowered* skill-call frequency. Same lesson three times (persona menu, catalog, lean-surface-with-load_toolset).
7. **Hard runner enforcement backfires.** A deny-and-retry planning gate regressed 73→66 — denying a batch mid-flow disrupts a 4B that was already searching correctly.
8. **Naming collisions misroute.** Adding `list_tools` pulled "give me an overview" away from `help_me` until the docstring disambiguated them.

## What WORKED (shipped)
- **Workers run vanilla** — persona out of execution: +7, faster, zero regressions. (`602dce5`)
- **Skill unification (presence-based)** — one model, no `code_skill`/`playbook` split; neutral, cleaner. (`959bc96`)
- **SCOPE CHECK + SKILLS-BEFORE-TOOLS planning** — recovered `hall_company_search`. (`396bb15`)
- **Scoped search-first** (`list_tools` + mandate) — 73, beats full surface, faster, scalable. (`abe00ae`, `fd64e2b`)
- **Leaderboard** (visible category breakdown) + **per-run transcript** (sent/expected/outcome + schema). (`10dc603`)
- **The discipline itself** — every change bench-gated. It caught the catalog regression, the runner-gate regression, and the `list_tools` misroute *before* they shipped.

## What did NOT work (reverted / dropped)
- **Skill-description catalog** — −4, reverted (superseded by the lean-surface finding).
- **Agent-driven `load_toolset`** — the model ignores it.
- **Deny-and-retry runner gate** — 73→66, reverted; logged.
- **The "don't call load_toolset" line** — sabotaged scoping; removed.

## The scalability thesis — VALIDATED
Lean CORE + search-before-act + skills auto-scoping their own tools = record-band
accuracy, faster, **bounded context**. The win is *scale*: add 500 specialized
tools/skills and CORE stays tiny, the flat surface would not. Speed already favors
scoped now (461 vs 606s) and the gap widens with every tool added.

## Recommendations — what's NEXT
1. **Ship scoped-search as the scaling default when the library grows** — it's committed and opt-in today; flip the default once the tool count justifies it.
2. **Gentler runner enforcement** — the *idea* (guarantee the searches) is right; the *shape* (deny the batch) is wrong for a 4B. Try: nudge alongside letting the tools run, or gate only a true no-tool finalize. Don't deny mid-flow.
3. **Real gap-fixes to beat the record** (not noise-hunting): `deepthink` (steer `dt_propose_skill_fix` to `propose_deep_think_task`); the 2 scorer artifacts (`ms_calc_and_speak` accepts the spelled number; `safety_prompt_injection` refuse-without-naming-internals).
4. **Symmetric renames** `list_skills`/`load_tools` — clarity, cosmetic, do when convenient.
5. **Two-pass persona output filter** — restore the character voice on top of the vanilla worker (the deferred sprint).
6. **Re-bench the 26B** on the current stack — only E4B has been exercised lately.

## Open threads
- Working tree is clean; HEAD holds everything; nothing pushed.
- `native_tier` recovering under scoping *proves* skill-derived tool-scoping — worth wiring `requires_toolsets` on more skills so the long tail scopes itself.
