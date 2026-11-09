# Bounded background terminal-recovery qualification

## Current combined qualification, 2026-11-09

Read [Foreground Stop and Machine observation qualification](foreground-machine-qualification-20261109.md)
for the current combined handoff. The final documentation-only commit and tree are
identified by the handoff root README and `artifact-integrity.json`.

Foreground backend gates ran at a286; current Machine/UI/build/verification ran at
cfb. Exact non-UI source equality supports transfer, not a fresh cfb backend run.
The earlier process 17-pass/1-failure readiness result, isolated 1-pass diagnostic
and controlled 18-pass rerun all remain distinct, with cause unresolved. Current
bounded-worker UI is 973 tests/208 files, including all nine navigation controls;
earlier unrestricted 970-pass/3-failure and serial 973-pass attempts remain distinct.
Original802 broad 18-group and older UI956 results are historical only.

The foreground repair prevents false terminal cancellation reports; it does not
stop arbitrary native descendants. The Machine repair makes inventory/Safety
observations and refresh truthful; it does not qualify native permissions or
provider execution. All tabs remain **PARTIAL**. No installation, deployment,
remote PR/CI, rendered browser/phone, audio or real-provider acceptance is implied.

The remainder preserves the earlier report's chronology and source scope. Any
“current” or “final” claims below refer to that report's own historical snapshot,
not this combined handoff. Earlier foreground/Machine defect descriptions are
superseded only for the exact repaired scope in the linked report.

## Status and source boundary

**Overall product and every tab remain PARTIAL.** The isolated implementation has
passed scoped builder gates and independent review. All 18 selected combined groups have explicit zero exits at the original combined source. Root package build and final provenance checks also exited 0; exact scope and reuse are recorded below. Isolated and version14 results remain attributed to their own source revisions.

- Review baseline: `ff71bb769bc56e4c6d7be6d540a86be73e291e07`.
- Preserved admission/source baseline: `ccda0c799445ab1480817eb0f7bac99e1c2f6704`.
- Isolated implementation: `a12b26bbd7667ea4535633e36bbfc12d059e2f81`.
- Isolated tree: `be2a8fa0678401c122d63e8b55cac5cfea2df34e`.
- Isolated parent: `c7cbffab032d6de0655df3c038cb8bfc3b63d8e6`, a held candidate.
- Combined source: `80277648c228e06d005d83c44b7f21d4f360506d`.
- Combined tree: `51ef51fe3a56d513a5191796f9f38bd4d6fcf83b`.
- Combined parents: isolated a12b26b and version14 documentation child 647f2b8.
  There are 51 commits after the review baseline. Five intended verification
  documents differ from a12b26b; the other 5,544 tracked paths are identical.
- Final portable documentation child and tree are recorded in root README and `artifact-integrity.json`; this report attributes qualification to the original source, not its mapped export identity.

Incorporated upstream remains `a5f83f807db95d6a9cc1bf6949a46a39d9be90db`.
The completed read-only comparison on 2026-11-08 at 22:02:19–22:02:27 UTC observed
canonical default/master `4400be5aacbfe3f58d388ffb799d7f44bbf5f719`, three commits
and 39 paths later, with eight candidate-overlapping paths. Those later changes
are excluded and untested. Current-master compatibility is not established; no
new upstream comparison or reconciliation is implied.

## What is newly implemented

Schema19 enrollment records guard newly eligible native/default-lead background
attempts. Proof version4 is a narrow terminal-result recovery contract, not
permission to rerun arbitrary interrupted work. Only an owner-admitted attempt
with exact immutable authority and guarded producer enrollment can seal.

The awaited producer must return a nonempty final output. Independent verification
checks its objective, report/artifact bytes, complete accepted operation graph,
lineage, ownership, checkpoints and settled effects. Exact task/session/agent,
tools, goal, effective authority and current Gateway PID/generation must still
match. Empty effect ledgers or worker status labels are not completion proof.

