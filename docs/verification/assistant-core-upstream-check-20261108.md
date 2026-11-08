# Canonical upstream snapshots

The isolated candidate remains based on
ff71bb769bc56e4c6d7be6d540a86be73e291e07, canonical master when work began.
The latest read-only query at 2026-11-08T19:28:16Z confirmed the canonical
https://github.com/JenkinsRobotics/JaegerAI.git default branch is master at
315f6eacbf99cab11b6a3edf3441a545140ca4c4. The candidate is not combined with
that revision. No main-checkout fetch, reset, merge, rebase or remote write was
performed during this inspection.

## Earlier snapshot retained

The earlier 25f3300e1973b59ddc3ecb8e75ed7cecbdaf2bb9 snapshot had exactly two
linear commits beyond the review base: 29b48c6 added the pip-audit timeout, and
25f3300 added branch-retirement/release-gate documentation. Its lack of runtime
or path overlap and isolated git apply --check result were valid for that
snapshot only. They do not establish compatibility with the newer master.

## New runtime changes

[Commit cbdcc147](https://github.com/JenkinsRobotics/JaegerAI/commit/cbdcc147c6e555275af6f984f6bea9619753eb69),
recorded at 2026-11-08T18:40:04Z, is “Unify conversation links and preserve
Gateway-owned cross-client context.” It changes 33 files, adding durable unread
markers, routes/events, operator-session proxying, execution-host display,
conversation links/selection and message actions/reactions.

Five paths overlap the candidate:

- jaeger_ai/core/gateway/server.py
- jaeger_ai/core/gateway/session_store.py
- jaeger_ai/features/webui/api/jaeger_sessions.py
- jaeger_ai/interfaces/ui/src/demo/StableDemo.tsx
- jaeger_ai/interfaces/ui/src/demo/StableDemo.test.tsx

StableDemo selection/navigation particularly overlaps the candidate's historic
session work. The previous no-runtime-overlap conclusion is obsolete.

[Commit 315f6ea](https://github.com/JenkinsRobotics/JaegerAI/commit/315f6eacbf99cab11b6a3edf3441a545140ca4c4),
recorded at 2026-11-08T19:27:19Z, points Connect Apps at the canonical Jaeger IDE
extension. It changes gateway connect_apps.py, its tests and the app registry,
correcting extension identity/package selection and registry-controlled setup
restrictions. Those three additional paths do not overlap this candidate; the
five earlier overlaps remain.

Connector comparisons confirm the latest observed cutoff is one commit beyond
cbdcc147, two beyond 25f3300 (36 changed paths), and four beyond the review base
(38 changed paths), all zero behind. Actual remote output, exact file inventory,
selected commit metadata/patches and structured comparisons are retained in
bundle evidence. Source inspection is not conflict resolution or combined tests.

## Attribution and next gate

GitHub records author/committer shuwalker for these upstream commits. Recorded
commit timestamps and account associations do not establish push/start times,
human versus agent involvement, causation, or whether separate work was active.
No successful remote write from this isolated work is recorded.

The current candidate and original branch must be preserved before reconciling
upstream in a separate isolated integration branch. Both sets of behavior need
careful overlap review, independent review and fresh affected tests. No combined
compatibility is claimed in this candidate's results. The next step is isolated
reconciliation, not a default-branch merge or runtime action.
Runtime-local work remains separate and must not be overwritten. A future live
release still requires its own data-preserving plan and explicit approval.
