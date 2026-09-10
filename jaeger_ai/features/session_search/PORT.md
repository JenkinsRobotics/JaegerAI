# Session search — port notes

## Donors

| Donor | Path | Status |
|---|---|---|
| hermes-agent | `hermes_state_search.py` (`SessionSearchMixin`, `_sanitize_fts5_query`) | **Partial** — sanitizer + LIKE escape landed in `query.py` |
| hermes-agent | `hermes_state_common.py` (`escape_like`, `FTS_SQL`) | Escape adapted; FTS schema not yet applied to Jaeger sessions.db |
| hermes-agent | `agent/native_compaction.py`, `agent/context_compressor.py` | Not ported — follow-up under agent package / this feature |

## Attribution

`sanitize_fts5_query` logic adapted from Hermes-agent `SessionSearchMixin._sanitize_fts5_query`
(AGPL-3.0 donor; keep this note when deepening the port).

## What works now

- Canonical DB: `<instance>/memory/sessions.db` via `sessions_db_path` / `open_session_store`
- LIKE search over titles + message text (`search_sessions` / `search_messages`)
- Agent tool `session_search` and bridge `search_sessions` both sanitize through this feature
- FTS5 virtual table **not** applied — `fts.py` remains a follow-up migration

## Next slices

1. Optional FTS5 virtual table on `messages` (see `fts.py` stub).
2. Compaction / long-context compressor cherry-picks.
3. Optional WebUI list filter that surfaces message-level snippets from `search_messages`.