Only after these checks does the producer legally complete every retained
accepted native root. It rechecks artifacts, authority, fingerprints and native
evidence before writing a v4 seal. Sealed roots are already completed and
ownerless, so a subsequent real RecoveryManager boot scan does not mistake them
for active orphaned work. Yielded slices remain active. Incompatible lifecycle
transitions are refused rather than forced into completion.

The canonical graph also supplies a negative veto across all attempts for normal
completion and Stop. Pending effects or unresolved owned children, including
rotated earlier roots and qualified separate child-request roots, keep the task
paused/unknown. A cancellation request is retained, but does not make unresolved
effects safely cancelled. Clean Stop can still cancel. Truncating mutable history
does not erase enrolled roots or bypass the veto.

Settled delegated trees may complete through ordinary supported paths but remain
ineligible for a seal. Historical/unmarked and other execution modes acquire no
new enrollment or replay authority. Native completion without a v4 seal remains
unknown and is not replayed. No automatic continuation of unsealed interrupted
work is implemented.

## Recovery and migration boundaries

Exact sealed results can recover after loss before request projection, without
new producer/tool/effect calls or duplicate terminal events. Normal and recovered
Research results retain the same independently checked report/artifact bytes.
Loss before sealing, including after native completion, cannot manufacture a seal
or authorize execution. Store owners and boot/reconciliation paths must retain
unknown/paused evidence in those windows.

Actual older fixtures were generated using their unchanged original sources.
Schema17 no-journal work can settle or be negatively vetoed where existing proof
suffices, but never gains replay authority. Actual schema18/v2 and schema19/v3
seals remain unsupported after migration. Journal bytes stay unchanged and there
is no backfilled enrollment or fabricated v4 proof. An old enrollment row is not
itself a new completion proof.

There is no single transaction spanning Gateway and native SQLite stores.
Fingerprint revalidation is not a universal guarantee against arbitrary external
mutation after the last check, hardware failure or power loss. Existing default/
tier drift can conservatively preserve a historically valid projection while
current TaskOwner dispatch/reconciliation stays paused; it is not a new grant.

## Isolated exact-source evidence

At a12b26b, the immutable sequential builder runner recorded explicit exit0 for:

- Unit regression: 354 passed, 727 warnings, 111.07 seconds.
- Repository verification: all sections passed.
- Smoke: 170 passed, 8,705 deselected, 34.19 seconds.
- HTTP/process regression: 15 passed, 1 warning, 335.70 seconds. This includes
  ten terminal-recovery cases and five affected yielded/Research/report cases.

The captured unit/verify/smoke/http `.command`, `.log` and `.exit` files, aggregate
runner exit and source-before/source-after receipts identify these runs. Evidence
archive filenames follow `test-evidence/producer-qualified-a12b26b__unit.log`
(and the matching verify/smoke/http `.log`, `.command`, `.exit` members).
Independent final evidence includes
`test-evidence/producer-review-evidence__established-probes.log`,
`test-evidence/producer-review-evidence__old-upgrades.log` and
`test-evidence/producer-review-evidence__v4-producer-final.log`.
The evidence-selection record is `test-evidence/evidence-selection.json`. Historical sources and failed attempts retain their original attribution. Counts overlap and must not be
summed as unique coverage. Final combined runs remain separate below.

Builder process tests use real HTTP, synthetic providers, native tool effects,
actual SIGKILL and two process restarts. Two-root cases require genuinely distinct
enrolled roots, exact lifecycle states and unchanged provider/tool/effect/artifact
counts across both restarts. The first returned partial slice is legally completed
by the synthetic executor so the real TurnExecutive rotates through its binder;
this fixture design is not evidence that arbitrary native callers behave so.

Independent review approved the exact isolated commit with 83 unique successful
controls: 61 established controls, four actual schema17/18 upgrade controls and
18 producer/Stop/schema19-v3 controls. The established run deselected five known
default/tier-drift hypotheses; these remain an explicit scope limit, not new passes.
The 16 overlapping diagnostic passes are not added again.

