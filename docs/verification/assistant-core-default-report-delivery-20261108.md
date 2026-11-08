# Default-workspace report delivery, 2026-11-08

## Scope

This is a test-only increment on production source
5fb71c393b7a27d717f7776855f9f9fbfa4ee9c5. No production code or fixture behavior
changes. The new test uses the existing scripted model boundary and a real
owned Gateway, SQLite task/receipt stores, approvals, native file tools,
work ledger, TaskCard verification and artifact routes.

It qualifies report delivery and recovery, not the factual quality of research
or citation support. Overall and every tab remain PARTIAL.

## Real acceptance journey

The test creates an ordinary parent session with no explicit workspace and
submits a goal-only task over Gateway HTTP. It does not fabricate terminal
rows, insert verification receipts, substitute an explicit project, or change
configured authority to make the test pass.

- Exactly one approval must identify files.write_file, the intended relative
  file, task/request/child session, native agent and parent session. Only that
  approval receives decision once; any unrelated or repeated approval fails.
- Actual native execution performs work_ledger, write_file, read_file,
  work_ledger, complete_task: five unique successful tool call pairs and six
  provider calls, all bound to the expected task attempt.
- Owner verification records the real file SHA-256 and checked default root.
  The authenticated catalog returns one readable reference without exposing
  the private root. Downloaded bytes and digest match exactly.
- Missing and invalid authentication return 401; an authenticated a2a caller
  receives 403 for both catalog and bytes. The authorized CLI succeeds.
- Restart preserves entity identity, artifact identity, exact report bytes,
  one assistant delivery and no duplicate attachment. Exact task replay returns
  the same task. Provider logs, all tool events, request receipt, file inode,
  timestamp and size remain unchanged, with no pending approvals.
- With the owned process stopped, the test moves only its disposable workspace
  intact and rebinds the default location through a symlink. The new resolved
  root does not gain access to the old receipt: catalog omits it and the old URL
  returns 404. Original bytes remain intact; no additional execution occurs.
- Cleanup checks that the test's own Popen process stopped. No broad PID cleanup,
  unrelated process signal, live runtime or operator data is involved.

## Evidence

Independent strengthened test: 1 passed in 19.53 seconds; hygiene: 9 passed.
The integrated main run of the identical test: 1 passed in 19.69 seconds.
The test SHA-256 is
4d15be0564a45482137accdbd4f2d3a89321feda7a13e3489d297b9aa6dcc015.

The prior nineteenth combined source remains the production baseline: 50 owned
HTTP cases with 3 infrastructure exclusions, 558 durable/artifact checks,
430 repository checks, 75 production-path, 203 security with 2 skips and 120
runtime/commitment checks. Those are not relabeled as a new 51-case aggregate.
No production bytes changed for this additional journey.

Preserved initial fixture errors: declaring explicit artifact paths with an
empty workspace is rejected by admission; instance-mode tools strip the
workspace/ prefix rather than create a nested workspace directory; scope drift
may omit the old artifact rather than retain an unreadable catalog entry.
The final test follows these existing contracts and retains denial assertions.
The initial test also approved every pending item and did not compare tool events
after restart; independent review strengthened both gaps before acceptance.

Reproduce with the existing isolated venv and external HOME/state/cache paths:

```sh
python -m pytest -q --timeout=120 \
  --basetemp=/path/to/fresh-external-test-state \
  -o cache_dir=/path/to/external-pytest-cache \
  dev/tests/jaeger_ai/core/test_gateway_default_report_delivery.py
```

Never reuse retained basetemp evidence: pytest clears that directory. Source,
commands, original failures and final logs are retained in the cumulative review
evidence. Optional skill smoke subprocesses remain disabled only by the unchanged
owned-test harness; cold production initialization is not qualified.

## Research source-support boundary

A separate deterministic audit traced ResearchPage's ordinary task proposal,
web_search output and owner verification. Search preserves returned URLs and
separates an unavailable backend from a responding backend with no results.
Seventy existing owner/outcome/search controls passed.

A source-free answer alone fails verification. The same source-free content in a
fresh file with a correct digest can reach completed_verified, because this
contract verifies artifact bytes. It does not prove citations support the text.
The existing grounded-citations procedure supports source ingestion and evidence
consistency checks, but the ResearchPage task/owner path does not invoke that
contract automatically. No new source-verification guarantee is claimed here.

Next source-handling acceptance must trace retrieval through that existing
procedure, preserve URLs/evidence in the saved report, exercise unavailable and
invalid-source outcomes, and distinguish consistency from factual truth. Actual
provider quality, rendered browser/phone, native host and external accounts remain
unqualified. No permissions, runtime, GitHub, merge or deployment action occurred.

The repository's full deterministic verification entrypoint was rerun after
integrating this new test: 430 checks passed. Critical Python lint and whitespace
checks also pass. The final production source remains byte-identical to the
nineteenth candidate, so its broader production/security/durable/package/UI
results are reused with that explicit qualification rather than rerun claims.
