---
name: spike
description: "Build throwaway prototypes to validate an idea before committing to a real build — load this when the user says 'let me try this', 'spike it out', 'is this even possible?', 'quick prototype of X', or 'compare A vs B'."
version: 1.1.0
platforms: [macos, linux, windows]
requires_tools: [web_search, web_extract, terminal, write_file, read_file, todo]
metadata:
  jros:
    tags: [spike, prototype, experiment, feasibility, proof-of-concept]
    category: software-development
    related_skills: [writing-plans, subagent-driven-development]
---

# SPIKE

Feel out an idea before committing to a real build: validate feasibility, compare
approaches, surface unknowns that research alone can't answer. Spikes are
disposable — throw them away once they've paid their debt.

## WHEN NOT TO USE
- Answer is knowable from docs/reading code → just research, don't build.
- It's production-path work → use `writing-plans` instead.
- Idea is already validated → go straight to implementation.

## TOOLS
- `web_search(query="...")` — find candidate libraries/approaches.
- `web_extract(url="https://...")` — read the actual docs (returns readable text).
- `terminal(command="...")` — mkdir, install, run the prototype, check versions.
- `write_file(path, content)` — create spike dirs' README + code.
- `read_file(path)` — read a cloned lib's README/examples when it has no docs page.
- `todo(...)` — track the spike queue when there are 2+ spikes (offload state).

## CORE LOOP
`decompose → research → build → verdict` — iterate on findings.

### 1. DECOMPOSE
Break the idea into 2-5 independent feasibility questions. Each = one spike.
Frame each as Given / When / Then with an observable output, and a risk level.
- standard spike = one approach to one question.
- comparison spike = same question, different approaches → share the number with
  letter suffixes (`002a`, `002b`).
ORDER BY RISK: the spike most likely to kill the idea runs first.
Log the queue with `todo(...)` so you don't lose track across steps.
Skip decomposition only if the user already named exactly one thing to spike.

### 2. ALIGN (multi-spike only)
Present the spike list + order. Ask: "Build all in this order, or adjust?"
Let the user drop / reorder / re-frame before you write any code.

### 3. RESEARCH (per spike, before building)
1. Brief it: 2-3 sentences — what, why it matters, key risk.
2. If there's real choice, surface 2-3 competing approaches (tool, pros, cons,
   maintained/abandoned). Use `web_search` then `web_extract` on the docs.
3. Check what's already installed: `terminal(command="pip show <lib> | grep Version")`.
4. Pick one, state why. If 2+ are credible, build quick variants in the spike.
5. Skip research for pure logic with no external dependency.

### 4. BUILD
One standalone directory per spike under `spikes/`:
```
spikes/001-websocket-streaming/{README.md, main.py}
spikes/002a-pdf-parse-pdfjs/{README.md, parse.js}
spikes/002b-pdf-parse-camelot/{README.md, parse.py}
```
Bias toward something the user can INTERACT with (best → ok): runnable CLI that
prints observable output; minimal HTML page; one-endpoint server; a unit test with
recognizable assertions. A log line saying "it works" is not enough.

Typical sequence:
```
terminal(command="mkdir -p spikes/001-websocket-streaming")
write_file("spikes/001-websocket-streaming/README.md", "# 001: websocket-streaming\n...")
write_file("spikes/001-websocket-streaming/main.py", "...")
terminal(command="cd spikes/001-websocket-streaming && python3 main.py")
# observe, iterate
```
HARDCODE everything — no Docker, bundlers, config systems, env files. It's a spike.
DEPTH OVER SPEED: never declare "it works" after one happy path. Test edge cases;
follow surprising findings. The verdict is only trustworthy if the probe was honest.

For comparison spikes (002a/002b), build them BACK TO BACK, then write the
head-to-head. (There is no sub-agent delegation tool — build sequentially.)

### 5. VERDICT
Close each spike's `README.md` with:
```
## Verdict: VALIDATED | PARTIAL | INVALIDATED
### What worked / What didn't / Surprises / Recommendation for the real build
```
- VALIDATED = core question answered yes, with evidence.
- PARTIAL = works under constraints X, Y, Z — document them.
- INVALIDATED = doesn't work, and here's why. This is still a successful spike.

For comparison spikes, add a head-to-head verdict scoring both on extraction
quality, setup cost, performance, and edge-case handling, then name a winner.

## FRONTIER MODE ("what should I spike next?")
Walk existing `spikes/` dirs and hunt: integration risks (two validated spikes
touching one resource, tested apart), unproven data handoffs, unproven assumed
capabilities, and alternative angles for PARTIAL/INVALIDATED spikes. Propose 2-4
Given/When/Then candidates; let the user pick.

## ERROR HATCH
If a prototype won't run after two fix attempts, that IS a finding — write it as
INVALIDATED (or PARTIAL) with the blocker, and move to the next spike. Don't sink
a spike's whole budget into one build.

## DONE WHEN
`spikes/NNN-name/` exists per spike, each with a `README.md` carrying question,
approach, results, and a VALIDATED/PARTIAL/INVALIDATED verdict. Code stays
throwaway — a spike that needs 2 days to "clean up for production" was a bad spike.
