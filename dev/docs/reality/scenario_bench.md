# The two JROS benchmarks — routing corpus vs scenario suite

JROS has **two** benchmark types. They answer different questions and run at
different cadences. Don't conflate them.

| | Routing corpus | Scenario suite |
|---|---|---|
| Code | `jaeger_os/core/bench/cases.py` + `cases_b.py` | `jaeger_os/core/bench/scenarios.py` |
| Runner | `dev/benchmark/bench.py` | `dev/benchmark/scenarios.py` |
| Shape | single-turn (mostly), fast | full-system, multi-turn |
| Checks | tool routing + `answer_contains` | **deterministic side-effects** (a file exists with content X, a schedule persisted, a board card landed, a refusal happened) |
| Instance | live instance + hermetic memory *snapshot/restore* | **throwaway temp instance** in a tempdir |
| Cadence | every prompt tweak | **pre-release gate** |
| Question | "does the model route to the right tool?" | "does the whole system actually DO the thing, safely?" |

## Routing corpus — the fast bench

```sh
python dev/benchmark/bench.py            # full corpus
python dev/benchmark/bench.py --quick    # 8-case smoke
python dev/benchmark/bench.py --category safety
```

Runs in-process against the live instance; snapshots the mutable memory
files and restores them after. Optimised for "did my prompt change move the
routing number". See the module docstring for the full flag set.

## Scenario suite — the pre-release gate

```sh
python dev/benchmark/scenarios.py                 # every runnable scenario
python dev/benchmark/scenarios.py --lane security # the [SEC] gates only
python dev/benchmark/scenarios.py --ids file-scratchpad,tool-conditional
python dev/benchmark/scenarios.py --list          # list, no model boot
python dev/benchmark/scenarios.py --keep-temp     # leave the tmp instance for inspection
```

Encodes the operator-authored real-world prompts from
`scenario_test_suite.md` (kept VERBATIM) as `ScenarioCase`s with **real
checks**. Two lanes:

- **scriptable [S]** — deterministic pass/fail (36 scenarios: Suites 1-2 +
  Suite 3's tool/memory/planning/honesty/edge cases).
- **security [SEC]** — refusal / isolation gates (15 scenarios: Suites 1-2 +
  Suite 3's destructive / exfiltration / self-tamper / injection battery).
  A SEC failure is a real vulnerability, not a score dip.

The **watch [W]** scenarios need a human glance and are listed as manual —
they join the pre-release flow-walk checklist, they don't run here:
`persona-dev-chat`, `mem-latent-association`, the UI-responsiveness half of
`async-timeout-recovery`, plus Suite 3's modality/tone rows (`cu-screenshot`,
`cu-readback`, `vis-generate`, `skill-list`, `skill-propose`, `persona-banter`,
`persona-tone`, `persona-meta`, `honest-recant`, `voice-roundtrip`).

### Hermetic by construction — why this can't pollute your instance

The scenarios WRITE real files, schedules, facts, and board cards. A prior
*manual* pass polluted the operator's live `jros-dev` (an every-minute
schedule that spammed on boot) because `kill -9` of a hung run bypassed the
snapshot-restore.

This harness removes that failure mode by construction:

1. It resolves the **live** instance and records a signature of its memory
   (files + sizes + mtimes) — the thing it must never touch.
2. It builds a **fresh minimal instance in a tempdir**
   (`build_hermetic_instance`): copies the live `config.yaml` + `identity.yaml`
   so the **same model** loads, but gives it a brand-new empty
   `memory/`/`workspace/`, a fresh manifest, and `permissions.mode: allow`.
3. It points `JAEGER_INSTANCE_DIR` at the tempdir and boots there.
4. On exit — even on crash — a `finally` block re-checks the live signature
   (prints `live instance untouched: YES/NO`) and deletes the tempdir.

Because the run *never snapshot-restores live state* and the temp instance
is a different directory with its own lock, a scenario cannot reach the
operator's instance even if the process is killed mid-run. The isolation is
verified every run, not assumed.

### Per-turn timeouts — the hang lesson

Every turn is bounded by `timeout_s` (default 180s; async scenarios get
more). A turn that exceeds it is recorded **inconclusive** and the scenario
moves on — the harness never hangs. The `safe-credential-leak` gate is the
canonical case: the old sweep ran a multi-minute `rglob` over `$HOME` that
no watchdog interrupted. Here it runs against the temp instance under a
bounded turn, and the check fails the gate the moment the agent engages the
sweep instead of refusing.

### Exit codes

- `0` — everything passed.
- `1` — a scriptable scenario failed.
- `2` — a **security gate** failed (LOUD; do not release).

## Testing the harness itself

The check functions are pure — `(Transcript, workspace_dir, MemoryView) ->
(passed, detail)` — so they're unit-tested with hand-built fixtures and **no
model**: `dev/tests/jaeger_os/core/test_scenarios.py`. The hermetic
temp-instance builder is tested there too (creates a temp instance from a
fake source, proves the source is never touched, tears down cleanly).

The full live run needs a booted model — that's the operator's pre-release
step, not part of `pytest`.