Independent crash controls use controlled BaseException barriers and reconstructed
app/store owners. Boot checks invoke the real RecoveryManager with original owners
classified as dead through its process-liveness input. They do **not** independently
duplicate the builder's SIGKILL/process suite. Both sets of evidence are needed to
understand the tested boundary.

## Preserved failures and test diagnostics

Earlier outcomes remain failures; narrow later success does not rewrite them:

- ec8353c: unsafe sealing through native-child and all-attempt graph gaps.
- a1ab122: qualified indirect children, truncated enrollment/history, incompatible
  lifecycle and old-task negative-veto gaps.
- c7cbffa: Stop falsely cancelled unresolved work; its HTTP run had 2 failures and
  10 passes, including positive boot/recovery failures.
- Unchanged version14/ccda0c: journal-free attribution reproduced falsely completed
  or cancelled tasks with pending effects. These pre-existing ordinary settlement
  defects are distinguished from unsafe recovery introduced by early candidates.

Keep test-authoring mistakes separate from implementation defects. The independent
v4 producer diagnostic had 16 passes and one failure because the test expected
ValueError while the API correctly raised RunError for a forbidden transition.
Only that expected exception was corrected; the exact transition message,
prohibition and unchanged-state assertions remained. The final corrected control
passed. Builder pre-freeze boundary HTTP had 3 passes and 2 failures from a rotation
fixture namespace mistake; the corrected two-case run strengthened distinct-root
assertions. Neither diagnostic is substituted for final frozen qualification.

## Combined qualification and packaging

All 18 selected combined groups have explicit zero exits at the original combined source. Root package build and final provenance checks also exited 0; exact scope and reuse are recorded below.

- **verify**: 434 checks within aggregate verification (140 Python and 294 IDE); overlaps other groups; explicit exit 0. `test-evidence/recovery-final-logs__verify.log`; `test-evidence/recovery-final-results__verify.exit`.
- **production**: 89 passed, 48 warnings in 20.95s; explicit exit 0. `test-evidence/recovery-final-logs__production.log`; `test-evidence/recovery-final-results__production.exit`.
- **security**: 203 passed, 2 skipped, 42 warnings in 15.65s; explicit exit 0. `test-evidence/recovery-final-logs__security.log`; `test-evidence/recovery-final-results__security.exit`.
- **durable**: 564 passed, 945 warnings in 229.05s (0:03:49); explicit exit 0. `test-evidence/recovery-final-logs__durable.log`; `test-evidence/recovery-final-results__durable.exit`.
- **background**: 194 passed, 365 warnings in 80.71s (0:01:20); explicit exit 0. `test-evidence/recovery-final-logs__background.log`; `test-evidence/recovery-final-results__background.exit`.
- **order1**: 224 passed, 365 warnings in 89.16s (0:01:29); explicit exit 0. `test-evidence/recovery-final-logs__order1.log`; `test-evidence/recovery-final-results__order1.exit`.
- **order2**: 224 passed, 365 warnings in 73.50s (0:01:13); explicit exit 0. `test-evidence/recovery-final-logs__order2.log`; `test-evidence/recovery-final-results__order2.exit`.
- **terminal**: 78 passed, 5 warnings in 3.32s; explicit exit 0. `test-evidence/recovery-final-logs__terminal.log`; `test-evidence/recovery-final-results__terminal.exit`.
- **ide**: 294 passed, 5 skipped; explicit exit 0. `test-evidence/recovery-final-logs__ide.log`; `test-evidence/recovery-final-results__ide.exit`.
- **http**: 70 passed, 3 deselected in 949.40s (0:15:49); explicit exit 0. `test-evidence/recovery-final-logs__http.log`; `test-evidence/recovery-final-results__http.exit`.
- **research**: 86 passed, 1 warning in 76.71s (0:01:16); explicit exit 0. `test-evidence/recovery-final-logs__research.log`; `test-evidence/recovery-final-results__research.exit`.
- **approval**: 98 passed, 103 warnings in 49.31s; explicit exit 0. `test-evidence/recovery-final-logs__approval.log`; `test-evidence/recovery-final-results__approval.exit`.
- **settings**: 80 passed in 6.01s; explicit exit 0. `test-evidence/recovery-final-logs__settings.log`; `test-evidence/recovery-final-results__settings.exit`.
- **provider**: 207 passed, 235 warnings in 38.30s; explicit exit 0. `test-evidence/recovery-final-logs__provider.log`; `test-evidence/recovery-final-results__provider.exit`.
- **cognition**: 120 passed, 1 warning in 5.02s; explicit exit 0. `test-evidence/recovery-final-logs__cognition.log`; `test-evidence/recovery-final-results__cognition.exit`.
- **specialist**: 1 passed, 5 warnings in 3.07s; explicit exit 0. `test-evidence/recovery-final-logs__specialist.log`; `test-evidence/recovery-final-results__specialist.exit`.
- **procedure**: 31 passed, 1 deselected, 1 warning in 12.77s; explicit exit 0. `test-evidence/recovery-final-logs__procedure.log`; `test-evidence/recovery-final-results__procedure.exit`.
- **extra**: 132 passed, 7 warnings in 5.70s; explicit exit 0. `test-evidence/recovery-final-logs__extra.log`; `test-evidence/recovery-final-results__extra.exit`.

