# Foreground Stop and Machine observation qualification

**Overall product and every tab remain PARTIAL.** This is the current combined
qualification report for the foreground Stop and Machine observation repairs.
It supersedes earlier foreground/Machine defect descriptions only in the exact
scopes below. Historical failures and broader limitations remain evidence.
This review handoff is not an installed or deployed release.

## Exact sources and complementary evidence

Current source: `cfb698421c36517493ff4ad6204b518772fc07bd`, tree
`d4ac76d7af69e5a5073eb8019d5a12122b664311`, in the Machine truth checkout. Its
sole parent is foreground-qualified integration
`a286874920ca0035a571faf17f23b28edae511dd`, tree
`015941119ee402ab5c5048d644a1cd57517e621c`. That merge preserves savedv15 docs
`89d421eb4cc2d8f8d8b43afd992dd74a5e972a6a` and approved foreground repair
`bbc0ec9f90ef41c789065cc09f6739869562055b` as ordered parents.

The current graph has 55 commits after shallow baseline
`ff71bb769bc56e4c6d7be6d540a86be73e291e07`. The final documentation-only child has cfb as its direct parent. Its exact commit, tree
and branch are in the handoff root README and `artifact-integrity.json`; its
runtime and tests are unchanged. Its identity does not relabel earlier test runs.

Foreground backend checks ran exactly on a286. Machine UI/build/repository
verification ran on cfb. Independently verified exact a286→cfb identity for 5,549 unchanged entries and 4,672 non-UI entries excluding the new verification document (proof SHA256 `58817998dc83c900453965dd5c4e72dfac420c7ada82eca395b9a5bebf0a5013`) establishes exact backend entry/type/mode/symlink identity across the Machine increment. Do not
claim the foreground backend groups were rerun on cfb. Independent approved bbc
source matches all 5,441 non-document entries at a286, with five intended docs
different. Historical original802→mappedace equivalence proves only that older
increment; current runtime intentionally includes both later repairs.

## Foreground repair scope

After existing child ownership qualification, cancellation status applies a
read-only native-settlement veto. It accounts for resident producer activity,
bound/earlier enrolled native roots, descendants, terminal lifecycle/checkpoints
and pending effects. Missing or unreadable evidence is unknown, not settled.

Existing qualified Gateway child Stop scopes/tokens and bound agent interruption
remain. The new negative evidence scan does not individually signal or terminate
arbitrary native descendants, undo effects, replay uncertain work, create seals
or expand authority. Bare live descendants stay paused/unconfirmed until authentic
settlement. This repairs false terminal cancellation reporting, not full native
cancellation convergence. Legacy nonresident behavior retains its scope.

Original v15 two failing/two clean Stop controls and reconstructed-owner failures
remain historical. They are not current-source failures and are not relabeled
passes. Independent corrective18 and separate167 controls passed on bbc; counts
can overlap. No OS-restart claim is inferred from reconstructed-owner controls.

## Exact foreground integrated results and retained failure

At a286, focused18, verification140 Python+294 IDE, production89, security203
with 2 macOS-seatbelt skips, and lifecycle359 passed with explicit zero exits.

The first process group had17 passed/1 failed, explicit exit1. The failure was
SECOND-restart readiness failure within a 20-second bound. The helper uses the same
assertion for deadline expiry and early child exit; no child exit/alive/timing
receipt was retained. It is therefore not proven timeout, load, contention or
collision. Cause remains unresolved. No source, assertion or deadline was changed.

An unchanged isolated case passed 1. A controlled fresh-state full process rerun
passed 18 with explicit exit0. These do not erase the original failure or prove its
cause. The original failure and every later result must be included distinctly.
Portable evidence (paths relative to the handoff root):
- `test-evidence/foreground-current-run-gate.sh` records selected commands;
  `foreground-current-focused.log`, `foreground-current-verify.log`,
  `foreground-current-production.log`, `foreground-current-security.log`,
  `foreground-current-lifecycle.log` and `foreground-current-exits.txt` in the
  same directory retain the first-run results and exits.
- `test-evidence/foreground-current-process.log` retains the original failure.
  `foreground-current-run-case-repro.sh`, `foreground-current-process-case-repro.log`
  and `foreground-current-process-case-repro.exit` retain the isolated diagnostic.
  `foreground-current-run-process-controlled.sh`, `foreground-current-process-controlled.log`
  and `foreground-current-process-controlled.exit` retain the controlled full run.
Counts overlap; they are not a unique aggregate total.

## Machine observation scope

