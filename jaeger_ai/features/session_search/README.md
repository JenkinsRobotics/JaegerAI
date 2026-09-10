# Session search

Product home for transcript search over Jaeger ``sessions.db``.

## Why

`SessionStore.search` today is `LIKE %-needle-%` — fine for small DBs, weak
for large histories and unsafe if we later feed raw strings into FTS5 MATCH.
Hermes-agent has a battle-tested sanitizer + FTS mixin (~2.5k LOC); we
cherry-pick the query-prep algorithms here instead of rebasing the frozen tree.

## API

- `prepare_search_query` / `sanitize_fts5_query` / `escape_like`
- `search_sessions(store, query)` — uses SessionStore, with sanitized LIKE
- `search_messages(store, query)` — returns message-level hits + snippets

Full FTS5 table creation stays behind `fts.py` helpers for a later pass.
