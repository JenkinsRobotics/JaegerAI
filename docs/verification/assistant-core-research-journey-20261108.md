# Cooperative research report journey

This is test-only qualification of the existing Research path. Automatic source
evidence enforcement and factual research quality remain PARTIAL.

## Actual path exercised

An authenticated gateway webui caller creates a paused research proposal. The
normal owner-approval route authorizes the task. The owned worker runs native
ledger, search, extraction, file, terminal, readback and completion tools. Only
external model/retrieval responses are synthetic. The existing grounded-citations
CLI builds/checks the source ledger and produces the report; no task success or
completion receipt is inserted by the fixture.

Exactly four tool approvals use once, bound to the expected task/request:
three workspace file writes and the known fixture CLI command. Proposal approval
is separate. No persistent grant is added. Real owner-file SHA-256 verification
qualifies the saved artifact; its authenticated download matches exact bytes.
Ten successful native tool-completion events retain the correct request scope.
Source identity, title, URL, quotes, extracted page and ledger are preserved.

Documents uses real WebUI password login and CSRF-protected HTTP save/reopen.
The original artifact retains its trailing newline; model final/task.result and
the saved Documents body are normalized. The test checks those two byte/text
contracts separately rather than assuming they are identical.

After successful completion, the owned runtime stops and restarts. The document
identity/body, artifact bytes and source ledger persist. Proposal replay does
not invoke the model again or create another completed run. This is completed
result persistence, not interruption recovery during research execution.

## Negative evidence and deliberate limits

Missing or fabricated quotes, unknown references, mismatched URLs and malformed
ledgers are rejected by the existing citation checker. Unavailable retrieval is
distinct from valid empty results. A contradictory or unrelated claim with a
matching source/quote can still pass reference consistency. Citation consistency
is not entailment, factual truth, or proof that page content cryptographically
belongs to a URL.

The scripted model cooperatively invokes the grounding procedure. Ordinary
Research completion does not enforce it automatically. Proposal/approval are
actual gateway API calls, not rendered ResearchPage interactions or React goal
builder/navigation tests. The HTTP fixture disables optional skill smoke
subprocesses, without changing production defaults. No live sources/providers,
physical browser/phone, cold skill initialization or long-running research
status is qualified here.

At this increment, terminal approval presentation still truncates the command.
The test compares fixture-owned exact issued-command evidence before granting
the explicitly authorized synthetic action. That is not evidence that the user
could see the full command. A separate visibility correction is required.
The defect is independently reproduced without executing any command: two
commands sharing the first 200 characters but differing later display equally.

## Qualification and reproduction

Patch SHA-256:
bfabdde1d06e272edd63b1560db7a3e917252a2c8408dd1d2db01b0fe4f95ff2.
Only four dev/tests files change before this report. Independent review applied
the patch unchanged on edc0f01f6b9ab90b20b8a3a7673c7fcc71d9f583 and compared
4,725 non-test tracked files: no differences.

- Builder and independent reviewer: 3 qualification tests passed.
- Existing report/Documents regressions: 37 passed in each isolated checkout.
- Independent repository verification: 430 passed (136 Python and 294 IDE).
- Main integrated qualification/regression gate: 40 passed. Main repository
  verification also passed. These are fresh targeted gates, not a relabeling of
  the previous fifty-one-case combined HTTP run.
- Reused production UI inputs match 866 source files and 857 manifest inputs,
  source fingerprint 36612489016ec2283f86dcc22d435be6aa80478591ab9dcb4551833c7be0fc1f.
  This is build provenance, not a new browser rendering test.

Commands, complete output, source/approval/artifact event evidence and hashes are
retained with the review work. Earlier harness assumptions remain recorded:
result-wrapper trust parsing, registered web_extract name, missing built UI for
CSRF shell, and final-answer newline normalization. They are not hidden or
reclassified as production fixes. The strengthened final run is run-7.

Run the final suite with an external venv, isolated HOME/state/basetemp and the
verified production UI selected by JAEGER_WEBUI_UI_DIST:

```sh
python -B -m pytest -q -p no:cacheprovider \
  dev/tests/jaeger_ai/core/test_gateway_research_qualification.py \
  dev/tests/jaeger_ai/core/test_gateway_default_report_delivery.py \
  dev/tests/jaeger_ai/features/webui/test_document_persistence.py \
  dev/tests/jaeger_ai/features/webui/test_unified_api.py
bash scripts/verify.sh all
```

No production code, live runtime, real credentials, Mac installation, remote
branch or deployment was changed by this increment. Overall Research acceptance
remains PARTIAL.
