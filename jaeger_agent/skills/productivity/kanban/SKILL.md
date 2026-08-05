---
name: kanban
description: "Run your kanban task board — file work, track multi-step jobs, triage urgent-vs-later. Load this whenever the user flags work for 'later / no rush / when you get a chance', hands you a multi-step task to track, or asks what's on the board."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [board_add, board_view, board_move, board_update, board_delete, propose_deep_think_task]
metadata:
  jros:
    tags: [kanban, board, tasks, planning, triage, deferral]
    category: productivity
    related_skills: [deep-think, writing-plans, subagent-driven-development]
---

# KANBAN — YOUR STANDING TASK BOARD

The board is your durable TODO stack (separate from chat) — it survives across
sessions. It is FIVE small tools, one per verb. Use the exact tool for the op;
there is no single "kanban" tool.

## THE TOOLS (exact — one verb each)
```
board_add(title="…", description="…", priority="low|med|high", tags=[…])   file a new card (lands in `ready`)
board_view(column="…", tag="…")                                            read the board (both args optional)
board_move(card_id="…", column="…")                                        move a card between columns
board_update(card_id="…", note="…", result="…", add_tag="…")               edit / log progress on a card
board_delete(card_id="…")                                                  remove a card entirely
```
Columns: `backlog` · `ready` · `in_progress` · `blocked` · `done`.

## THE TRIAGE RULE (the important one)
When a request mixes URGENT and LATER work:
- Do the URGENT part NOW with the real tools (calculate, write_file, …).
- FILE each deferrable part with `board_add(...)` and STOP working it — do NOT
  start it, do NOT load a playbook for it this turn. Confirm it's logged.
- Never silently drop deferred work, and never do work the user said can wait.

## SOP
1. FILE: user says "later / no rush / when you get a chance" -> `board_add(title=…,
   priority=…)`. One card per distinct task. Then stop and confirm.
2. TRACK a multi-step job: `board_add` a card per step up front, then as you work
   each: `board_move(card_id, "in_progress")` -> do it -> `board_update(card_id,
   result="…")` -> `board_move(card_id, "done")`.
3. IDLE pickup: `board_view()` -> take the highest-priority `ready`/`in_progress`
   card -> work it -> move to `done`. One card per idle tick.
4. BLOCKED: needs the user -> `board_move(card_id, "blocked")` and say what's needed.
5. DISCARD a card that's no longer wanted -> `board_delete(card_id)`.

## HARD vs ROUTINE WORK
A card alone does NOT hand work to the strong model. For a big build/fix that
needs the Deep Think coder model, ALSO call `propose_deep_think_task(description=…)`
— that's the actual handoff; the board card just tracks it.

## ERROR HATCH
- `board_move`/`board_update`/`board_delete` returns "no card <id>" -> you used a
  stale id; `board_view()` to get the current card ids, then retry.

## DONE WHEN
Urgent work is done, every deferrable item is a card on the board (not dropped,
not half-done), and you've told the user what you did vs what you filed.
