# Studio conditional-save compatibility

GET /v1/studio/board returns normalized items, optional legacy updated_at and revision: lowercase SHA256 of exact persisted bytes, or `missing` only when genuinely absent. Valid legacy on-disk Boards remain readable without rewriting. Corrupt/unreadable data is unavailable (503), not an empty board.

PUT requires items and expected_revision. Missing preconditions return 428, malformed values return 400, and stale values return 409 without changing committed Board bytes. Only `missing` or lowercase 64-character SHA256 is valid. Successful writes return actual normalized items, updated_at, generation and revision. A changing nonsecret generation prevents obsolete revisions becoming current again when content/time repeats. Authentication and permissions are unchanged; a revision is not authorization.

Matching backend and client must roll out together through a separately approved maintenance plan. Old clients against the new backend explicitly fail blind writes with an upgrade/reload precondition error. New clients must not treat an old backend's missing or malformed revision/acknowledgment as success or silently downgrade to blind writes. Reload is not safe draft recovery: preserve unresolved local intent before leaving the current view.

Compare/read/validate/commit occurs under a stable OS lock local to the canonical resolved Board target. Cooperative independent processes, differing operator roots and symlink aliases for one target converge. Shared helper default callers retain existing behavior; changed shared code requires fresh consumer qualification rather than whole-domain inheritance. Replacement uses unique temporary files, fsync and atomic replace. This is not protection against arbitrary external writers.

Asset deletion rereads CURRENT Board under that same lock, preserves unrelated notes and removes references before index/file changes. Stale snapshots cannot resurrect deleted references. Invalid Board data stops destructive asset side effects. A crash or failure after Board commit may leave partial cross-file deletion; index/file/Board crash atomicity is not established.

The mounted client retains its original server base separately from local edits, serializes one in-flight save, coalesces edits and validates acknowledgment before advancing its base. Conflict, error, malformed success or unknown outcome preserves visible local intent and persistent warning while stopping automatic writes, even after more edits. It does not fetch a newer revision and replay stale state. Multi-client merge, safe retry and durable drafts across navigation/reload/restart remain outside this increment.

Restoring older code can remove concurrency protection even if it still reads new data. Never infer rollback safety from parse compatibility alone. Never blindly restore an old data backup over newer work.
