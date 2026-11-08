# Knowledge request ownership verification

Date: 2026-11-08. Isolated development checkout; no live runtime or provider use.

## Repairs

- Skills list/detail, memory reads/search, and Library list/search/detail now own results by request context. Navigation, backend replacement, query changes, retry, and unmount retire previous requests, including requests dispatched before debounce cleanup.
- Read failures are visible and retryable without changing the selected skill, agent, or document. Detail errors do not replace the Library list. Unsupported controls, empty collections, no agents, missing selected agent, search misses, loading, and failures have distinct states.
- Memory and detail response identities are checked before display. A removed memory agent does not silently switch to another agent.
- Knowledge pins the editor's agent and controls while open and disables agent selection. The shared AgentMemory editor remounts for a different agent or backend, isolating outstanding reads/mutations. Retired receipt handling leaves durable pending-operation records and drafts untouched for explicit reconciliation. Existing read-only and mutation gates remain intact.

## Automated evidence

Commands from repository root:

- `npm test --prefix jaeger_ai/interfaces/ui -- src/unified/KnowledgePage.test.tsx src/agents/AgentMemory.test.tsx`: 13 tests passed, 2 files. Ten new regressions plus three existing durable-edit tests.
- `npm run typecheck --prefix jaeger_ai/interfaces/ui`: passed.
- `git diff --check`: passed.

New regressions cover stale skill details/list results, detail retries, stale memory successes/failures, response identity mismatch, removed/no agents, unsupported controls, stale document reads/search results, editor target pinning, editor agent/backend replacement, and a rejected late mutation preserving pending intent and draft bytes.

Logs are external to the checkout under `/tmp/jaeger-baseline-20261108/knowledge-tests.log` and `knowledge-typecheck.log`.

## Limits

Component tests use controlled fake API results and jsdom; they are not end-to-end evidence of real providers, persistence after a process restart, visual browser acceptance, or the native app. No commit, push, deployment, Mac runtime change, or live-provider operation was performed. The parent owns aggregate verification.
