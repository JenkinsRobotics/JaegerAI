# Studio Board conditional saves

## Contract and compatibility

The authenticated Studio routes and permission boundary are unchanged. GET
`/v1/studio/board` returns `items`, optional legacy `updated_at`, and `revision`.
The revision is the SHA256 of the exact persisted bytes, or `missing` only when
the file does not exist. It is concurrency metadata, not an authorization token.
Existing valid legacy Board files remain readable without rewriting them.

PUT requires `{items, expected_revision}`. The precondition must be `missing`
or a lowercase 64-character SHA256. Missing preconditions return 428 with an
upgrade/reload explanation, malformed ones return 400, and stale ones return
409 without changing Board bytes. Old clients must upgrade and reload; blind
full-snapshot writes are intentionally no longer accepted. Invalid/unreadable
persisted data returns 503 and is not treated as a missing Board.

Successful PUT returns the actual normalized `items`, `updated_at`, `generation`
and new `revision`. The persisted nonsecret generation changes on each commit,
preventing stale authority from returning even when item content or wall time
repeats. Clients retain their original revision on failure/uncertain response.
They must not fetch a newer revision and replay a stale full snapshot.

## Storage and cooperation

The Board target remains `<unified state_root>/studio/board.json`.
`JAEGER_STATE_HOME` still takes precedence over `JAEGER_STATE_DIR`; this change
neither redirects existing storage nor changes the operator resolver.

All Board reads and mutations use the canonical resolved target and a stable
OS flock in its sibling `.board-write-locks` directory. Thus different process
operator-root settings and symlink aliases for the same target share a lock.
The shared atomic-files helper accepts an explicit lock root; consumers that
omit it retain their existing operator-root lock behavior. Compare, read,
schema validation and commit are one critical section, with unique temporary
files, fsync and atomic replacement. Writers wait at most five seconds for the
lock before an unavailable response. This protects cooperating writers, not
arbitrary external file edits or applications that ignore the protocol.

Asset deletion validates and rereads CURRENT Board under the same lock, commits
reference removal, then updates the asset index and removes the file. An older
Board snapshot cannot resurrect references. Unrelated notes already committed
are retained. Corrupt Board data stops deletion before index/file side effects.
This is not a cross-file crash-atomic asset/index/Board transaction; failures
following Board commit can leave a partially completed deletion. Asset-only
index writers retain their existing concurrency behavior; this is not a general
multi-process asset-library transaction repair.

## Mounted client behavior and limits

The Board keeps the loaded base separately from its local edit generation.
It permits only one in-flight save, coalesces newer local edits, and advances
its server base only after validating a normalized acknowledgement. Conflicts,
failed requests and malformed acknowledgements retain visible local intent,
show a persistent warning and pause automatic writes, including after later
edits. They do not authorize a blind retry. Source/lifetime and failed-load
safeguards remain.

Draft durability across navigation, refresh or restart is NOT part of this
increment. No storage keys, new credentials, persistent access, owner scopes or
auth modes are introduced. A verified nonsecret owner/instance recovery scope
is a separate prerequisite for safe durable draft recovery. Mounted component
tests are not browser/process-concurrency proof; process tests independently
exercise the producer protocol. Full release verification and runtime rollout
remain separate gates.
