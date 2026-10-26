# gateway-session-store — monolith break-out module (split plan, NOT yet cut)

Original file: jaeger_ai/core/gateway/session_store.py, 143,703 bytes, second-largest gateway file. Session persistence for the Gateway.

Proposed split, keeping the store interface unchanged for server.py callers (or server.py's split breaks twice):
- session-records — session create/read/update, ownership, metadata.
- session-transcripts — transcript storage and retrieval, Gateway-owned (clients only project it, see ide-client).
- session-queries — list/search by title, workspace, session ID, transcript content.
- session-archive — archive/unarchive state, Gateway-owned metadata, not a client-side flag.

Test to run when code-run is available: create a session, add turns, list/search, archive/unarchive, reopen from IDE/WebUI, with the original session_store behavior as reference, after each split group.

Overlap with jaeger-agent: session_store is JaegerAI Gateway persistence, not jaeger-agent memory (SQLite memory/world in jaeger-agent). Do NOT merge them into one store, and do NOT edit jaeger-agent memory to fit the Gateway.