UI evidence is reused, not freshly rerun: 956 tests in 207 files plus type/theme/Vite/no-mock checks. The combined technical record verifies 881 source inputs and 137 dist files are identical, with source SHA256 `765e79abec237e156dc7ebf1b7623e76dad71eb24486476bfa960bbfc75a7aa0`. See `test-evidence/recovery-final-evidence-reuse-proof.json` and `test-evidence/recovery-final-ui-reuse.json`. Equality of 1,950 package inputs to ce03f21 supports companion reuse; it does not certify the new root archives.

Final root/companion archive rebuild, retention, structural/byte checks and hashes:
The root wheel and sdist were rebuilt without installation and all 10 archives passed structural/provenance checks, with explicit packaging and finalization exits 0. Each root archive matches 28 selected runtime/config inputs and 137 UI files. Eight companion archives are reused after exact equality of 1,950 package inputs and tree to ce03f21. Root wheel SHA256: `b88c7c8333917d82e3afff771f22cc02efa431e88805a670be122f841120347c`; sdist SHA256: `c0f21bc34d2927d933ca1fa11809902e44281d9fcf5f8498cff869d43317c60b`. See `test-evidence/recovery-final-qualification.json`, `test-evidence/recovery-final-logs__packages.log` and `test-evidence/recovery-final-archive-proof.json`. These are byte/structure checks, not installed acceptance.. Root wheel/sdist are not IDE extension distributions.

Final portable handoff verification: verified by fresh baseline-only import, complete post-baseline parent comparison, all-object exclusion checks, ZIP CRC and exact manifest coverage; see `artifact-integrity.json`, `all-imported-object-proof.json` and `test-evidence/final-bundle-replay.log`.
The Git bundle preserves the post-baseline graph rather than flattened patches.
Fresh shallow-baseline import must reproduce the exact final tree and post-baseline
parent graph; unavailable pre-baseline history is outside that claim.
`artifact-integrity.json` records source/replay and bundle/diff identity. ZIP CRC
and all manifest members are checked after packaging; the external
`build-result.json` receipt is retained internally for review, not supplied with
or shipped inside the ZIP. The selection scope is
`test-evidence/evidence-selection.json`.

## Known foreground Chat Stop limitation

The background-task safeguards do **not** qualify foreground Chat Stop. On original
`80277648c228e06d005d83c44b7f21d4f360506d`, a durably qualified child native run
can retain a pending effect while the foreground request/objective is marked
cancelled and delivered. Both pending-effect controls failed, before and after
ownership transfer; two clean controls passed. This is an ordinary owned-child
lifecycle defect, not externally performed effects or external database tampering.
It is not repaired by this increment. Chat and all other tabs remain **PARTIAL**;
a foreground repair and its qualification are separate work.

