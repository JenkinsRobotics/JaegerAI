# Background admission and recovery qualification

## Review status and exact source

**Overall product and every tab remain PARTIAL.** All 18 selected final qualification groups have explicit zero exits at the frozen source/test revision. Package structural and exact-byte checks also passed. These scoped results do not establish blanket product acceptance or deployment approval.

Repository: https://github.com/JenkinsRobotics/JaegerAI

- Preserved version13: `efb2d67f2035bac0cb92eb7ebf782938f2247654`.
- Admission source: `e44b31d0a09e9758b43d1e7191d27435467a4424`, independently
  approved within admission scope but **failed broad qualification**.
- Corrective core source: `95e303b1fa9e6a6fe7e90f1511d6fa779b249532`, independently
  approved against e44b31d.
- Pinned upstream: `a5f83f807db95d6a9cc1bf6949a46a39d9be90db`, after
  `315f6eacbf99cab11b6a3edf3441a545140ca4c4`.
- Reviewed workspace/UI/terminal source: `f9babc880c22016366c678520cbebc3028c76e34`.
- Combined source: `f331e9c055b97043cc0384c4187a84fd396647c8`, tree
  `0382beefa66b43c83dfe7e72a17ce85f7d4eb6ea`. This applies the corrective
  commit onto f9babc8 without adaptation; it is a historical intermediate source, superseded by the test-only correction below.
- Current source/test freeze: `ccda0c799445ab1480817eb0f7bac99e1c2f6704`, tree
  `0f37ec3c2564028b65f7d0668fca470cdf8d4cb9`, parent f331e9c. This independently
  approved test-only fixture correction leaves runtime, packages and scripts
  byte-identical to f331e9c. The final selected qualification groups below passed at this exact source/test freeze.
- The final documentation-only child commit, tree, branch and bundle hashes are recorded in the archive root `README.md` and `artifact-integrity.json`. They are not self-referenced inside this committed report.
- At the final read-only comparison on 2026-11-08, 22:02:19–22:02:27 UTC, canonical default/master was `4400be5aacbfe3f58d388ffb799d7f44bbf5f719`: three commits and 39 changed paths beyond incorporated `a5f83f8`, with eight candidate-overlapping paths. Those later changes are excluded and untested; compatibility with current master is not established. See `test-evidence/upstream-final-canonical-ls-remote.txt`, `test-evidence/upstream-final-compare-result.json` and `test-evidence/upstream-final-overlap-paths.txt`.

## Newly qualified admission scope

The new admission marker is issued by TaskOwner for supported **new client
native/default-lead tasks using configured instance defaults**. Callers cannot
self-grant it. Historical/unmarked tasks, explicit model/provider/options,
specialist/delegated and webhook paths retain their prior guarantees. An explicit
Research consistency contract can be carried by an otherwise eligible task;
this does not make every explicit execution configuration eligible.

Admission freezes task/child/parent identity, objective/version, native runner,
enabled pinned lead, effective provider/model/tier/absolute workspace, instance
route provenance, caller/tools, declared artifacts, exact Research contract and
task-specific artifact namespace. Per-attempt resolved execution and exact prompt
are committed with request admission and the current Gateway lease. Checks cover
actual dispatch arguments, session metadata and resolved agent, not only a
separate reread of configuration. Unresolved or changed authority fails closed.

The corrective commit retains the **original input fingerprint before resolving
defaults**. Exact nonce-free replay returns the original task without re-resolving
mutable defaults, recreating approval or overwriting a legitimately edited
objective. Changes to caller, objective, tools, execution choices, proposal mode,
artifacts or Research contract conflict. Replay does not authorize execution:
changed defaults can still prevent subsequent approval.

## Returned-slice continuity and source exclusivity

An active native lifecycle alone does not prove that a producer is still busy.
A returned, yielded slice may retain an active native run. Bounded same-process
continuation requires the exact prior contract, current native PID and saved
Gateway lease including start generation, exact request/task/native bindings,
no unfinished source operation, settled effects and qualified children.
The synthetic two-slice journey completes verified with the original native
trajectory. Old-lease/cross-restart active reuse lacks that proof and pauses.

