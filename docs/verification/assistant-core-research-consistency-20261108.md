# Research citation-consistency admission and completion

Isolated increment, not deployed. Captured baseline: `5e4df5843736541477980ca9f784ed47ca5fa848` (commit26 plus approved visibility candidate and explicit timeout fixture correction). No Mac runtime, upstream, or real-provider changes.

## Contract

Only ResearchPage opts into the fixed version-1 `citation_consistency` request. Server rejects null, unknown versions, extra fields, and substituted paths. Admission persists the contract in task payload and client-submission fingerprint, including effective task-specific artifact paths. Proposal edits, approval, continuation, restart, and replay preserve it. Worker arguments, result metadata and goal text cannot remove or mint it. Ordinary clients and historical prefix-only tasks retain their existing behavior and do not receive citation-consistency labeling.

The owner captures one verification root and resolves two designated paths below it: `research/<owner-task-id>/research-report.md` and `research/<owner-task-id>/sources.json`. The owner derives and persists the namespace at admission; clients and workers cannot redirect it. Namespace/file symlinks cannot alias another task. Directory descriptors are walked from the filesystem root using no-follow opens; one task-directory descriptor is held across both files, and each regular-file check and single read share the final file descriptor. Ancestor/leaf swaps cannot redirect reads or mix roots across the report/ledger pair. Malformed workspace roots return a non-verified result. Each file is read once. Validation, SHA256 receipts, and displayed/saved report text derive from those same byte snapshots. No later file read supplies result text. Worker summaries and `output` cannot substitute another result. Originating chat delivery and Research Save to Documents use the exact report text, preserving trailing whitespace and line endings.

The report requires nonempty inline numeric citations, a final `## Sources` section, matching reference IDs and HTTP(S) URLs, and matching nonempty evidence quotes in a version-1 JSON ledger. Comment/code/image/escaped citation markers do not establish inline citations. Unknown, duplicate, malformed, empty, missing and mismatched evidence cannot produce a verified sourced report. The owner retains files and partial work with a `needs_owner` outcome and an explicit non-verified primary result. Existing approval gates remain unchanged; tests approve only exact synthetic calls already inspected.

The standalone grounded-citations `--evidence` check also rejects zero citations or an empty ledger.

## Limits

These checks establish artifact/reference consistency, not factual truth, entailment, coverage of every claim, or authentic retrieval provenance. The ledger and report are worker-writable. A false claim with structurally matching citations deliberately passes a regression test. No factual-quality claim follows from `completed_verified`; Research labels it **Citation consistency checked** and displays the limitation.

The v1 report format is deliberately narrow and follows `render --style evidence`; HTML-bearing prose, other Markdown bibliography styles or multiline quotes are retained as non-verified instead of guessed. Files remain mutable after completion; owner hashes allow later artifact access to detect changed bytes, while task result retains the checked snapshot. Distinct tasks receive distinct artifact namespaces. This prevents accidental filename collisions; it does not create a new filesystem sandbox or revoke tools' preexisting workspace access. Immutable artifact storage is not introduced here.

## Evidence

Tests and logs are retained outside the repository at `/tmp/jaeger-research-contract-evidence`, `/tmp/jaeger-research-ui-contract`, and `/tmp/jaeger-research-contract-review`.

Original reproduction accepts missing citations, fabricated IDs and an unrelated scratch receipt; empty-ledger evidence verification also passes before the fix. Focused tests exercise strict admission, replay conflicts, proposal edits, approval, restart, yielded continuation, worker-metadata resistance, exact saved/delivered bytes, negative evidence cases and unchanged general/historical tasks.

Owned HTTP tests use real isolated Gateway/WebUI/task/tool/approval/SQLite/Documents routes with scripted model and retrieval boundaries and reserved `.invalid` URLs. They are not live-provider or rendered-browser proof. The retained no-mock UI build supplies only WebUI static assets. Focused React tests separately exercise the changed request, labels and save payload. Initial HTTP runs failed503 at the WebUI shell because the test used the wrong dist environment variable; corrected to `JAEGER_WEBUI_UI_DIST` and failures retained. An initial UI typecheck fixture omitted sibling IDE media declarations; corrected external copy and retained both logs.

Independent review found hidden/inline-code citation markers, invalid URL ports, and dictionary-stringified originating-chat delivery. Each was corrected with regression coverage before final validation. A subsequent independent review rejected candidate `7cbc977` for indented/unclosed/HTML code citations, trailing-slash URL equivalence, path-read symlink races, and unhandled self-symlinks. Its failing controls are retained; the final correction excludes non-prose markers, preserves URL path slashes, and uses pinned no-follow descriptor reads. A second review rejected `b05823e` because it reopened the root for each artifact and did not catch root-resolution errors; the final version pins the pair together and tests both issues.
