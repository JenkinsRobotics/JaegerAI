# Recognized provider credential diagnostics

## Verified failures and correction

Returned provider failures and raised/chained exceptions reached the gateway's
terminal handler as raw text. It logged the full traceback, settled TaskCards,
and persisted failed request/SSE results without applying the shared redactor.
The UI renders that error field. Machine log tail also exposed URL userinfo,
and nested native receipt diagnostics could bypass the top-level error field.

The gateway now sanitizes recognized credential forms before task settlement,
terminal persistence and logging. The entire formatted traceback is sanitized,
without subsequently attaching the original exception through exc_info. Useful
HTTP status and category text remain readable. Machine log tail reuses the
shared text sanitizer while preserving its existing patterns.

The shared sanitizer covers the tested quoted/escaped assignments, Bearer/Basic
schemes, explicit Authorization tuple/array representations and URL userinfo.
URL matching is limited to the authority section so an email-like query or
fragment does not invent a different masked host. Plain authentication guidance
is not treated as a token merely because it mentions an auth scheme.

## Operational receipts are not just display data

Native receipts feed cancellation, exception recovery and reconciliation. The
initial generic recursive redactor wrongly masked token-usage counts and author
metadata. Independent real completed-receipt tests caught that regression; that
candidate was rejected despite otherwise passing focused/security/verification
suites.

The final receipt-specific copy sanitizes diagnostic subtrees and exact
credential-labelled values. Structural Authorization pairs are masked only in
diagnostic/header context. Status, identity/control fields, accounting, author
metadata, successful reply text and ordinary operational pairs remain intact.
The original NativeTurns SQLite proof is not rewritten. Retaining the source
proof alone was not enough: corrected consumer behavior is also tested.

No permission, authentication, approval, execution or retry policy changes occur.
Failure, cancellation, unknown and completed status handling retain their
existing meaning. No successful answer is recorded for the failed-turn fixtures.

## Evidence

Final independently reviewed candidate:
0c5b86f95d29da65bc58ea337afb091c397e56c6, based on the twenty-third increment.
Combined patch SHA-256:
c99f269bb5ce200e073edee80b618ddaf8d98d555d725a290b89aea5fad51e65.
The isolated main integration also retains the separate twenty-fourth increment.

- Initial gateway probe: 3 failures. Machine URL and nested native receipt
  probes independently fail before their corrections. The expanded original
  production-file baseline records 17 failed and 2 passed controls.
- The generic receipt-redaction candidate, 394a764, was rejected for actual
  completed recovery/reconciliation metadata loss. Its passing suites remain
  separate from those failed controls.
- The narrowed a0d12a1 candidate fixed that loss but still missed explicitly
  labelled short header pairs and distorted a URL query/fragment containing @.
  All 10 added controls failed before the final correction. These records remain.
- Final builder aggregate: 207 passed. Independent exact-final aggregate:
  272 focused/adjacent passed; security 203 passed with 2 macOS-only skips;
  repository verification 430 passed (136 Python and 294 IDE).
- Tests reopen actual request SQLite/history/replay and inspect task results,
  event-bus SSE payloads and captured logs. Real NativeTurns completed receipts
  exercise exception recovery and reconciliation while preserving original data.
- Main's integrated provider/adjacent gate passed 207 tests. The later combined
  qualification report records all integrated gates and source/archive checks.

All fixtures use synthetic dummy values and disposable state. Model/provider
results are controlled. UI error mapping was source-traced, not browser-rendered.
Counts overlap and are not a full-repository test total. A test-authoring error
using model_dump instead of to_dict was corrected and retained separately from
production failures. Full commands, logs, controls and freeze hashes accompany
the review bundle.

## Limits and remaining acceptance

This is recognized diagnostic-pattern redaction, not a fail-safe category-only
error contract or a universal secret detector. Arbitrary opaque, unlabeled or
unrecognized encoded values may evade it. Successful text, nondiagnostic
metadata and historical records are outside the scrub scope. Original native
proof is preserved, not migrated or retrospectively cleaned. Other logging
producers are not comprehensively audited.

Settings inspection found no additional bounded exception defect: existing
provider configuration errors are generic, and discovery returns exception
class names rather than raw credentials/endpoints. This is a source/fixture
finding, not comprehensive Settings or real-account certification.

Chat, Machine, Settings and overall product acceptance remain PARTIAL. No live
provider, rendered browser, native Mac application, runtime update, merge or
deployment was performed. Existing operator data and local runtime work remain
untouched.
