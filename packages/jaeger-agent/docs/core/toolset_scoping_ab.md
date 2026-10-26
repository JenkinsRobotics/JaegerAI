# Toolset scoping (P1) — A/B benchmark

Run: 2026-05-20. Timing benchmark (`benchmark/timing/`), 33 prompts,
Gemma 4 26B-A4B, in-process llama-cpp.

## The hypothesis

The agent exposed all ~64 tools to the model every turn. The mined
hermes-agent research called this the #1 routing problem: "a 26B model
picking 1-of-64 each turn is hard." The fix tried — **toolset scoping**:
a ~17-tool CORE always visible, the rest grouped into named toolsets
the model loads on demand via a `load_toolset` tool. A skill is its own
self-describing toolset (the loader captures exactly what it registers).

## Result

| | All tools visible | Toolset scoping (core + load_toolset) |
|---|---:|---:|
| Routing accuracy | **28/33 (85%)** | 22/33 (67%) |
| Avg / prompt | 2.83s | 3.16s |

**Scoping regressed routing by 18 points and was slower.**

## Why it failed

The `load_toolset` **meta-step** is the culprit. When a prompt needs a
non-core tool (`run_python`, `schedule_prompt`, `list_credentials`…),
the model must first *realise* it needs a toolset, *call* `load_toolset`
with the right name, then call the real tool. Gemma 4 does not reliably
take that step — it answered in plain text, or picked a wrong core
tool, instead of loading the toolset. Cases like `list_credentials`
(0.91s) and `reload_skills` (0.76s) returned far too fast to have done
the two-step at all.

The deeper finding: **"too many tools" was not the routing bottleneck.**
Gemma 4 handles a 64-tool surface at 85%. Adding the meta-step *created*
failures it didn't have. The research was a sound theory; the benchmark
refuted it.

## Disposition

- Toolset scoping is **OFF by default** (`JAEGER_TOOLSET_SCOPING`,
  default `0`). The default surface is all tools visible — the proven
  85%. Same discipline as the native chat handler: built, benchmarked,
  found not-a-win, flagged off rather than shipped.
- The code is **kept** — `core/toolsets.py`, the skill-as-toolset
  capture in the loader, `load_toolset`. It is the foundation for the
  one variant that might still work: **auto-load on intent** — a cheap
  keyword pre-pass loads the likely toolset *before* the turn, so the
  model never has to take the meta-step. That is a separate experiment;
  scoping stays opt-in until it beats 85%.

## Takeaway

Routing accuracy on Gemma 4 is not gained by shrinking the visible tool
surface. The remaining levers for cleaner agentic behavior are
elsewhere: in-loop stall recovery, a tool-call guardrail, and clearer
(disambiguating) tool descriptions.
