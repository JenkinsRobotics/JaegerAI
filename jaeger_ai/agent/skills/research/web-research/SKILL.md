---
name: web-research
description: "Answer a question that needs current or external information — 'what's the latest on X', 'find the docs for Y', 'is Z true', 'compare A and B'. Load this whenever the answer isn't in your own knowledge/memory or could be stale, before reaching for web_search/web_extract raw."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [web_search, web_extract]
requires_toolsets: [web]
metadata:
  jros:
    tags: [research, web, search, citations, fact-checking]
    category: research
    related_skills: [log-calculations]
---

# WEB RESEARCH — SEARCH -> EXTRACT -> CITE

Two tools, used in a strict order: `web_search` finds candidate pages (title +
url + snippet only — NOT enough to answer from), `web_extract` fetches one
page's real text. Never answer from a snippet alone.

## THE TOOLS (exact)
```
web_search(query="...", max_results=5)     titles/urls/snippets, no page body
web_extract(url="...", max_chars=8000)      full text of ONE page
get_weather(location="...")                 dedicated tool — don't web_search weather
```

## THE TRIAGE CHAIN

1. `web_search(query=...)` with a query close to the user's actual words —
   don't over-narrow on the first try. 3-5 results is normally enough.
2. Scan titles/snippets, pick the 1-3 most likely to have the real answer
   (official docs/source > news > forum/blog, unless the question IS about
   forum opinion). Never pick purely by list position.
3. `web_extract(url=...)` each candidate, in order of confidence. Read what
   comes back before deciding you need another page — don't extract all 5
   speculatively.
4. **When to fan out vs stop:**
   - Stop after ONE extract if it directly answers the question with a
     clear, citable statement.
   - Fan out to a 2nd/3rd extract when: the first page is thin/ambiguous,
     the question asks to "compare" or "find the best", or the claim is
     surprising/high-stakes enough to want a second source.
   - Stop fanning out once two independent sources agree — don't keep
     extracting "just in case."
   - If the first `web_search` returns nothing useful, reformulate the
     query (more specific terms, or drop a qualifier) ONCE before telling
     the user you couldn't find it — don't retry the identical query.
5. Synthesize the answer in your own words; don't paste raw extracted text.

## CITATION DISCIPLINE

- Every non-obvious factual claim traces to a page you actually
  `web_extract`'d this turn — not a `web_search` snippet, not memory.
- Name the source inline when it matters ("per the official docs at
  <url>...", "TechCrunch reports...") — enough for the user to verify,
  not a formal bibliography.
- If sources disagree, say so — don't silently pick one and hide the
  conflict.
- Never state a specific number, date, price, or quote you didn't see in
  an extracted page. "I couldn't confirm the exact figure" beats a
  plausible-sounding guess.
- A claim from your own training data (not this turn's search) gets
  flagged as such ("from what I know, though I didn't verify this just
  now...") rather than presented with the same confidence as a cited one.

## ERROR HATCH

- `web_search` returns zero/junk results twice in a row -> tell the user
  what you tried and ask them to narrow it, rather than fabricating.
- `web_extract` fails (paywall, JS-only page, 404) -> try the next
  candidate from the search results; don't retry the same dead URL.
- Time-sensitive question ("what's happening right now with X") ->
  `get_time()` first so "recent" is anchored to the real date, then favor
  the most recently-dated result.

## EVAL EXAMPLES

| User ask | Expected chain | Notes |
|---|---|---|
| "what's the latest jaeger-os release" | web_search -> web_extract (1 page) | stop once one page confirms it |
| "compare X vs Y pricing" | web_search -> web_extract x2 | two sources, fan out expected |
| "is <surprising claim> true" | web_search -> web_extract x2+ | verify before repeating a surprising claim |
| "what's the weather in Austin" | get_weather (NOT web_search) | dedicated tool exists — don't triage-chain this |

## DONE WHEN

The user has a synthesized answer with the claim(s) traceable to a page
you actually extracted this turn, contradictions surfaced rather than
hidden, and no fan-out beyond what was needed to settle the question.
