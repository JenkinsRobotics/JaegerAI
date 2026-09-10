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

## Next slices

1. Optional FTS5 virtual table on `messages` (see `fts.py` stub).
2. Compaction / long-context compressor cherry-picks.
3. Wire WebUI `/api/sessions/search` (or existing list filter) to `search_messages`.
