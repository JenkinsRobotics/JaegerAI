---
name: self-improvement
description: "Audit and curate your OWN skill library: find stale or unused skills worth retiring, spot skills that keep underperforming, and queue fixes. Load this for 'check / curate / clean up / retire skills', 'which skills are unused or stale', or reviewing how your skills are doing."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [list_skills, skill_notes, request_skill_review, record_skill_revision, skill_note]
metadata:
  jros:
    tags: [self-improvement, curation, skills, maintenance, retire, review]
    category: software-development
    related_skills: [skill-builder, deep-think]
---

# SELF-IMPROVEMENT — CURATE + IMPROVE YOUR OWN SKILL LIBRARY

Keep the skill library healthy: retire what's gone stale, improve what keeps
underperforming, and log how skills are doing so the loop can learn. This is
library-level upkeep — for AUTHORING one skill, use `skill-builder`.

## WHEN TO USE
- "Check / audit / curate / clean up the skill library; which skills are stale
  or unused; anything worth retiring?"
- After heavy skill use, to journal what worked and flag what didn't.

## THE TOOLS (exact — read-only unless noted)
```
list_skills(action="curate")   find STALE / unused agent-authored skills (the audit)
list_skills(action="stats")    which skills + tools actually get used
list_skills(action="list")     the full catalog, to eyeball coverage/overlap
skill_notes()                   a tally across ALL skills of which ones are struggling
skill_notes(skill="name")       recent usage notes for one skill
request_skill_review(skill="name")   queue a Deep Think pass to IMPROVE an underperformer
skill_note(skill="name", outcome="issues", note="…")   journal a post-use observation
record_skill_revision(skill="name", version="…", summary="…")   log a kept change
```

## SOP
1. AUDIT for stale/unused: `list_skills(action="curate")` — it reports which
   agent-authored skills have gone stale (read-only; it retires nothing itself).
2. FIND the strugglers: `skill_notes()` (blank = the per-skill outcome tally) and
   `list_skills(action="stats")` for usage. Low-use + issue-heavy = candidates.
3. ACT, don't just look:
   - A skill that keeps underperforming -> `request_skill_review(skill="name")` to
     queue a measured Deep Think improvement pass.
   - Something you just observed -> `skill_note(...)` so the signal isn't lost.
4. REPORT to the user: the stale/unused list, the underperformers, and what you
   queued. Retiring is the operator's call — surface candidates, don't delete.

## ERROR HATCH
- `list_skills(action="curate")` returns nothing stale -> say so; a clean library
  is a valid result. Don't invent skills to retire.

## DONE WHEN
You've reported the stale/unused skills and any underperformers, and queued a
review (`request_skill_review`) for anything worth improving.
