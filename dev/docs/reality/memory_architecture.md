# JROS memory architecture — the storage pipeline (locked 2026-07-03)

The rule: **long-term knowledge → SQL; short-term/working state → JSON;
high-frequency telemetry → time-series (later).** Pick storage by data shape,
not habit.

## Long-term memory = SQLite (`<instance>/memory/state.db`)
Durable, queryable, attributed knowledge. This is the source of truth.

- **facts** — the CURRENT view. Columns:
  `subject, key, value, category, source, tags, note, created_at, updated_at`,
  PK `(subject, key, source)`.
  - `subject` — WHO/WHAT the fact is about (operator by default, or a named
    person/thing — supports "I know many people's colours").
  - `source` — WHO SET it: `user` (operator) / `agent` (inferred) / `benchmark`.
    The operator's recall ignores `benchmark` facts; a bench run only sees its
    own. Purge test data with `DELETE FROM facts WHERE source='benchmark'`.
  - `category` + `tags` + `note` — the 5W1H context and grouping.
- **fact_log** — APPEND-ONLY history. One row per `remember()`. Lets a fact be
  traced over time ("blue on d1, black on d2"); the `facts` row is just the
  latest. `recall_history(key, subject)` reads it.
- **episodic** + **episodic_embeddings** — every turn + its vector, for SEMANTIC
  recall (`search_memory`). Use this for open-ended "what did we talk about…";
  use `facts`/`recall` for structured keyed facts.
- **sessions.db** — per-session conversation history.

Retrieval split: **structured** (subject/key/tag) from `facts`; **semantic**
(fuzzy, open-ended) from `episodic_embeddings`. Synthesis ("your colours are
blue and black") is the AGENT's job at recall time — SQL hands it the raw
assertions.

## Short-term / working state = JSON (small, operational, human-editable)
- `board.json` — the kanban board (current cards).
- `schedules.json` — scheduled prompts.
- `skill_notes.jsonl` — skill-use telemetry (append log).
These are small, ephemeral-ish working state — JSON is right; SQL would be
overkill.

## Removed (2026-07-03)
- `core/memory/facts.py` (legacy `facts.json` key/value layer) — dead since
  facts moved to SQL; deleted. The one-shot `facts.json`→SQL importer in
  `memory.py` stays until we're sure no un-migrated instance exists, then goes.

## The tool surface
`memory(action=remember|recall|history|forget|list|search, …)` — `remember`
takes `subject`/`category`/`tags`/`note`; `recall`/`history`/`forget` take
`subject`. The `memory-keeping` skill teaches the 5W1H discipline (the schema is
cheap; the value comes from the agent actually populating context — that's what
the skill drives).

## Future (0.7): time-series telemetry → InfluxDB
Robot/hardware telemetry (JP01 `/sense/node_health` at 1 Hz, motor positions,
latencies) is a genuine time-series firehose — SQL is the wrong tool for that
volume. Plan to add InfluxDB (or equivalent) for hardware telemetry in 0.7,
SEPARATE from the SQL knowledge memory. See future_backlog.md.
