# Kanban board — design

> **Status: built — shipped in 0.1.0.** The board (`core/board.py`), the
> four `board_*` tools, the `/board` TUI command, and the Deep Think
> fold-in (the queue is now a view over the board, with a one-time
> migration of any legacy `deep_think_queue.jsonl`) are all live. This
> document is the design record; it matches the implementation.

A single inspectable **board** is the agent's task surface — for ad-hoc
multi-step work, for Deep Think, and for goal decomposition. It replaces
the standalone Deep Think queue and gives the agent (and the user) one
place to see "what is being worked on, what is next, what is stuck."

## Why

Jaeger-OS tracks work in three disconnected places today:

- **Deep Think queue** — `deep_think_queue.jsonl`, states `pending →
  approved → done`.
- **`/goal`** — an autonomous completion condition, with no
  decomposition into steps.
- **Schedules** — cron triggers.

And there is no general task list at all (Hermes' `todo` was
deliberately skipped — kanban is the right way to fill that gap).

The key observation: **the Deep Think queue is already a one-column
kanban board.** `pending → approved → done` *is* `backlog → ready →
done`; `propose_deep_think_task` plus the user-approval gate *is* a card
moving `backlog → ready`. Kanban is not a new concept bolted on — it is
the generalization of what the framework already does.

## The board model

One board per instance, persisted at `<instance>/memory/board.json` —
a single JSON document rewritten atomically on change (the precedent is
`facts.json`, not the append-only `*.jsonl` logs, because cards are
mutable: they move columns).

A **card**:

| field | meaning |
|---|---|
| `id` | `card_<hex>` |
| `title` | one line |
| `description` | optional detail / acceptance notes |
| `column` | `backlog` \| `ready` \| `in_progress` \| `blocked` \| `done` |
| `source` | `user` \| `agent` \| `goal` \| `deepthink` \| `schedule` |
| `tags` | free-form labels (e.g. `deepthink`, `coding`) |
| `parent` | card id of the epic this belongs to, or `null` |
| `priority` | `low` \| `med` \| `high` |
| `created_by` | `user` \| `agent` |
| `created_at` / `updated_at` | ISO timestamps |
| `notes` | running log the agent appends as it works |
| `result` | filled when the card reaches `done` |

Columns are a **fixed set** in 0.2 — no user-configurable columns,
swimlanes, or multi-board. Keep it small; generalize later if needed.

## Lifecycle — and the approval gate

```
            agent proposes              user approves
  (none) ───────────────────▶ backlog ─────────────────▶ ready
                                                            │ agent picks up
                                                            ▼
   done ◀─────────────── in_progress ──────────────▶ blocked
         card complete                  needs the user
```

- An **agent-proposed** card lands in `backlog` — *unapproved*. This is
  exactly today's `propose_deep_think_task` behaviour.
- A person moves `backlog → ready` to approve it. The agent **cannot**
  self-approve — `board_move` refuses an agent-driven `backlog → ready`.
  The approval gate you locked in for Deep Think is preserved verbatim.
- A **user-created** card may be created straight into `ready` (no
  self-approval problem — a person made it).
- The agent moves its own cards `ready → in_progress → done` / `blocked`
  freely.

## Folding in Deep Think

`DeepThinkQueue` / `deep_think_queue.jsonl` is **retired**. Its tasks
become cards:

- `propose_deep_think_task(description)` → `board_add(...)` with
  `tags=["deepthink"]` → `backlog`.
- `list_deep_think_queue()` → `board_view(tag="deepthink")`.
- The Deep Think manager / daemon drains **`ready` cards** (it moves one
  to `in_progress`, works it, writes `result`, moves it to `done`,
  attaches the after-action reflection as `notes`) instead of reading
  the JSONL queue.
- `/deepthink start` / auto-idle activation are unchanged — only the
  *queue* behind them becomes the board.

A one-time migration (core-version bump) converts existing
`deep_think_queue.jsonl` rows into `board.json` cards.

## Folding in goals

`/goal "<condition>"` optionally creates an **epic** card. The agent
decomposes the goal into child cards (`parent` = the epic id) and works
them. The goal evaluator can read the board — "3 of 5 child cards done"
is a far better progress signal than re-judging free text each turn.
`/goal` keeps working standalone; the board is enrichment, not a forced
coupling.

## The schedule tie-in

Schedules stay exactly as they are — cron triggers are a different beast
from work cards (a recurring trigger never "reaches done"). The tie-in
is one-directional: **a scheduled prompt can drop a card on the board.**
`schedule_prompt("0 9 * * 1", "add a board card: review the week's PRs")`
— when cron fires, that turn calls `board_add`, and the card shows up in
`backlog` with `source="schedule"`. No new scheduling machinery.

## Tools (~4 — replacing the 2 Deep Think queue tools, net +2)

| tool | tier | what |
|---|---|---|
| `board_view(column=None, tag=None)` | READ_ONLY | the board, optionally filtered |
| `board_add(title, description="", tags=[], parent=None, priority="med")` | local | add a card → `backlog` (agent) ; returns "awaiting approval" |
| `board_move(card_id, column)` | local | move a card; refuses agent `backlog → ready` |
| `board_update(card_id, ...)` | local | edit title / description / tags / append `notes` / set `result` |

The three mutating tools are **not confirmation-gated** — they only
touch the instance's own `board.json`, the same low-risk local
bookkeeping as `remember`. Prompting on every card move would be
miserable UX.

## TUI

A `/board` slash command renders the five columns (Rich columns/table).
Operator sub-commands:

- `/board` — show the board
- `/board approve <id>` — `backlog → ready`
- `/board add <title>` — create a card straight into `ready`
- `/board done <id>` / `/board block <id>` — quick moves

`/deepthink` stays for *run control* (`start`, auto-idle) but its
`add` / `list` / `approve` sub-commands become aliases of the `/board`
ones.

## Out of scope for 0.2

Custom / user-defined columns, swimlanes, multiple boards, card due
dates (schedules cover time), card assignees (one agent per instance),
a web board view. Revisit only if real use demands them.

## Open questions

1. Should the agent auto-create cards for *every* multi-step turn, or
   only for substantial work (Deep Think, goals, long builds)? Leaning:
   only substantial work — prompt guidance, not a hard rule, so trivial
   two-step turns don't spam the board.
2. `done` column growth — auto-archive cards `done` older than N days
   into `board.archive.json`? Probably yes, cheap.
3. Does `blocked` notify the user proactively (a message / a TUI
   highlight), or just sit until they look? Leaning: surface it in the
   status bar.
