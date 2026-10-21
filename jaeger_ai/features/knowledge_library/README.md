# Knowledge Library

One instance-owned SQLite `layout.memory_dir/library.db` serves both read-only indexed collections and app-owned managed documents. `store.py` indexes safe text files in already registered roots; it never writes those source files. `managed.py` stores native document content, optimistic revisions, immutable version snapshots and recoverable archive state in additive tables in that same database. Archived managed documents are excluded from ordinary search; restore preserves identity and versions. Restoring a prior version creates a new revision and cannot bypass an archive or revision conflict.

`tools.py` exposes the existing permission-gated collection add/index operations and read-only search/read tools. The Gateway library routes expose existing indexed content and managed document operations; reads use existing read scope, mutations require existing admin scope. No directory grants, credentials, external imports, sharing or permanent deletion are added. Browser controls never accept a filesystem path.

Migration is additive (`library_managed_documents`, `library_document_versions`). Existing indexed corpus/FTS tables and external files remain intact. Older code can leave these tables in place during rollback; do not drop them or discard the renderer's pending operation IDs. No production database migration is performed by a source build.