Every native bind checks protected source task/request pairs across **all retained
native run IDs**, inside its write transaction and before a receiving guard can
mutate state. Omitted/unmarked guards and foreign receivers cannot borrow those
IDs. Only exact TaskOwner-authorized source pairs permit transfer or same-request
rebinding. Legacy sources are not retroactively upgraded.

This is an admission and continuity prerequisite, **not a background terminal
journal**. Background owner-request journal eligibility remains unchanged.
Task-row creation precedes child-session creation; a crash between them can
conservatively pause. Registry, configuration and native-run stores do not form
a universal atomic snapshot. Direct qualified-child checks do not establish a
transitive descendant terminal-sealing protocol.

## Interrupted Research: retained evidence, no automatic replay

The test-only baseline increment `c9f5989ff9dd6bcb10a9bb2c4b2b30d9c78553b3`
kills an owned Gateway at two real process boundaries: after four returned native
tools, and after eight tools including report/ledger creation and readback but
before completion. Two replacement Gateways reopen the same owned state. Each
restart has a bounded three-second observation window, not an indefinite claim.

Task/request/child identity, admitted contract, approvals, tool receipts and
saved bytes survive. The request becomes `execution_unknown`; the task becomes
`paused` for effect reconciliation. Attempts, provider/tool calls and completion
messages do not advance. An existing report is not promoted to verified merely
because it exists. Exact POST replay replays admission, not effects.

The strengthened interruption run passed 2 cases; independent `test-evidence/interruption-review-results.log`
passed the same 2 cases in 45.56 seconds. Related corrected Research/recovery
coverage passed 52. Initial related HTTP failures were missing-built-UI 503s,
retained separately; using the source-matched prior build corrected that setup.
Subsequent admission reviews also retain the two interruption controls.
Unattended interrupted Research continuation remains unsupported.

## Workspace, navigation and terminal corrections

Pinned upstream adds persistent sidebar disclosures, compact summaries, tabbed
tools/sidechat, workspace files/changes and initial page/schedule controls.
Reconciliation retains exact opaque historic/agent links, unread behavior,
settings and task navigation. Outputs and artifacts remain reachable, while an
empty selection cannot list global artifacts. Late output responses cannot
replace a newer selection.

A late fork result can enter Recents but cannot steal navigation or dismiss a
newer menu, including navigation away and back. Terminal operations and output
attachment revalidate current session/profile authority; streaming rechecks
buffered events and idle intervals and stops after revocation. Producer registry
keys preserve valid whitespace, slashes and Unicode without trimming. Invalid
keys and mismatched stored ownership reject before reuse/control or capacity
side effects. Legacy session results require exact identity and active-profile
ownership; Gateway resolution retains its trusted-workspace checks.

These checks use component tests and synthetic terminal owners. No real PTY,
rendered browser/phone or native-host acceptance is established.

## Evidence ledger: keep narrow and broad results separate

Counts overlap and must not be summed as unique coverage.

- e44b31d admission-only independent review: 85 adversarial/unit and 54
  process/compatibility passes; repository verification passed.
- e44b31d broad qualification: durable **559 passed, 1 failed**; owned HTTP
  **58 passed, 2 failed, 3 excluded**; Research **85 passed, 1 failed**.
  Passing focused checks did not qualify this candidate.
- The failures included an obsolete artifact fixture lacking a persisted
  canonical lead and supported defaults, an obsolete empty-workspace assertion,
  and a **genuine nonce-free post-restart HTTP 409 replay regression**. The
  first two do not explain away the third.
- 95e303b retains and strengthens original approval, anti-forgery, byte/readback,
  two-restart and scope-drift assertions. Independent orders passed 116 and 130
  cases, including 14 new replay-authority probes; both original HTTP journeys
  passed, and repository verification passed. Import-order mock leakage was
  corrected by patching/restoring both consuming identity-helper references.
