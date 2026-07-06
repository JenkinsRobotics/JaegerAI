# Pipeline: Memory (store → recall → search → review)

**What it is:** how a Jaeger instance persists and recalls what it learns.
Two layers, one SQLite file: **facts** (curated key/value the agent
remembers/recalls) and **episodic** (one row per turn, semantically
searchable). Everything is instance-scoped — `<instance>/memory/state.db`
(`core/memory/sqlite_store.py:54`, `_DB_FILENAME = "state.db"`) — so two
instances on one host never share state.

## Vocabulary
- **Fact** — a durable `{key, value, category}` row the agent stores on
  purpose (`facts` table, `sqlite_store.py:182`). Category defaults to
  `'general'` (`memory.py:_norm_category`, line 119).
- **Episodic turn** — one `(user, answer, decision_raw, …)` row written
  automatically per turn (`episodic` table, `sqlite_store.py:193`).
- **Episodic embedding** — one normalised float32 vector BLOB per episodic
  row, keyed by `episodic_id` with `ON DELETE CASCADE` (`episodic_embeddings`
  table, `sqlite_store.py:212`). Powers semantic search.
- **Short-term context** — the in-process history for the live session. A
  session starts with a CLEAN slate; prior sessions are NOT replayed
  (`main.py:_get_session_history`, ~line 692). Distinct from episodic
  memory, which is the durable store the agent queries on demand.

## The flow

```
bind(layout)                                  ← memory.py:43  (once at boot)
  • sqlite_store.bind(): open state.db, WAL pragmas, try sqlite-vec,
    ensure schema                             ← sqlite_store.py:73
  • lazy-import pre-0.2.0 facts/episodic/schedules/audit JSONL → SQL
        │
   turn runs
        │
   ┌── WRITE (automatic) ──────────────────────────────────────────┐
   │  every turn → _record_episodic → mem.append_episodic(...)      │
   │      → INSERT into episodic      (main.py:678, memory.py:336)  │
   └───────────────────────────────────────────────────────────────┘
        │
   ┌── WRITE (agent-driven) ───────────────────────────────────────┐
   │  memory(action="remember", key, value, category)              │
   │      → mem.remember → INSERT OR REPLACE into facts             │
   │        (agent/tools/memory.py:93, memory.py:175)               │
   └───────────────────────────────────────────────────────────────┘
        │
   ┌── RECALL ─────────────────────────────────────────────────────┐
   │  memory(action="recall", key)  → mem.recall  (memory.py:200)  │
   │     1) exact key → 2) substring over keys → 3) word-overlap    │
   │        (fuzzy fallback; stopwords stripped)                    │
   │  memory(action="list") → facts + by_category                  │
   └───────────────────────────────────────────────────────────────┘
        │
   ┌── SEARCH (semantic) ──────────────────────────────────────────┐
   │  memory(action="search", query)  → mem.search_memory          │
   │        (agent/tools/memory.py:70, memory.py:570)              │
   │     • _ensure_embeddings_up_to_date(): encode any episodic     │
   │       row missing a vector (sentence-transformers, batched)   │
   │     • encode query → cosine (dot of normalised vecs) over the │
   │       embedding BLOBs → top-k                                  │
   └───────────────────────────────────────────────────────────────┘
        │
   ┌── REVIEW (background, periodic) ──────────────────────────────┐
   │  every JAEGER_MEMORY_REVIEW_EVERY user turns (default 8):     │
   │  one bounded model call reads recent turns → promotes up to 5 │
   │  new facts via mem.remember  (main.py:2280, 2303)            │
   └───────────────────────────────────────────────────────────────┘
```

## Key files / functions
- `core/memory/sqlite_store.py` — the store foundation.
  - `bind(layout)` (line 73) — opens `<instance>/memory/state.db`,
    idempotent; re-bind to same layout no-ops, to a different layout closes
    the old conn first.
  - `_open()` (line 108) — WAL journal, `synchronous=NORMAL`, foreign keys
    ON, 5s busy-timeout; single per-process connection with
    `check_same_thread=False`, writes serialized by `_write_lock`.
  - `_try_load_vec()` (line 131) — best-effort `sqlite-vec` load; on any
    failure `has_vec_extension()` stays False and search uses the Python
    cosine fallback.
  - `_SCHEMA_STATEMENTS` (line 169) — defines `schema_version`, `facts`,
    `episodic`, `episodic_embeddings`, `schedules`, `sessions`,
    `tool_calls`, `audit_log`. `SCHEMA_VERSION = 1` (line 52).
  - `writer()` (line 341) — `_write_lock` + `BEGIN IMMEDIATE`; commit on
    success, rollback on exception. Every INSERT/UPDATE/DELETE goes through it.
