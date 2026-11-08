# Document drafts and response ownership (2026-11-08)

## Scope and producer contract

`DocumentsPage.tsx` edits the WebUI-owned Markdown documents, not Gateway managed-library records. The producer is `features/webui/api/unified_api.py`: GET returns the document revision; PUT accepts `expected_updated_at` and returns the normalized title/body and new revision. The companion backend repair adds the same optional revision check to DELETE and serializes revision comparison and mutation. AI editing returns proposed text, not a document mutation.

No deployment, runtime restart, live provider call, commit, or push was performed for this UI increment.

## Changes

- Draft title/body and their original server base are synchronously stored on every edit in **per-tab sessionStorage**. Workspace navigation and reload can restore them. Another tab's save cannot erase this tab's draft. A duplicated tab inherits a snapshot, then its storage diverges independently.
- Restoring a draft never silently substitutes a newer server revision. The editor reports the conflict and retains the old CAS token. The explicit, confirmed **Discard draft and reload** action fetches successfully before removing recovery data. There is no navigation autosave or automatic recreation.
- When storage is unavailable/full, an in-memory per-document fallback survives workspace unmount/remount. Malformed stored bytes are not overwritten by typing; new edits use that fallback until explicit discard. The UI distinguishes session-only recovery from saved server data.
- Local drafts remain accessible when GET fails or returns 404, including via **Recover draft** buttons when the server list no longer contains the document. Saving still uses the original document ID and revision; it does not silently recreate a missing document.
- A beforeunload warning is registered for unsaved tab drafts and memory fallbacks, even outside the Documents workspace. This is a browser best-effort prompt, not guaranteed retention after tab/app termination. Save to the server or copy important text before closing. SessionStorage is **not durable server storage** and is normally discarded when its tab closes. Memory fallback does not survive reload/crash.
- Selection/request guards reject late open, save, create, delete, and AI results after newer navigation or unmount. Dismissed AI does not reopen. Replacing AI text requires the same document and unchanged edit version.
- Returning to the old base while a save is pending retains a recovery record, including after navigation/unmount; a later server revision leaves that restored draft unreconciled rather than falsely Saved. Dispatch marks a save unreconciled until a validated response arrives, so a committed write with a lost response cannot clear a reverted draft or falsely show Saved.
- Per-document mutation guards suppress concurrent saves/deletes, including across workspace remount. Editing during save retains newer edits; server normalization is adopted only for unchanged fields. Editor inputs are disabled during deletion. DELETE sends the displayed revision.
- GET/PUT document identities and required fields are validated before adoption. List/model load failures have explicit retry controls.
- DELETE snapshots even a clean document before dispatch and retains that recovery copy with an unconfirmed-outcome warning on rejection. Unknown POST outcomes explicitly direct the user to the refreshed list before creating again, without automatic replay.
- Failed/unknown mutations retain recovery data and do not claim Saved/Deleted. PUT retries remain CAS-protected; no write is replayed automatically. The backend does not provide idempotency IDs for create, so an unknown create outcome still requires inspecting the server list before intentionally creating another document.

## Evidence

Focused jsdom React regression suite: `src/unified/DocumentsPage.test.tsx`.

Before implementation, **6 of the initial 7 tests failed** (draft loss, stale open, duplicate saves, save/delete navigation, dismissed AI, cross-document AI); failed-save dirty status already passed. After implementation, **23/23 pass**, also covering malformed/full storage, explicit discard, server normalization, delayed create, rejected deletion, two isolated tab-storage contexts, unavailable/deleted server recovery, recovery without a route ID, and close warnings after unmount.

Commands run from `jaeger_ai/interfaces/ui`:

- `npm test -- --run src/unified/DocumentsPage.test.tsx`: 23 passed.
- `npm run typecheck`: passed.
- `npm run check:theme`: passed.
- `git diff --check`: passed.

Before/after logs are outside the source tree under `/tmp/jaeger-baseline-20261108/documents-before.log` and `documents-after.log`; final TypeScript output is `documents-typecheck-final.log` in that directory. Parent coordinates repository-wide verification against all concurrent changes.

## Limits

These are component/state regression tests with mocked API responses and isolated storage contexts, not browser acceptance or live provider verification. Chromium cannot create required UNIX sockets in this executor; no real-browser acceptance is claimed. Native tab storage isolation follows the browser storage contract and is simulated in jsdom. Browser close prompts can be suppressed by the host, so they do not establish permanent draft durability.