Machine overview now reports the observed serving `gateway_process_only` host and
transport limits without fabricating Mac hardware, endpoint address, online daemon
or execution readiness from pending/unsupported/failed/empty reads. Safety accepts
qualified passive `bound_instance_policy_sources`; false values and unknown/null
grant counts remain valid observations. Failed reads do not imply unrestricted
permission. Wrong scope, malformed rows or action overclaims fail qualification.

Loading, unsupported, failed-with-alert and observed-empty states differ. Refresh
re-reads inventory and Safety, clears old observations and ignores completions
from obsolete refresh/source/unmounted lifetimes. Useful valid Linux fields and
backend limits survive. Existing native settings and backend authorization are
unchanged. Permission badge semantics, native settings acceptance, independent
capability/resource subcard refresh and cloud-provider execution readiness are
outside this repair. It controls observations, not native permission semantics.

Independent review passed 23 controls (six unchanged audit cases plus 17 builder
cases) and four extra controls. These overlap builder coverage, not new full-
product gates. Original audit five-failure/one-pass evidence remains historical.
Selected failure evidence is documented in `test-evidence/evidence-selection.json`.
Reviewed Machine logs/results/probes required no sanitation; original local logs
remain unchanged. Broad state manifests are omitted, and the foreground failure
state is represented only by a derived status-only summary.
No credential-bearing diagnostic output or raw private report is supplied.
Independent results are in `test-evidence/machine-review-regressions.log` and
`test-evidence/machine-review-independent.log`, with corresponding `.exit` files.

## Exact Machine UI/build evidence and prior failure

At cfb, the documented bounded-worker full run `npm test -- --maxWorkers=2`
passed 973 tests in 208 files, explicit exit 0, 181.86 seconds. All nine AppWindow
navigation cases passed. Source was clean and 882 tracked UI/shared inputs matched
the compiled snapshot. UI source SHA256:
`899b1bd68a8411d0d8da36979cd7c4ca835ca59407ca855bf602a11562809f89`.

The prior unrestricted run remains FAILED:970 passed/3 navigation failures.
A separate serial diagnostic passed 973. The later bounded pass does not establish
why the unrestricted run failed or make it harmless. Assertions/timeouts were
unchanged; no causal load/contention diagnosis is claimed.

Theme, TypeScript, Vite production/no-mock checks and repository verification pass
on the exact Machine source separately from the bounded full UI run. This is fresh
current UI evidence, not reused old956 evidence. Older original802 broad18 groups
remain historical complementary evidence, not a current full broad18 rerun.
Portable evidence: `test-evidence/machine-bounded-workers2__run.command`,
`test-evidence/machine-bounded-workers2__source-verification.log`,
`test-evidence/machine-bounded-workers2__full-ui.log` and its `.exit` file.
The earlier unrestricted and serial results remain in
`test-evidence/machine-final-ui.log` / `.exit` and
`test-evidence/machine-serial-ui.log` / `.exit`, respectively.
Separate exact-source build and verify records are
`test-evidence/machine-final-build.log` / `.exit` and
`test-evidence/machine-verify.log` / `.exit`.
Selection scope and omitted private state are explicit in
`test-evidence/evidence-selection.json`.

## Packages, history and handoff integrity

Fresh cfb root wheel and sdist were built with no installation and no build
isolation, using the existing exact-source production UI. Build exit is 0.
All ten archives passed structural/path/duplicate/payload checks and wheel RECORD
checks. Both root archives match all 137 embedded UI files, the mock=false
manifest and current UI fingerprint, all 29 historical changed runtime/config
inputs, and the three Machine source/test files. Tracked-source matches are
2,317 in the wheel and 2,322 in the sdist. The sdist build configuration matches.
The IDE controller omission is explicit: these are not IDE extension packages.

- Root wheel SHA256: `8e84b70753915f857c8a4993a8b828d0164954b39acf9bcfa6193378701a982c`.
- Root sdist SHA256: `09bbded064a147f323c95087cf47b3414c377989314c18b84e4335ef277305cb`.
- Eight companion archives are reused only after all 1,950 tracked package inputs,
  package tree `5caed92392f7ddab53e2a883a1bed9600dd21f75`, and all eight prior
  archive hashes matched. They are not claimed freshly rebuilt.