- `core/memory/memory.py` — the public facade (signatures unchanged from the
  0.1.x JSON era; storage swapped to SQL underneath).
  - `bind(layout)` (line 43) — sets legacy paths in `_state`, calls
    `sqlite_store.bind`, then runs the four lazy JSONL→SQL importers.
  - Facts: `remember` (175, `INSERT OR REPLACE`, preserves `created_at`),
    `recall` (200, exact → substring → word-overlap fuzzy), `forget` (244),
    `list_facts` (252), `list_facts_by_category` (260, `'general'` sorted last).
  - Episodic: `append_episodic` (336); `_extract_episodic_columns` (292) maps
    known fields to columns and bundles the rest into `meta_json`.
    `load_recent_turns` (350) returns role/content pairs from `decision_raw`;
    `recent_qa_pairs` (387) returns user/answer pairs.
  - Semantic search: `EMBED_MODEL_ID` (477) =
    `sentence-transformers/all-MiniLM-L6-v2` (override via
    `SEMANTIC_MEMORY_MODEL`). `_ensure_semantic_model` (485) lazy-loads
    SentenceTransformer pinned to **CPU** (Metal collides with
    llama-cpp-python's context). `_ensure_embeddings_up_to_date` (524) encodes
    missing rows in batches of 32, stores normalised float32 as BLOB.
    `search_memory` (570) encodes the query, computes cosine via
    `vectors @ q_vec`, returns top-k `{user, answer, timestamp, score}`.
    (sqlite-vec KNN is not yet wired — the code always does the Python-side
    cosine scan; the `vectors @ q_vec` path at line 610-624 is the only one.)
- `agent/tools/memory.py` — the tool layer the agent calls.
  - `memory(action, key, value, query, category)` (line 93) — one consolidated
    tool routing `remember` / `recall` / `forget` / `list` / `search`.
  - The five granular siblings (`remember`, `recall`, `forget`, `list_facts`,
    `search_memory`) still exist alongside the umbrella (`tool_bundles.py:88`).
- `main.py` — write + review wiring.
  - `_record_episodic` (678) → `append_episodic`, called per turn when
    `_pipeline["with_memory"]` is set (679); skips turns with no user text.
  - `_get_session_history` (~692) — clean-slate session context; comment
    documents that past turns live in episodic memory, retrieved on demand.
  - `_previous_session_digest` (2245) — a bounded, REFERENCE-ONLY digest of
    the last `_SESSION_RESUME_TURNS = 6` episodic pairs for this session key,
    for orientation after a restart (not task resumption).
  - `_maybe_spawn_memory_review` (2280) / `_memory_review_worker` (2303) —
    every `_MEMORY_REVIEW_EVERY` (default 8, env
    `JAEGER_MEMORY_REVIEW_EVERY`) user turns, a background thread runs one
    model call over recent turns and promotes up to `_MEMORY_REVIEW_MAX_FACTS
    = 5` new facts via `remember` (dedup: skips if `recall(key) == value`).
    Takes `llm_lock` only if free; skips `deepthink`/`bench` sessions.
- `agent/prompts/reflection.py:111` — a reflection lesson is also written into
  episodic memory (`append_episodic`) so `search_memory` can resurface it.

## Storage: what lands where (`state.db`)
- `facts` — curated key/value + category (agent-driven memory).
- `episodic` — one row per turn: `session_key, ts, user, answer,
  decision_raw, tool_activity, latency_ms, first_decision, skipped_final,
  meta_json`.
- `episodic_embeddings` — vector BLOB per episodic row (semantic index).
- `schedules`, `sessions`, `tool_calls`, `audit_log` — sibling tables in the
  same store (schedules/tool-calls/audit have their own facade functions in
  `memory.py`; not part of the recall path).
- WAL sidecars `state.db-wal` / `state.db-shm` sit in the same `memory/` dir
  (`sqlite_store.py:32-36`).

## Status
- **Done:** SQLite-backed facts + episodic; fuzzy `recall`; semantic
  `search_memory` over episodic embeddings (sentence-transformers, CPU,
  lazy/incremental encoding); consolidated `memory` tool + granular siblings;
  automatic per-turn episodic write; periodic background memory-review that
  promotes facts; lazy JSONL→SQL import for pre-0.2.0 instances.
- **Fallback / not-yet-wired:** `sqlite-vec` loads when available but KNN is
  not wired — `search_memory` always runs the Python-side cosine scan
  (`memory.py:607-624`). Migration runner beyond v1 is a stub
  (`sqlite_store.py:_ensure_schema`, line 322 branch).
- **Not the live path:** `core/memory/facts.py` is a JSON-backed Lilith port
  (its own docstring, line 1-11); the live store is `memory.py` + SQLite.
