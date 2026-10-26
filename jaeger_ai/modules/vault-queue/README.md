# vault-queue — independent module, code copied, NOT yet wired

Job: a small, standalone SQLite job queue — enqueue a job, claim it, retry it, record errors — with no external dependencies beyond Python stdlib. This is the one Ai work item that was small enough, standalone enough, and dependency-free enough to copy as code, not just register.

Source + copy:
- Desktop "Ai  work " / vault_queue.py, 4,535 bytes, 139 lines, copied verbatim into this folder as vault_queue.py (copy verified by the file tool, no edits in the copy).
- Head: VaultQueue class, sqlite3, WAL journal mode, jobs table (id, task_type, payload, priority, status pending, retry_count, error, created_at, updated_at), index on (status, priority DESC, created_at), enqueue() with uuid + timestamp, max_retries=3 default.
- NOT in the Jaeger repo before this module: Jaeger has features/dispatcher (primary/worker sessions + Kanban + sidecar) and core/runtime work_ledger, but neither is a generic SQLite job queue with this exact schema. Overlap check: dispatcher is session routing, work_ledger is runtime bookkeeping, vault-queue is a job queue — different jobs, so this is an OPTIONAL alternative, not a duplicate to delete. Do NOT merge it into dispatcher without an import check.

How it bolts on (wire later):
- Register as a Jaeger tool / host service via the tool registry, with a bound database path (never a model-named path, never ~/.jaeger state without an owner). Jobs are data, not permission: claiming a job does NOT authorize its effect — the effect still goes through proposer/checker/approval gate.
- Keep it single-writer: one process owns the queue DB, readers use the module, not direct SQLite opens from multiple agents (see project-boundaries module).

Test to run when code-run is available, alone first: enqueue 3 jobs with different priorities, claim in priority order, fail one twice then succeed, fail one past max_retries and record error, restart and verify no job is lost or double-claimed, WAL mode on.
