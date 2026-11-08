# Fresh-session procedure retrieval and automatic review gate

Base: `1bb5daab000776e9fe4df147f42ddf3ffe6cb62a`.

## Findings and bounded correction

The active retrieval path is `EntityRuntime.prepare_turn` → `_skill_matches` →
`SleepTimeProcessor.skill_pipeline.matching_skills` → context compiler. The
registry reloads persistent package directories. The separate legacy
`MemorySubsystem.procedural` reader only handles flat files and is used for
telemetry, not this active prompt path; it is unchanged.

Before the correction, automatic skill review passed a non-placeholder syntax
check as its verification callback and persisted `verified: true`. A controlled
procedure returning a success string without writing the required receipt failed
an independent disk check, but was promoted and retrieved after reload. This is
a real false-verification defect, not proof of safe autonomous learning.

The correction retains original candidates pending independent verification,
rejects placeholders explicitly, reports outcomes in the cycle result and
completion event, and stops re-extracting the same candidate on every cycle.
It adds no verifier, code execution, model scoring, permission changes, or
promotion authority. Pending review is not successful execution.

## Positive acceptance and controls

Two separate interpreters use isolated state. The producer executes only
constant fixture code and independently verifies exact written contents through
VerificationContract before explicit promotion. It exits. A new interpreter
creates EntityRuntime and prepares a different session. The real registry and
prompt path retrieve the persisted procedure and reflection. Failed and
placeholder candidates do not appear. Syntactic tool success alone creates no
skill candidate target or semantic claim. An instruction-bearing historical
reflection remains escaped read-only context, distinct from the current request.
This verifies prompt construction, not resistance of a live model to injection.
Global registration and singleton lookup are patched only during explicit
fixture promotion; persistence, reload, matching, and turn preparation are real.
No providers, browser, AF_UNIX, live runtime, real credentials or operator data.

## Limits

- Automatic acquisition is still incomplete: no objective-specific verifier is
  wired into sleep review. Candidates remain pending, including on repeat cycles.
- LearningPipeline's novel-pattern branch returns candidate metadata, not a
  complete automatically verified extraction pipeline. A quiet heartbeat selects
  SleepTimeHandler, whose default cycle includes candidate review.
- Explicit promotion trusts the caller's verifier/result. Verification results
  are not bound to candidate code, and registry reload does not revalidate disk
  integrity, manifests or provenance. Existing records are not retroactively
  repaired or quarantined. No arbitrary disk-package safety is claimed.
- Runtime `skill.used` currently means retrieval/selection, not observed execution
  or successful reuse. The acceptance does not execute retrieved code.
- No permission broker/evaluator or tool boundary changes. No model-weight
  training. No live application, Mac Studio, default-branch merge or deployment
  qualification. Product remains partial.

Registry `get_skill` reloads package source, while `prepare_turn` selects a skill
name, description and provenance reference. The prepared prompt is not evidence
of full implementation instructions reaching a model, or of the model/tool
runtime executing that procedure successfully. Only the producer's explicitly
controlled fixture execution is independently verified.

Pending candidates remain in the append-only event store. The existing automatic
review window is still the most recent 200 candidates within 24 hours; this
change does not create an indefinite pending-work scheduler. Cycle `action_taken`
means processing occurred, not that a candidate was executed or verified.

## Verification

- Fail-before negative acceptance: 1 failed, 1 deselected, exit 1 at base.
- Before-change adjacent regression: 25 passed, 1 deselected (HTTP test excluded).
- Before-change required `scripts/verify.sh all`: passed.
- Candidate focused acceptance: 6 passed, including two fresh interpreters,
  automatic false-success rejection, repeated/reopened review with spoofed
  verdicts and placeholders, and public handler pending outcome.
- Candidate adjacent regression: 25 passed, 1 HTTP case excluded. Required
  aggregate: 430 passed (136 Python and 294 IDE).
- Independent exact candidate: 57 focused/adjacent and 430 aggregate passed.
  Its own spoofed-verdict/false-success probe fails before and passes after.
- Main integrated procedure/adjacent gate: 31 passed, 1 HTTP case excluded here.
  The final combined gates appear in the linked combined qualification report.
  Counts overlap; do not infer a broader live product pass.

Run with an external venv and isolated HOME, JAEGER state and pytest basetemp:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD:$PWD/packages/jaeger-agent:$PWD/packages/jaeger-os"
python -B -m pytest dev/tests/jaeger_ai/core/test_fresh_procedure_retrieval.py -q -s -p no:cacheprovider
python -B -m pytest dev/tests/test_upaa_live_correctness.py dev/tests/jaeger_ai/core/test_release_companion_repairs.py dev/tests/jaeger_ai/core/test_context_item_provenance.py -k 'not normal_authenticated_gateway' -q -p no:cacheprovider
bash scripts/verify.sh all
git diff --check
```

Test logs include existing pytest-asyncio fixture-loop deprecation and unknown
`cache_dir` warnings with cacheprovider disabled. These are not test failures.