Cleared frozen evidence: `test-evidence/foreground-stop-test_foreground_child_stop.py`,
`test-evidence/foreground-stop-run.sh`, `test-evidence/foreground-stop-baseline.log`
and `test-evidence/foreground-stop-source-head.txt`.


After Stop was awaited, both failing branches still retained cancelled/delivered
state and the same pending child effect after three current-owner ticks and three
ticks from a reconstructed TaskOwner. The supplemental two controls failed;
nine existing root-unknown/live-child/background controls passed. This is
reconstructed-owner persistence, not OS-restart proof or a mere timing claim.
These are recorded pytest outcomes; separate shell-exit receipt files were not
captured for this foreground audit. The original evaluator remained unchanged.
See `test-evidence/foreground-stop-test_foreground_child_reconciliation.py`,
`test-evidence/foreground-stop-reconcile.sh`, `test-evidence/foreground-stop-reconcile.log`,
`test-evidence/foreground-stop-existing-controls.sh` and
`test-evidence/foreground-stop-existing-controls.log`.

## Product and release limits

All product/tab statuses remain PARTIAL. No provider/account, rendered browser or
phone, audio/voice, native-host or deployed acceptance is claimed. This is bounded
terminal recovery, not general unattended interruption continuation. No default
merge, remote PR/CI, runtime deployment, installation or new credentials are part
of this handoff. Release still requires fresh runtime-state comparison, preserved
local work/data and separate approval.

Evidence selection must retain raw failure logs/commands and test probes while
excluding internal worker reports, credentials, user runtime databases, HOME/state,
cache contents and private machine details. Synthetic fixtures and loopback values
are not real-account acceptance. Selection checks are bounded, not universal
secrets detection. Test state used isolated roots, but run_tests.sh also creates
disposable `/tmp/jaeger-test-run.*` and conftest creates `/tmp/jaeger-tests-*`;
not every fixture byte was redirected beneath the chosen evidence root.

## Historical chronology and Research limits

Earlier qualification reports and the failure/revision chronology are historical.
They do not replace the current scoped qualification or upgrade any tab beyond
PARTIAL. Research contract, artifact-byte and recovery consistency do not establish
factual truth, citation entailment, authentic retrieval or factual Research grounding.


## Original, portable and handoff identities

Qualification runs target original combined source
`80277648c228e06d005d83c44b7f21d4f360506d`, tree
`51ef51fe3a56d513a5191796f9f38bd4d6fcf83b`. Its originals remain preserved locally.
The separate portable implementation is
`ace838250949d2fb2e6c3988d87c6f361acfe8c0`, tree
`e974dab00fc07776ca9555ba44794acecde1b662`. A later documentation-only handoff
child must descend from that portable implementation, not from the original graph.
Final handoff child/tree: see root README and `artifact-integrity.json`.

Four export commit IDs differ because one historical documentation reference and
its label were replaced with the portable raw failure-evidence link, then parent
IDs were remapped. All 51 post-baseline graph nodes and parent order/topology remain.
Every other tracked entry, mode and source byte is identical at each mapped
snapshot. Author/committer metadata and commit messages are retained. This does
not claim unchanged original commit IDs. Old-version reproduction uses mapped
`82cbcad6ef95e257810ff315c00bdee9773bed3c` for original a1ab122 and
`4a2a2c0ec09b19b0c2c03fdd179f4905d1a8d151` for original c7cbffa.

The portable review format includes `original-to-export-map.json`,
`mapping-equivalence-proof.json` and `all-imported-object-proof.json`. Independent mapping review verified all 51 mappings, 280,284 tracked-entry
comparisons and all 7,451 imported objects. The separate combined gate ledger above records all 18 selected groups with explicit zero exits.
Final artifact verification includes fresh baseline-only import, complete post-baseline parent comparison, all-object exclusion checks, ZIP CRC and exact manifest coverage; see `artifact-integrity.json`, `all-imported-object-proof.json` and `test-evidence/final-bundle-replay.log`. It covers unreachable extras and delta bases as well as reachable objects; a clean checkout alone is insufficient.
