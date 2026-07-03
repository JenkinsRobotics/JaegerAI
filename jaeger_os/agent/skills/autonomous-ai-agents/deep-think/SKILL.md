---
name: deep-think
description: "Hand a task that's too big for right now to the Deep Think model instead of botching it in this turn. Load this when the user says 'note it for later / fix it properly later / that's too big to do now', or when you hit a job that needs the strong coder model, deep research, or hours of work — you queue it and note it, you don't attempt it live."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [propose_deep_think_task, kanban, todo]
metadata:
  jros:
    tags: [deep-think, escalation, defer, planning, background]
    category: autonomous-ai-agents
    related_skills: [self-improvement, subagent-driven-development, writing-plans]
---

# DEEP THINK — DEFER THE BIG STUFF, DON'T BOTCH IT LIVE

Some work does not belong in the current turn: a proper fix/rewrite that's too
large, a build that needs the strong coder model, deep multi-source research, or
a multi-hour job. For these you HAND OFF to Deep Think — you do not half-do it now.

## WHEN TO USE
- The user says "note it / log it / fix it properly later / that's too big for now".
- You spot a real fix or feature worth building that's bigger than this turn.
- A task needs the coder model or sustained background work, not a quick answer.
NOT for a task you can just DO now — do that instead of deferring it.

## THE TOOLS (exact)
```
propose_deep_think_task(description="…")   queue a build/fix task for the Deep Think model
kanban(action="add", title="…", description="…", tag="…", priority="…")   note it on the board
todo(...)                                   optional: track it in the session list
```
`propose_deep_think_task` takes ONE argument, `description` — write it as a crisp,
self-contained task the strong model can pick up cold (what's broken / what to
build, where, and the acceptance check).

## SOP
1. RECOGNIZE the moment: is this too big/complex/long for now? If yes, do NOT
   start hacking at it — defer.
2. QUEUE it: `propose_deep_think_task(description="Fix the weather skill: it
   crashes on malformed input — add validation + tests, keep the bench green.")`.
3. NOTE it so it isn't lost: `kanban(action="add", title="Fix weather skill
   crash", description="malformed-input handling", tag="skill-fix", priority="med")`.
4. TELL THE USER plainly: it's queued for Deep Think + on the board — you didn't
   silently drop it and you didn't botch a rushed fix.

## ERROR HATCH
- If you catch yourself starting the big fix inline "just quickly" — stop. That's
  the exact failure this skill prevents. Queue it, note it, move on.

## DONE WHEN
The task is queued with `propose_deep_think_task` AND noted on the kanban board,
and you've told the user it's deferred to Deep Think.