- f9babc8 independent terminal/workspace/backend review: 85 passed. Approval is
  restricted to that scope, not all core behavior.
- Independent full UI at `f919ca097392d545f972c162ab4be5afe8071b0d`: **956 tests
  in 207 files**; theme, TypeScript, Vite and no-mock checks passed. Source SHA-256:
  `765e79abec237e156dc7ebf1b7623e76dad71eb24486476bfa960bbfc75a7aa0`.
  The 881 tracked UI/shared inputs are unchanged through f9babc8 and the combined
  correction; the combined comparison also matches 137 built files. This is
  **source-identical reused evidence, not a fresh combined UI run/build**.
- Both independent adaptation reviews approve exact combined f331e9c within
  their respective scopes: the core correction matches 95e303b, UI/features match
  f9babc8, and 73 fresh mocked backend controls pass. The 881 UI/shared inputs
  still match the reused full build. This does not replace full combined gates.
- Final globally serial selected gates all exited 0; the complete ledger is below.
  The earlier f331e9c production run has **87 passed, 1 failed** in
  `dev/tests/jaeger_ai/features/test_voice_session.py::test_gateway_client_round_trip_against_the_real_gateway`:
  `Admitted default workspace changed; no tool dispatch`. A fresh-state isolated
  rerun passed 1/1; that did not qualify the aggregate.
- Deterministic fixture pollution was subsequently confirmed: admission read an
  unrelated prior `_instance`, while patched `get_singleton` returned a different
  no-layout fake. Production correctly refused the mismatched authority. The
  ccda0c test-only correction binds both singleton surfaces, parameterizes prior
  state and asserts that no workspace/default marker is borrowed. Independent
  checks passed 62 cases, then 71 reversed-order/hygiene cases, retaining the
  original real-socket/result assertions and workspace-drift refusals. Production
  authority checks were not weakened.
- Initial f331e9c durable/background pytest summaries report 564 and 58 passes,
  but their evidence wrappers exit 2 after a runner syntax error. Those attempts
  remain incomplete gate evidence. The stopped-before-HTTP sentinel is also
  retained, not a passing HTTP run. Fresh globally serial execution at ccda0c with immutable runners and explicit zero exit statuses is recorded below.
  The final fresh runs below supersede their qualification status without changing those historical outcomes.
- The root wheel and sdist were rebuilt at ccda0c. Each matches 27 selected changed runtime inputs and 137 source-matched UI files byte-for-byte. All 10 package archives passed structural/provenance checks; eight unchanged companion archives were retained after equality of 1,950 package source inputs to ce03f21. See `test-evidence/final-archive-proof.json`, `test-evidence/final-package-source-equality.json`, `test-evidence/final-logs__packages.log` and `test-evidence/final-logs__finalize-resume-v2.log`. These are archive provenance checks, not installation or native-runtime acceptance.
  Root archive verification is scoped to packaged Python/configuration and built UI inputs. IDE JavaScript, including controller.js, is intentionally excluded by the package configuration; root archives are not an IDE extension package or installed IDE acceptance. The review Git bundle preserves complete source and original commit/merge history.

## Final selected qualification ledger

All 18 groups below ran serially against ccda0c with explicit zero exits. The
aggregate ledger is `test-evidence/final-qualification-resume-v2.json`. Commands
and runner hashes are retained alongside the logs. Counts overlap.

