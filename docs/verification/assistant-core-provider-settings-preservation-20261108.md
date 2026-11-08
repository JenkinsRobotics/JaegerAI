# Preserve CLI provider settings on failed reads

## Verified defect

The existing Settings Providers panel sends enabled/models updates through
PUT /v1/providers/cli/{id}. Its update producer read providers/cli.json through
a permissive display fallback: malformed, non-object, invalid UTF-8 or unreadable
content became an empty dictionary. A single toggle could then overwrite the
whole saved document with defaults and report success.

The producer now requests a strict writable snapshot. A missing file may still
initialize on first save. An existing unreadable or invalid root is rejected
before writing, with a static error and existing HTTP 400 response. Exact original
bytes remain untouched. Error text contains neither document contents nor
underlying exception detail. Read-only display fallback is unchanged.

This does not change authentication, CSRF, permissions or credentials. The
initial mask-placeholder overwrite hypothesis was not supported by the current
UI: provider controls send enabled/models, while catalog credentials are blanked
and individual configuration leaves are updated separately.

## Qualification

Frozen candidate 40e0a75bfeeaec4eec3df9944733b9fc73873825.
Patch SHA-256 cbbc4a1caa1d2e1bc3e94bff87a27bf25db9a3d9872cb6978e3063081fdcaaad.

- Before repair: 7 failures and 1 compatibility pass.
- Focused corrected suite: 43 passed. Three owned loopback bridge tests were
  initially excluded for test-process coordination, then separately passed with
  unchanged assertions. They use synthetic tokens/temp files and no real provider.
- Independent focused review: 44 passed, including 28 additional controls;
  5 VS Code cases were excluded from that independent in-process run.
- Independent hygiene: 9 passed. Simulated read/write/mkdir/replace failures
  preserve the original file and cannot report successful mutation.
- Integrated main preservation regressions: 8 passed. Source/tests match the
  reviewed candidate exactly. Critical lint and whitespace checks pass.

Tests use disposable synthetic configuration, mock detection and existing test
helpers. No actual credentials, provider executable, live account or Mac runtime
was read or changed. Upstream auth/CSRF was source-traced, not newly exercised by
these handler tests. Counts overlap; full integration is a separate gate.

The historical independent counts above were recorded in reviewer command
outputs, not separate retained log files. Their control files are included.
The later transaction report includes a fresh exact-final independent rerun
with complete saved logs.

## Remaining work at this increment

Strict enabled types and invalid nested target rows are a separate validation
increment. Concurrent read-modify-write loss and the shared cli.tmp path also
remain separate: a revision-bound atomic transaction must cover both reading
and mutation, not just replace the final write call. Temporary files may remain
after existing write failures. No comprehensive Settings validation, concurrent
writer safety or live UI acceptance is claimed here.

The existing atomic file helper is being evaluated for that follow-up without
changing its policy or silently retrying uncertain outcomes. Overall and every
tab remain PARTIAL. No runtime changes, merge, deployment or remote write occurred.

The later [provider validation increment](assistant-core-provider-settings-validation-20261108.md)
rejects nonboolean enabled values and malformed target-provider rows. It remains
separate from concurrent-writer safety and preserves this earlier failure record.
