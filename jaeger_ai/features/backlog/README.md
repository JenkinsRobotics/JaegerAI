# Backlog

Matthew's Jaeger project task list. The SQLite file `~/.jaeger/backlog.sqlite3`
(`JAEGER_BACKLOG_DB` overrides) is the source of truth.

| Surface | What |
| --- | --- |
| REST (Gateway, loopback) | `GET /v1/backlog`, `POST /v1/backlog`, `POST /v1/backlog/{id}`, `POST /v1/backlog/{id}/assign`, `POST /v1/backlog/import` |
| MCP | `jaeger.backlog_list`, `jaeger.backlog_add`, `jaeger.backlog_update` (`assign_to=` hands off) |
| UI | Work › Backlog (`/work/backlog`), ⌘K "Go to Backlog" / "Backlog: needs my OK" |
| Import | `python -m jaeger_ai.features.backlog.importer [~/Documents/Jaeger-Backlog.md]` (insert-only) |

Task fields: id, title, detail, source, status (`open`/`in_progress`/`needs_ok`/`done`),
priority (`P0`/`P1`/`P2`), worker, handoff id/thread, last note, timestamps.

Assign sends a real hub `task` message to the worker (from the calling surface,
or `jaegerd` when a worker assigns itself) and links it. The worker's `status`
/`result`/`question` replies on that thread move the task (result → done;
failure/blocked/needs-ok words → needs_ok). Explicit result statuses are only
successful for `done`, `completed`, `finished`, and the legacy `done, <note>`
form. Omitted/empty status retains historical result → done compatibility.
Other explicit result/answer statuses, including unknown and pending, map to
`needs_ok` for unresolved-result intervention, not approval or retry. Only the worker named on the task
can move it. Only owner surfaces may approve a `needs_ok` task or import.
Muse can't read the hub inbox, so assigning to Muse also appends a notice to its
file-bridge `inbox.md`; Muse replies are not linked automatically.
Every change publishes a `backlog.updated` activity row.
