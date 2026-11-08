# Owned-process loss at resident request seal

Runtime base: 747d41f2909340db436fe22e945c79ee70d9e014 (selected-agent handling plus stable-route default-lead journal). This increment changes tests only.

## Actual boundary

The existing OwnedGateway worker uses the real EntityRuntime, owner continuation, native run/effect store, work ledger, file tools, approval and TaskCard verifier. Only its model responses and fault barrier are scripted. A real authenticated UI proxy selects native:jaeger when creating a new chat; the actual handler pins that selection. The client does not supply `_owner_agent`. The journal identity is checked for the server-generated native lead authority.

The explicit Create request executes the existing CONTRACT-DURABLE scenario: work ledger, approved file write, readback, ledger completion and complete_task. The TaskCard must be completed_verified in the sealed result. No fabricated terminal rows or changed production defaults are used.

A nominated request/session-only wrapper stops before `_commit_owner_outcome`, or after that entire method returns. The latter is outside its atomic TaskCard/journal transaction. An external connection confirms the durable proof and absence of terminal projection before the test checks the marker PID against its live Popen child and invokes OwnedGateway.stop (SIGKILL+wait). The next two boots use the identical scratch state without the hook.

## Result

4 passed in 99.49s on the exact runtime base:

- After seal: request recovers completed once, exactly one completed turn.reconciled, immutable proof, unchanged assistant transcript on second restart.
- Before seal: execution_unknown after both restarts, no successful terminal event and no replay.
- After seal with authority digest drift: unknown, no successful projection/replay.
- After seal with request session drift: unknown, no successful projection/replay.

Every case produced exactly six original-request model calls and one file-write tool call. The saved four-case run compared original native effect rows through both restarts and file contents/mtime after the first restart. It did not directly recheck file bytes/mtime after the second restart; the strengthened regression below adds that missing assertion. Independent final SQL/log inspection confirms queued request model calls: one in the valid recovery case, zero in the three unknown cases. Unknown cases retain the queued request; valid recovery completes it through the existing startup drain. This is process-loss acceptance with scripted provider, not live-provider or desktop-client verification.

## Reproduce

With the external venv and state environment used by the repository runner:

JAEGER_WEBUI_UI_DIST=/workspace/shared/jaeger-ui-tenth/dist dev/scripts/run_tests.sh --integration -- --timeout=120 --basetemp=<fresh external scratch directory> -x dev/tests/jaeger_ai/core/test_owner_receipt_process_loss.py

Exact launcher: /tmp/jaeger-lead-process-crash-final-run.sh
Passing log: /tmp/jaeger-lead-process-crash-final-second.log
Passing fixtures: /workspace/shared/jaeger-20261108-test-temp/lead-process-crash-final-second
Independent final counts: /tmp/jaeger-lead-process-crash-evidence.json

Preserved developmental failures: the earlier d9 prompt was not actionable and did not create a TaskCard despite verified ledger/file evidence; the explicit Create prompt fixes the input rather than weakening the card requirement. The first 747 run recovered correctly but the test expected turn.finish; corrected to the existing startup turn.reconciled contract and retained exactly-once checks. Logs remain /tmp/jaeger-lead-process-crash-first.log and /tmp/jaeger-lead-process-crash-final-first.log.

No production code, default configuration, operator runtime, remote repository, or original fixtures were changed. No deadlines increased. All child processes ended through owned cleanup. Implicit unpinned first-turn routing remains deliberately outside journal coverage until routing commits; this test uses actual explicit selection.


## Strengthened regression, combined process rerun

After review, the same test now checks file bytes AND mtime after each restart,
zero initial assistant messages and exact final assistant counts/content/session,
original-request terminal events across every session, and queue status plus
exact provider counts after both restarts. Native evidence includes target-file
tool/effect records under any run or session, and provider calls are matched by
original request ID OR the scenario marker, so a replay with new identifiers
cannot hide behind original-run filtering. Targeted markers distinguish this
work from unrelated initiative traffic.

The saved 4/4 result above belongs to the prior assertion set. The strengthened
assertions have static checks and read-only saved-fixture consistency checks;
the refreshed four-case process suite has now passed after integration, as recorded below.
No second-restart file timestamp comparison is retroactively claimed for the
old run.

## Integrated source result

On production source 35100a1e477a5eaebc21cd4fc66f3f25b530f015, all four
strengthened SIGKILL cases passed within the combined HTTP run. The helper also
checks the original request status after each restart. An independent reviewer
approved that additional status assertion before the run.

Combined HTTP outcome: 49 passed, 1 failed, 3 excluded in 695.68 seconds.
The failure is test_new_chat_default_snapshot_survives_real_retry: after an
implicit unpinned first turn, retry incorrectly adds current _owner_agent identity
to the original immutable execution snapshot. The existing exact equality
assertion was not weakened. This is a separate producer regression and blocks
a green combined qualification; it does not negate the four passed kill cases.

Log: http-seventeenth-final.log. Fixture root:
/workspace/shared/jaeger-20261108-test-temp/http-seventeenth-final.
See [combined evidence](assistant-core-combined-qualification-20261108.md).
