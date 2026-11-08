# Revision-bound provider preference saves

## Verified defects

Two independent interleavings reproduced data loss in the existing provider
settings writer: a stale snapshot erased another successful field update, and
the fixed cli.tmp name allowed one writer to consume another's temporary file.
Both are distinct from malformed-file preservation and input type validation.
The original defects and desired-invariant fail-before controls are retained.

## Bounded producer correction

The provider updater validates requested fields, reads one exact raw snapshot,
parses strict UTF-8 without BOM, and hashes those same bytes. It uses the existing
unchanged mutate_json helper with that revision and a field-only transform. The
helper reads/checks the current revision and transforms/replaces the document
under its canonical write lock, using a unique temporary file.

A stale revision or busy writer returns an explicit sanitized conflict. There
is no automatic retry or stale whole-document replacement. Only the requested
provider fields change; unrelated values, original mode and historical cli.tmp
remain preserved. Missing files still initialize normally. Temporary files
created by the helper are cleaned up; unrelated files are not deleted.

An I/O error may occur after replacement, so the API says the save could not be
confirmed and asks the caller to reload. If saving succeeded but reading provider
status fails, the error says it was saved. Neither falsely promises that nothing
changed. Read errors, invalid inputs and conflicts remain distinct from these
postcommit outcomes. Error text does not disclose contents or underlying details.

The intermediate private _settings(for_update) branch became unused and was
removed after caller inspection. Its original read-only fallback remains. No
helper, permission, authentication, CSRF, provider command or automatic retry
policy changes. The package-qualified import remains lazy for the file-loaded
WebUI API module; normal packaging/launcher paths include that module and helper.

## Qualification

Frozen final candidate 34e5f2bdf056cbce17ddcff9f0c59b838e74a269.
Combined third-increment SHA-256:
031ee8a5eddc9ca332bd00906b3f1938f17560485d2bc225fdcfb444ceb7f924.

- Two original interleavings confirm the defective behavior. Desired-invariant
  regression before correction: 2 failed, 4 passed.
- Exact final focused suite: 80 passed; hygiene: 9 passed.
- Independent exact final: 89 passed, 5 VS Code tests excluded; hygiene: 9 passed.
  Real isolated subprocess writers against existing and missing documents each
  prove one successful save and one explicit conflict, retaining the winner.
  A fresh exact-final rerun also passed 89/9, with complete stdout/stderr,
  source/control hashes and a reproducible command file retained in the bundle.
- Four adversarial post-snapshot replacements preserve the externally changed
  bytes. Strict encoding, read failures, modes, unique temp cleanup, historical
  temp preservation, post-replace fsync and provider-status errors are covered.
- Integrated source/test bytes match the reviewed freeze. Final combined gates
  appear in the [combined report](assistant-core-combined-qualification-20261108.md).
  Counts overlap and are not a whole-package test total.

Controls use only synthetic files, owned temporary state and existing fixtures.
No real provider, credential, account or operator configuration is used. Existing
and corrected harness/import errors are retained with the successful runs.

## Boundaries

Cooperating writers must use the same canonical state/lock root. A noncooperating
external writer can still race between the final revision check and replacement;
this is not a universal filesystem compare-and-swap guarantee. No frontend
revision token was added, so it is not a new stale-form editing contract.

Read-only malformed-configuration fallback remains unchanged. Other Settings
fields and real platform/provider behavior are not comprehensively qualified.
Overall/tab acceptance remains PARTIAL. No runtime changes, merge, deployment or
remote writes occurred.
