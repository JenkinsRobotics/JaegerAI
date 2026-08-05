---
name: memory-keeping
description: "Keep rich, traceable long-term memory: record facts with WHO/WHAT/WHEN context, track how they change over time, and recall them precisely. Load this when storing or answering about people's details, preferences, or anything the user will expect you to remember across sessions."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [memory, recall, remember, search_memory]
metadata:
  jros:
    tags: [memory, facts, recall, preferences, people, long-term]
    category: productivity
    related_skills: [self-improvement, deep-think]
---

# MEMORY-KEEPING — RICH, TRACEABLE LONG-TERM MEMORY

Long-term memory is SQL (durable, queryable, attributed). Store facts with
enough context that you can trace them back — who it's about, what, when, and
why. A fact isn't just a value; it's a value with a history.

## THE MODEL (5W1H, mapped to the tool)
- WHO it's ABOUT -> `subject` (omit = the operator; "alice" for someone else)
- WHAT -> `key` + `value` (snake_case key, e.g. favorite_color = blue)
- WHEN -> recorded automatically (every write is timestamped + logged)
- WHY/HOW -> `note` (the context: "mentioned while planning the trip")
- grouping -> `category` (preferences / contacts / projects / schedule) + `tags`

## THE TOOLS (exact)
```
memory(action="remember", key="favorite_color", value="blue", subject="jonathan",
       category="preferences", tags="colour", note="said it casually")
memory(action="recall",  key="favorite_color", subject="jonathan")   current value
memory(action="history", key="favorite_color", subject="jonathan")   values OVER TIME
memory(action="forget",  key="…", subject="…")                       drop current (history kept)
memory(action="list")                                                all facts by category
memory(action="search", query="…")                                  semantic search of past chat
```
`remember`/`recall` also exist as their own tools. Use `search` (semantic over
episodic chat) for open-ended "what did we talk about…", `recall` for a known key.

## SOP
1. STORE proactively: the moment the user states a preference, detail about a
   person, plan, or identity fact -> `memory(action="remember", …)` with a
   subject (if it's about someone), a category, and a `note` for context.
   Acknowledging "I'll remember" WITHOUT the tool call is lying — never do that.
2. Re-stating changes it, doesn't erase it: if they say the colour is now black,
   `remember` it again — the old value stays in history.
3. RECALL before answering anything they told you earlier: `memory(action=
   "recall", …)` first; the store is the source of truth, not this chat.
4. CHANGED-OVER-TIME questions -> `memory(action="history", …)`, then synthesize:
   "you mentioned blue on Jul 1 and black on Jul 3 — your colours are blue and black."
5. ABOUT OTHER PEOPLE: always set `subject`. "Alice likes green" ->
   subject="alice". "Who likes what" -> recall each subject.

## ERROR HATCH
- `recall` misses (fuzzy key didn't hit) -> `memory(action="search", query=…)`
  over episodic chat, or `memory(action="list")` to see the actual keys, then
  recall the right one. Never answer "I don't know" without trying search + list.

## DONE WHEN
The fact is stored with its subject + context (or recalled + answered from the
store, not from chat memory). For a changed fact, the answer reflects the history.