Source proof, prepackage UI check, package build and final archive proof all exited
0. The initial read-only archive checker was deliberately interrupted with Ctrl-C
(exit 130) while repeated gzip seeks were slow. Its log is empty and no assertion
failure was observed. This incomplete run remains distinct from the final pass.
Independent review confirms the optimized checker only caches member bytes once
and changes the reader to use that cache; assertions, inputs and archives are
unchanged. This is a checker performance change, not a source repair.
`test-evidence/archive-checker-reader-optimization.diff` and
`test-evidence/checker-interruption-provenance.json` retain the clarification.
Package provenance is not installation
acceptance and does not imply these distributions contain the later documentation
child. See `test-evidence/machine-artifact-artifact-readiness.json`,
`test-evidence/machine-artifact-archive-hashes.json`,
`test-evidence/machine-artifact-packages.log` / `.exit`,
`test-evidence/machine-artifact-archive-proof.log` / `.exit` and
`test-evidence/machine-artifact-archive-proof-interrupted.log` / `.exit`.
The review ZIP supplies package evidence; it is not an installer.

The historical four-ID original802→ace map is older-increment provenance only.
`original-to-export-map.json` and `mapping-equivalence-proof.json` identify that
mapping. They do not prove current runtime equality. Current transfer proofs are
`foreground-integration-equivalence-proof.json` (bbc→a286) and
`current-domain-equivalence-proof.json` (a286→cfb). The final docs child preserves
all 55 preceding post-baseline commits and their available parent order.

The root README identifies the final bundle/patch hashes and import procedure.
`artifact-integrity.json` identifies the docs-only child and domain sources.
`all-imported-object-proof.json` covers every imported object, including otherwise
unreachable objects and delta bases, object digests and the specific exclusion
checks. `test-evidence/final-bundle-replay.log` records the fresh baseline-only
import and exact head/tree/history checks. `SHA256SUMS` covers every supplied
member except itself. ZIP CRC and exact manifest coverage are checked during
packaging. No pre-shallow-baseline history or universal secret-detection claim is
made. These packaging proofs are separate from application test evidence.

`test-evidence/evidence-selection.json` describes bounded selection. External
post-build receipt is retained packaging evidence, not falsely supplied with a
single ZIP. Delivery caption supplies ZIP SHA256. No raw worker reports, private
state, databases, tokens, native journals, caches or raw migration snapshots ship.

## Known current Agents limitation, outside these repairs

Current cfb still has an Agents outcome-reporting defect. ARES tick retains
failure, timeout or error in the result title/body, but the MCP `post_result`
producer hardcodes `status_line=done`. The bridge, Activity feed and inspector
therefore display finished/completed even beside a failed result title. The
result check correctly stays pending: this is false completion labeling, **not**
verified success or an authorization bypass.

Synthetic execution of the actual worker/MCP producer and actual UI regressions
reproduced three failing unsuccessful-outcome invariants and one passing successful
control. Nineteen existing controls also passed. Producer exit 0 means reproduction
completed, not that the defect is fixed; the UI regression exit is 1. An initial
producer harness-registration error is retained separately from the corrected
harness reproduction. These are synthetic producer/component controls, not live
provider/subprocess, browser, phone or installed-runtime acceptance.

A separate repair is underway outside this source and is not included or qualified
by this handoff. All tabs, including Agents, remain **PARTIAL**.
Evidence citation: `test-evidence/agents-audit-producer.log`, `test-evidence/agents-audit-producer-results.json`, `test-evidence/agents-audit-ui.log`, `test-evidence/agents-audit-controls.log` and their selected `.exit` receipts; reproducible probes/runners are selected alongside them. The separately retained `test-evidence/agents-audit-producer.initial.log` records only the initial harness-registration error.

## Product and release limits

All tabs remain PARTIAL. No real-provider/account operation, browser/phone paint,
audio, native host, installed/deployed acceptance, default merge or remote PR/CI.
Research consistency is not factual truth, entailment or authentic retrieval.
The Machine repair does not change native permission or provider execution
semantics; the foreground repair does not terminate arbitrary native descendants.
Owned test harnesses also use documented /tmp roots; do not claim total redirection.
Pinned upstream remains a5f83f8. A read-only repository/branch API observation on
Nov 9, 2026 at 01:51–01:52 UTC resolved canonical master to
3926eedd353faaf9ddd54eecf74a9f6fbd003707: four commits and 48 paths beyond the
incorporated cutoff, with eight paths overlapping frozen cfb. These later commits
are excluded and untested; no merge/conflict simulation or current-master
compatibility is claimed. The Nov 8 22:02 UTC observation of 4400be5 is historical.
See `test-evidence/latest-upstream-observation.json` for exact overlapping paths
and public repository, branch, commit and compare URLs.