- **verify**: 434 component checks within aggregate verification; overlaps other groups; exit 0. `test-evidence/final-logs__verify.log`; `test-evidence/final-results__verify.exit`.
- **production**: 89 passed; exit 0. `test-evidence/final-logs__production.log`; `test-evidence/final-results__production.exit`.
- **security**: 203 passed, 2 skipped (macOS seatbelt); exit 0. `test-evidence/final-logs__security.log`; `test-evidence/final-results__security.exit`.
- **durable**: 564 passed; exit 0. `test-evidence/final-logs__durable.log`; `test-evidence/final-results__durable.exit`.
- **background**: 58 passed; exit 0. `test-evidence/final-logs__background.log`; `test-evidence/final-results__background.exit`.
- **order1**: 88 passed; exit 0. `test-evidence/final-logs__order1.log`; `test-evidence/final-results__order1.exit`.
- **order2**: 88 passed; exit 0. `test-evidence/final-logs__order2.log`; `test-evidence/final-results__order2.exit`.
- **terminal**: 78 passed; exit 0. `test-evidence/final-logs__terminal.log`; `test-evidence/final-results__terminal.exit`.
- **ide**: 294 passed, 5 skipped; exit 0. `test-evidence/final-logs__ide.log`; `test-evidence/final-results__ide.exit`.
- **http**: 60 passed, 3 deselected, 668.67 seconds; exit 0. `test-evidence/final-logs__http.log`; `test-evidence/final-results__http.exit`.
- **research-resume-v2**: 86 passed, 61.51 seconds; exit 0. `test-evidence/final-logs__research-resume-v2.log`; `test-evidence/final-results__research-resume-v2.exit`.
- **approval-resume-v2**: 98 passed; exit 0. `test-evidence/final-logs__approval-resume-v2.log`; `test-evidence/final-results__approval-resume-v2.exit`.
- **settings-resume-v2**: 80 passed; exit 0. `test-evidence/final-logs__settings-resume-v2.log`; `test-evidence/final-results__settings-resume-v2.exit`.
- **provider-resume-v2**: 207 passed; exit 0. `test-evidence/final-logs__provider-resume-v2.log`; `test-evidence/final-results__provider-resume-v2.exit`.
- **cognition-resume-v2**: 120 passed; exit 0. `test-evidence/final-logs__cognition-resume-v2.log`; `test-evidence/final-results__cognition-resume-v2.exit`.
- **specialist-resume-v2**: 1 passed; exit 0. `test-evidence/final-logs__specialist-resume-v2.log`; `test-evidence/final-results__specialist-resume-v2.exit`.
- **procedure-resume-v2**: 31 passed, 1 deselected; exit 0. `test-evidence/final-logs__procedure-resume-v2.log`; `test-evidence/final-results__procedure-resume-v2.exit`.
- **extra-resume-v2**: 132 passed; exit 0. `test-evidence/final-logs__extra-resume-v2.log`; `test-evidence/final-results__extra-resume-v2.exit`.

The initial final-source `test-evidence/final-logs__research.log` was interrupted
without an exit record and is not a passing result. The distinct
`research-resume-v2` log/exit above is the completed qualification. The original
failed f331e9c production and nonzero wrapper records remain separate.

UI provenance is recorded in `test-evidence/final-ui-reuse.json`; package and
finalization exit records are `test-evidence/final-results__packages.exit` and
`test-evidence/final-results__finalize-resume-v2.exit`. The bundled `artifact-integrity.json` records source identity, documentation-only
changes, parent-history replay and bundle/diff hashes. Exact review-bundle import
is recorded in `test-evidence/final-bundle-replay.log`. After packaging, ZIP CRC
and every manifest member hash are checked. The post-build receipt is retained
with the packaging evidence outside this ZIP; the delivery caption supplies the
ZIP SHA-256. The bundle preserves the complete post-baseline commit/parent graph
and merge history, not upstream history before the shallow baseline. These
review-archive checks are distinct from the package archive results.

## Rejected snapshots and retained failures

Rejected admission snapshot `452ae4474e6109baa1430e14f38cc1efe4050f86` lacked
reverse-source borrowing protection and was superseded by e44b31d. The latter's
broad failure remains a failure despite its scoped approval. Initial workspace
merge `c74170904857124480b3eda83717c1d71888f960` failed late-fork, terminal scope
and opaque-ID probes despite passing its build/component suite. Intermediate
f919ca0 fixed those route/UI defects but still needed producer-key and legacy
profile corrections in f9babc8. Earlier failures and probes remain retained.

