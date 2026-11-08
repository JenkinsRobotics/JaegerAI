# Document persistence regression verification, 2026-11-08

Scope: WebUI document CRUD only. Isolated Linux checkout based on
`291676589a7aa7885bc7d55ca1f499c8a0a39f64`. No runtime Mac, providers,
credentials, deployment, push, or migration involved.

## Repair

`jaeger_ai/features/webui/api/unified_api.py` now uses the existing core
`atomic_files._file_write_lock` and `_write_unlocked` for document transactions.
Read, exact revision check, and replace share a stable OS lock; delete uses the
same lock and fsyncs the parent directory. Writes use unique temporary files,
fsync, atomic replacement, and cleanup. The general `_write_json` and other
endpoint persistence paths are unchanged.

The document JSON layout and optional `expected_updated_at` field remain.
Frozen/backwards clocks advance `updated_at` using the next representable
float. Exact comparison rejects the preceding token, including differences
smaller than the old tolerance. Malformed/nonfinite tokens return 400, without
writing. Explicit null is invalid; omit the field for legacy unconditional
updates. Stored invalid revisions fail closed on save.

DELETE also accepts an optional JSON body with `expected_updated_at`; stale
requests return 409 with `current`, preserving the newer document. Existing
bodyless DELETE remains supported. Update-after-delete returns 404 rather than
recreating the ID.

## Evidence

Regression file: `dev/tests/jaeger_ai/features/webui/test_document_persistence.py`.

- Eight overlapping real threads: exactly one CAS winner, seven 409s, disk
  content equals the returned winner.
- Four independently launched Python processes: same assertion, with delayed
  reads to force overlap. A fresh process reads the exact persisted winner.
- Save/delete overlap: delete waits for the in-flight save, then removes the
  file; an old save cannot resurrect it.
- Independent process deletion blocks on the same file lock.
- Frozen and backwards clocks, invalid save/delete tokens, stale deletion,
  DELETE route parsing, and failed replacement preservation/temporary cleanup.

Fail-before used the final test file copied outside the repository, changing
only its `SOURCE` constant to a `git show` snapshot of the original API at the
base commit. **24 failed**. Thread/process overlap reproduced shared-temporary
file races or multiple winners; clock, revision-validation, delete serialization,
cleanup, and revision-bound deletion assertions also failed. The final rerun
replaces an earlier multiprocessing-spawn harness that could not import the
pytest module; final subprocess tests use independent Python interpreters.

Final focused check: **36 passed, 1 warning in 9.56 seconds** (24 new regression
cases plus 12 existing unified API tests). Command, from repository root:

```bash
export HOME=/tmp/jaeger-baseline-20261108
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/tmp/jaeger-baseline-20261108/pycache
export JAEGER_STATE_DIR=/tmp/jaeger-baseline-20261108/state
export PYTHONPATH="$PWD/packages/jaeger-agent:$PWD/packages/jaeger-os:$PWD"
/tmp/jaeger-baseline-20261108/venv/bin/python -m pytest \
  dev/tests/jaeger_ai/features/webui/test_document_persistence.py \
  dev/tests/jaeger_ai/features/webui/test_unified_api.py -q -p no:cacheprovider
```

Logs: `/tmp/jaeger-baseline-20261108/documents-final.txt` and
`/tmp/jaeger-baseline-20261108/documents-baseline-confirmed.txt`.
`git diff --check` passed. Pytest reports its existing asyncio fixture-scope
notice and unknown `cache_dir` warning because cacheprovider is disabled.
Aggregate verification is owned by the integrating task, not claimed here.

## Limits

File locks coordinate cooperating writers on the same host/filesystem with the
same canonical `operator_state_root()` lock directory. Tests set both
`JAEGER_STATE_HOME` (WebUI documents) and `JAEGER_STATE_DIR` (canonical lock root).
Writers with different canonical state roots targeting the same documents via
`JAEGER_STATE_HOME`, noncooperating external editors, network filesystem lock
semantics, and power-loss fault injection are not covered. Existing helper
lock contention timeout behavior is retained. No claim of globally repaired
persistence, runtime-Mac validation, or universal crash durability is made.

## Owned WebUI HTTP journey (additional acceptance)

`dev/tests/jaeger_ai/core/test_webui_document_journey.py` uses the existing
`OwnedGateway(tmp_path, webui=True)` harness, real HTTP handlers, cookie login,
and CSRF tokens. Its fixture prevents outbound provider/operator connections;
all document contents and login credentials are synthetic. The test explicitly
maps `JAEGER_STATE_HOME`, `JAEGER_STATE_DIR`, and `JAEGER_HOME` to the same scratch
root. It does not change the production launcher or shared fixture.

The first run failed at the unauthenticated-read assertion: expected HTTP401,
but urllib followed a login redirect to HTML200. Inspection showed an API-path
classification defect, **not an authentication bypass**: `check_auth` recognized
only `/api/` as JSON API requests, treating `/v1/documents` as a page. The narrow
repair in `api/auth.py` includes `/v1/` in the existing unauthorized401JSON and
profile-denied403JSON branches. Public paths, valid sessions, and ordinary page
redirect behavior are unchanged. A first unit-test expectation incorrectly
assumed `/login` instead of the existing relative `login` redirect; that test
was corrected to assert existing behavior, without changing the redirect.

The HTTP test now verifies:

- Unauthenticated document list returns401; authenticated no-CSRF create returns403.
- Actual HTTP create/read/save; exact Unicode content and revision.
- Stale PUT and stale DELETE return409/current and retain the exact winner.
- Independently read document JSON matches that winner.
- Stop/restart only the owned test child (both Gateway and WebUI); existing
  cookie authentication, identity, document content, and revision survive.
- After restart, no-CSRF DELETE returns403 and retains the document; DELETE
  with valid CSRF plus JSON revision body succeeds, followed by404 and no file.

Final documented-runner result: **1 passed in 13.89 seconds**, repeated after
an earlier successful run. External UI build is used only to obtain the server
HTML CSRF token; this is not browser/render/native acceptance.

```bash
HOME=/tmp/jaeger-baseline-20261108 \
JAEGER_VENV=/tmp/jaeger-baseline-20261108/venv \
JAEGER_WEBUI_UI_DIST=/tmp/jaeger-baseline-20261108/ui-final/dist \
JAEGER_STATE_DIR=/tmp/jaeger-baseline-20261108/document-http-state \
bash dev/scripts/run_tests.sh --integration -- \
  dev/tests/jaeger_ai/core/test_webui_document_journey.py --timeout=120 -ra
```

Eight new focused auth-classification cases verify `/api/` and `/v1/` JSON401
and profile JSON403, plus unchanged page redirects for ordinary, `/v10/`,
`/v1-lookalike/`, and `/api-lookalike/` paths. With existing CSRF and profile
regressions: **37 passed in 2.92 seconds**.

```bash
HOME=/tmp/jaeger-baseline-20261108 \
JAEGER_VENV=/tmp/jaeger-baseline-20261108/venv \
JAEGER_STATE_DIR=/tmp/jaeger-baseline-20261108/document-auth-state \
bash dev/scripts/run_tests.sh --unit -- \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_auth_api_path_classification.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_csrf_cookie_mutations.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_session_active_profile_authorization.py \
  --timeout=120 -ra
```

Logs: `/tmp/jaeger-baseline-20261108/document-http-journey.txt` and
`/tmp/jaeger-baseline-20261108/document-auth-regressions.txt`.
No first-increment core test file was modified. No full-suite, browser,
provider, native-shell, live-runtime, or deployment claim follows from these
focused results.