The earlier `test-evidence/admission-21-source-final-verify.log` stopped at the IDE aggregate stage;
its captured failure output was suppressed by the runner. Its cause remains
**unknown**, not proven storage failure or flakiness. No-change direct and
aggregate reruns passed; they do not retroactively turn that run into a pass.
Other earlier fixture, polling, missing-assets and storage failures retain their
own recorded causes rather than sharing this unexplained classification.

## Review and release boundary

Citation consistency binds checked report/ledger bytes. It does not establish
factual truth, entailment, authentic retrieval or real-provider quality. No
browser/phone paint, real PTY/native host, voice/media, installation or deployed
acceptance is claimed. Optional package coverage remains incomplete. Framework
evolution remains deferred.

GitHub organization write access remains blocked. No PR, remote CI, default
merge or deployment has occurred. The baseline's data-preserving deployment and
rollback proposal remains a proposal: fresh runtime-state comparison, preservation
of local work/data and separate approval are still required before cutover.

## Source and selected evidence references

Source identity above fixes the meaning of these repository-relative paths.
The archive-relative filenames below identify the retained recorded runs. No raw runtime state is a deliverable. `test-evidence/evidence-selection.json` records the content-selection scope and synthetic fixture limits; it is not universal secrets detection. Synthetic test data, fake providers, local loopback endpoints and isolated test directories are test fixtures, not evidence of real-account acceptance.

- Admission and replay: `jaeger_ai/core/tasks/background_admission.py`,
  `jaeger_ai/core/tasks/owner.py`, `jaeger_ai/core/gateway/owner_receipts.py`,
  `jaeger_ai/core/gateway/session_store.py`, `jaeger_ai/core/gateway/server.py`.
- Admission regressions: `dev/tests/jaeger_ai/core/test_background_admission_contract.py`,
  `test_background_yield_completion.py` and `test_background_yield_lifecycle.py`
  in the same directory.
- Original journeys: `dev/tests/jaeger_ai/core/test_gateway_default_report_delivery.py`,
  `test_gateway_owned_process_contract.py` and `test_task_artifact_default_scope.py`
  in the same directory.
- Interruption: `dev/tests/jaeger_ai/core/test_gateway_research_interruption.py`
  and `dev/tests/fixtures/research_contract.py`.
- Workspace corrections: `jaeger_ai/interfaces/ui/src/demo/StableDemo.tsx`
  and `StableDemo.test.tsx`; terminal implementation:
  `jaeger_ai/features/webui/api/route_terminal.py` and `terminal.py`;
  regressions: `dev/tests/jaeger_ai/features/webui/test_gateway_terminal.py`
  and `test_terminal_owner_identity.py`.
- Admission collection: `test-evidence/admission-21-source-final-verify.log`, `test-evidence/admission-23-ide-repro.log`,
  `test-evidence/admission-24-source-verify-rerun.log`, `test-evidence/admission-30-default-report-correction.log`,
  `test-evidence/admission-34-replay-final-journeys.log`.
- Corrective independent controls: `test-evidence/admission-review-21-correction-units-order1.log`,
  `test-evidence/admission-review-23-correction-units-order2-replay.log`, `test-evidence/admission-review-22-correction-http.log`,
  `test-evidence/admission-review-24-correction-verify.log`.
- Failed e44b31d broad qualification: `test-evidence/failed-admission-logs__http-restart-repro.log`.
- Workspace independent controls: `test-evidence/workspace-review-build-f919ca0.log`, `test-evidence/workspace-review-backend-f9babc8.log`,
  `test-evidence/workspace-review-terminal-owner-repro.log`.
- Interrupted Research controls: `test-evidence/interruption-final-interruption.log`,
  `test-evidence/interruption-related-with-assets.log`; independent interruption collection: `test-evidence/interruption-review-results.log`.
- Combined qualification: `test-evidence/failed-combined-logs__production.log`, `test-evidence/failed-combined-logs__voice_repro.log`, `test-evidence/failed-combined-logs__durable.log`,
  `test-evidence/failed-combined-logs__background.log`. Final-source gate and package records are listed in the ledger above; these combined records preserve the earlier failed/incomplete attempt.
