# Skill Evolution — Plan A: Signal + Trigger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the per-use skill journal into a structured post-use summary, and replace the count threshold with a probabilistic, severity-weighted trigger that fires reviews during idle.

**Architecture:** Two existing modules change. `jaeger_os/core/skill_notes.py` gains structured fields (backward-compatible — `_load` already drops unknown keys, so old lines still parse). `jaeger_os/agent/background/skill_review.py` gains pure trigger functions (`activation`, `fire_probability`, `select_for_review`) + a `sweep()` that the Deep Think idle loop calls; the eager on-note proposal becomes a flag-only fast-path. Randomness is injected (a `random.Random`) so selection is deterministic in tests. Validation/review/spawn/archive/retirement are **out of scope** (Plans B + C).

**Tech Stack:** Python 3.11/3.12, stdlib only (`math`, `random`, `json`, `dataclasses`), pytest.

## Global Constraints

- **No new dependencies** — stdlib only (`math.exp` for the sigmoid; `random.Random` for draws).
- **Backward-compatible journal** — existing `skill_notes.jsonl` lines (no new fields) must still load; no migration.
- **Tests use `.venv/bin/python -m pytest`** (pyenv 3.13 lacks deps).
- **No `Co-Authored-By` trailer** on commits.
- **Scope = recipe-skills only**; this plan adds signal + trigger, nothing that rewrites a skill.
- Severity weights (verbatim): `smooth 0 · slow 1 · issues 2 · failed 3`; an agent **flag** adds `FLAG_BUMP = 4`.

## File Structure

- `jaeger_os/core/skill_notes.py` — MODIFY: widen `SkillNote` + `add_note`.
- `jaeger_os/main.py` — MODIFY: `skill_note` tool (`:1199`) passes the new fields; on-note hook (`:1216`) becomes flag-only.
- `jaeger_os/agent/background/skill_review.py` — MODIFY: add `severity`/`activation`/`fire_probability`/`select_for_review`/`sweep`/`_log_decision`; change `maybe_propose_on_note`.
- `dev/tests/jaeger_os/core/test_skill_notes.py` — MODIFY: structured-fields round-trip + old-line tolerance.
- `dev/tests/jaeger_os/agent/test_skill_review.py` — MODIFY: trigger math + selection + sweep + flag fast-path.

---

### Task 1: Widen the post-use summary (`SkillNote` + `add_note`)

**Files:**
- Modify: `jaeger_os/core/skill_notes.py`
- Test: `dev/tests/jaeger_os/core/test_skill_notes.py`

**Interfaces:**
- Produces: `SkillNote(skill, outcome, note, ts, objective, calls:int, procedure, errors, flag:bool)`; `add_note(layout, *, skill, outcome, note="", objective="", calls=0, procedure="", errors="", flag=False) -> SkillNote`.

- [ ] **Step 1: Write the failing test**

```python
def test_add_note_stores_structured_fields(tmp_path):
    from jaeger_os.core import skill_notes as sn
    layout = type("L", (), {"root": tmp_path})()
    n = sn.add_note(layout, skill="weather", outcome="issues",
                    note="slow", objective="get forecast", calls=7,
                    procedure="read,read,read,fetch", errors="404 then retry",
                    flag=True)
    assert n.calls == 7 and n.flag is True and n.objective == "get forecast"
    loaded = sn.notes_for(layout, "weather")[0]
    assert loaded.calls == 7 and loaded.flag is True and loaded.errors == "404 then retry"

def test_old_lines_without_new_fields_still_load(tmp_path):
    from jaeger_os.core import skill_notes as sn
    p = tmp_path / "memory" / "skill_notes.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text('{"skill":"x","outcome":"smooth","note":"old","ts":"t"}\n', encoding="utf-8")
    layout = type("L", (), {"root": tmp_path})()
    n = sn.notes_for(layout, "x")[0]
    assert n.calls == 0 and n.flag is False        # defaults fill missing fields
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/core/test_skill_notes.py::test_add_note_stores_structured_fields -v`
Expected: FAIL — `add_note() got an unexpected keyword argument 'objective'`.

- [ ] **Step 3: Widen the dataclass + add_note**

In `jaeger_os/core/skill_notes.py`, replace the `SkillNote` dataclass and `add_note`:

```python
@dataclass
class SkillNote:
    skill: str = ""
    outcome: str = "smooth"      # smooth | slow | issues | failed
    note: str = ""               # the agent's terse, concrete observation
    ts: str = ""
    objective: str = ""          # the task objective, verbatim (1 line)
    calls: int = 0               # tool-call count for this use
    procedure: str = ""          # brief ordered procedure (the calls)
    errors: str = ""             # errors / retries / dead-ends
    flag: bool = False           # agent asks for review (fast-path)


def add_note(layout: Any, *, skill: str, outcome: str, note: str = "",
             objective: str = "", calls: int = 0, procedure: str = "",
             errors: str = "", flag: bool = False) -> SkillNote:
    """Append a structured post-use summary — one JSONL line, no model call.
    An unknown ``outcome`` is recorded as ``issues`` (still worth a signal)."""
    out = (outcome or "smooth").strip().lower()
    n = SkillNote(skill=(skill or "").strip(),
                  outcome=out if out in OUTCOMES else "issues",
                  note=(note or "").strip(), ts=_now(),
                  objective=(objective or "").strip(), calls=int(calls or 0),
                  procedure=(procedure or "").strip(),
                  errors=(errors or "").strip(), flag=bool(flag))
    p = notes_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(n), ensure_ascii=False) + "\n")
    return n
```

(`_load` already filters to `SkillNote.__dataclass_fields__`, so old lines load with defaults — no change needed there.)

- [ ] **Step 4: Run to verify both pass**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/core/test_skill_notes.py -v`
Expected: PASS (existing skill_notes tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
git add jaeger_os/core/skill_notes.py dev/tests/jaeger_os/core/test_skill_notes.py
git commit -m "Skill notes: widen post-use note into a structured summary"
```

---

### Task 2: `skill_note` tool passes the structured fields

**Files:**
- Modify: `jaeger_os/main.py:1199-1216` (the `skill_note` tool)

**Interfaces:**
- Consumes: `skill_notes.add_note(...)` (Task 1).
- Produces: tool `skill_note(skill, outcome="smooth", note="", objective="", calls=0, procedure="", errors="", flag=False) -> dict`.

- [ ] **Step 1: Update the tool signature + body**

Replace the `skill_note` tool head + `add_note` call in `jaeger_os/main.py` (around `:1199`):

```python
    def skill_note(skill: str, outcome: str = "smooth", note: str = "",
                   objective: str = "", calls: int = 0, procedure: str = "",
                   errors: str = "", flag: bool = False) -> dict:
        """Jot a post-use summary about a skill you just used — the journal that
        feeds skill self-improvement. After a notable use:
          • outcome — smooth | slow | issues | failed (how it went)
          • note    — one terse, concrete line
          • calls   — how many tool calls this use took
          • procedure — the brief ordered calls ("read,read,fetch")
          • errors  — errors / retries / dead-ends you hit
          • flag    — True to ask for a review now (a use that wasted real effort)
        Cheap (one line, no model). Reviews fire on their own during idle; `flag`
        fast-tracks one. Returns {ok, skill, outcome}."""
        from jaeger_os.core import skill_notes as _sn
        layout = _pipeline.get("layout")
        n = _sn.add_note(layout, skill=skill, outcome=outcome, note=note,
                         objective=objective, calls=calls, procedure=procedure,
                         errors=errors, flag=flag)
        result = {"ok": True, "skill": n.skill, "outcome": n.outcome}
```

(Leave the lines after `result = …` as-is, except the hook change in Task 6.)

- [ ] **Step 2: Smoke that the tool imports + accepts the args**

Run: `.venv/bin/python -c "import jaeger_os.main"`
Expected: no error (import clean).

- [ ] **Step 3: Commit**

```bash
git add jaeger_os/main.py
git commit -m "skill_note tool: accept the structured post-use fields"
```

---

### Task 3: Severity-weighted activation

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py`
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Consumes: `skill_notes.notes_for` + `SkillNote.flag` (Task 1).
- Produces: `_SEVERITY: dict[str,int]`, `FLAG_BUMP: int`, `severity(note) -> int`, `activation(layout, skill) -> float`.

- [ ] **Step 1: Write the failing test**

```python
def test_activation_sums_severity_since_last_review(tmp_path):
    from jaeger_os.core import skill_notes as sn
    from jaeger_os.agent.background import skill_review as sr
    layout = type("L", (), {"root": tmp_path})()
    sn.add_note(layout, skill="w", outcome="failed", note="")     # 3
    sn.add_note(layout, skill="w", outcome="reviewing", note="")  # resets
    sn.add_note(layout, skill="w", outcome="issues", note="")     # 2
    sn.add_note(layout, skill="w", outcome="slow", note="", flag=True)  # 1 + 4
    assert sr.activation(layout, "w") == 7.0      # 2 + 1 + 4, pre-marker dropped

def test_severity_unknown_is_zero():
    from jaeger_os.agent.background import skill_review as sr
    from jaeger_os.core.skill_notes import SkillNote
    assert sr.severity(SkillNote(outcome="smooth")) == 0
    assert sr.severity(SkillNote(outcome="failed")) == 3
    assert sr.severity(SkillNote(outcome="bogus")) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_activation_sums_severity_since_last_review -v`
Expected: FAIL — `module 'skill_review' has no attribute 'activation'`.

- [ ] **Step 3: Implement severity + activation**

Add to `jaeger_os/agent/background/skill_review.py` (after `_BAD`):

```python
_SEVERITY = {"smooth": 0, "slow": 1, "issues": 2, "failed": 3}
FLAG_BUMP = 4


def severity(note: Any) -> int:
    """Severity weight of one note (unknown outcome → 0)."""
    return _SEVERITY.get(getattr(note, "outcome", ""), 0)


def activation(layout: Any, skill: str) -> float:
    """Severity-weighted sum of a skill's notes SINCE the last ``reviewing``
    marker (a review consumes/resets it), plus FLAG_BUMP per flagged note."""
    notes = skill_notes.notes_for(layout, skill)
    last = max((i for i, n in enumerate(notes) if n.outcome == "reviewing"),
               default=-1)
    recent = notes[last + 1:]
    return float(sum(severity(n) for n in recent)
                 + FLAG_BUMP * sum(1 for n in recent if getattr(n, "flag", False)))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py -v -k "activation or severity"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jaeger_os/agent/background/skill_review.py dev/tests/jaeger_os/agent/test_skill_review.py
git commit -m "skill-review: severity-weighted activation (since last review)"
```

---

### Task 4: Fire probability + the two rails

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py`
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Produces: constants `S0`, `T`, `S_MIN`, `S_MAX`; `fire_probability(s, *, s0=S0, t=T, s_min=S_MIN, s_max=S_MAX) -> float`.

- [ ] **Step 1: Write the failing test**

```python
def test_fire_probability_rails_and_shape():
    from jaeger_os.agent.background import skill_review as sr
    assert sr.fire_probability(0.0) == 0.0                 # below gate
    assert sr.fire_probability(sr.S_MIN - 0.01) == 0.0     # gate
    assert sr.fire_probability(sr.S_MAX) == 1.0            # ceiling
    assert sr.fire_probability(sr.S_MAX + 5) == 1.0        # past ceiling
    mid = sr.fire_probability(sr.S0)                       # midpoint ≈ 0.5
    assert 0.49 <= mid <= 0.51
    # monotonic between gate and ceiling
    assert sr.fire_probability(sr.S0 - 1) < mid < sr.fire_probability(sr.S0 + 1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_fire_probability_rails_and_shape -v`
Expected: FAIL — no attribute `fire_probability`.

- [ ] **Step 3: Implement the sigmoid + rails**

Add to `skill_review.py` (add `import math` at top):

```python
# Trigger tuning (conservative to start; widen once watched). S is an activation
# in "severity points" — one `failed` = 3, one `issues` = 2, a flag = +4.
S_MIN = 2.0    # gate: below this, never fire (don't review noise)
S0 = 5.0       # sigmoid midpoint (~ P=0.5)
T = 2.0        # temperature: larger = softer ramp
S_MAX = 10.0   # ceiling: at/above this, always fire (no infinite deferral)


def fire_probability(s: float, *, s0: float = S0, t: float = T,
                     s_min: float = S_MIN, s_max: float = S_MAX) -> float:
    """Probability this skill is reviewed this idle sweep. Gate below ``s_min``
    (0.0), ceiling at/above ``s_max`` (1.0), sigmoid in between."""
    if s < s_min:
        return 0.0
    if s >= s_max:
        return 1.0
    return 1.0 / (1.0 + math.exp(-(s - s0) / t))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_fire_probability_rails_and_shape -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jaeger_os/agent/background/skill_review.py dev/tests/jaeger_os/agent/test_skill_review.py
git commit -m "skill-review: sigmoid fire-probability with gate + ceiling rails"
```

---

### Task 5: Weighted selection under a per-sweep budget

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py`
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Consumes: `fire_probability` (Task 4).
- Produces: `select_for_review(activations: dict[str, float], k: int, *, rng) -> list[str]` — `rng` is a `random.Random`; returns the fired skills, worst-first, capped at `k`.

- [ ] **Step 1: Write the failing test**

```python
def test_select_respects_gate_budget_and_draw():
    import random
    from jaeger_os.agent.background import skill_review as sr
    acts = {"low": 0.0, "mid": sr.S0, "hi1": sr.S_MAX, "hi2": sr.S_MAX + 3}
    # rng that always "draws low" → only P==1.0 (ceiling) skills fire
    class _AlwaysFire(random.Random):
        def random(self):  # noqa: D401
            return 0.0
    fired = sr.select_for_review(acts, k=5, rng=_AlwaysFire())
    assert "low" not in fired                      # gated out (P==0)
    assert set(fired) >= {"hi1", "hi2"}            # ceilings always fire
    # budget cap + worst-first ordering
    capped = sr.select_for_review(acts, k=1, rng=_AlwaysFire())
    assert capped == ["hi2"]                       # highest activation first
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_select_respects_gate_budget_and_draw -v`
Expected: FAIL — no attribute `select_for_review`.

- [ ] **Step 3: Implement selection**

Add to `skill_review.py`:

```python
def select_for_review(activations: dict[str, float], k: int, *, rng) -> list[str]:
    """Probabilistically pick skills to review this sweep. Each skill fires with
    its ``fire_probability``; fired skills are returned worst-first (highest
    activation) and capped at ``k`` so one idle period can't churn everything."""
    fired = [s for s, a in activations.items()
             if rng.random() < fire_probability(a)]
    fired.sort(key=lambda s: activations[s], reverse=True)
    return fired[:max(0, k)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_select_respects_gate_budget_and_draw -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jaeger_os/agent/background/skill_review.py dev/tests/jaeger_os/agent/test_skill_review.py
git commit -m "skill-review: probabilistic worst-first selection under a budget"
```

---

### Task 6: The sweep + flag fast-path + decision log + wiring

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py` (add `sweep`, `_log_decision`; change `maybe_propose_on_note`)
- Modify: `jaeger_os/main.py:1216` (on-note hook passes the note)
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Consumes: `activation` (T3), `select_for_review` (T5), `propose_review` (existing), `skill_notes.summary` (existing), `fire_probability` (T4).
- Produces: `sweep(layout, queue, *, k=DEFAULT_K, rng=None) -> list[dict]`; `_log_decision(layout, skill, s, p, fired) -> None`; `maybe_propose_on_note(layout, note) -> dict | None`; `DEFAULT_K = 3`.

- [ ] **Step 1: Write the failing tests**

```python
def test_flag_fast_path_proposes_immediately(tmp_path, monkeypatch):
    from jaeger_os.core import skill_notes as sn
    from jaeger_os.agent.background import skill_review as sr
    layout = type("L", (), {"root": tmp_path})()
    called = {}
    monkeypatch.setattr(sr, "propose_review",
                        lambda lay, skill, **k: called.setdefault("skill", skill) or {"proposed": True})
    n = sn.add_note(layout, skill="w", outcome="slow", note="", flag=True)
    assert sr.maybe_propose_on_note(layout, n) == {"proposed": True}
    assert called["skill"] == "w"
    # an unflagged note defers to the sweep → no immediate proposal
    called.clear()
    n2 = sn.add_note(layout, skill="w", outcome="slow", note="")
    assert sr.maybe_propose_on_note(layout, n2) is None

def test_sweep_proposes_selected_and_logs(tmp_path, monkeypatch):
    import random
    from jaeger_os.core import skill_notes as sn
    from jaeger_os.agent.background import skill_review as sr
    layout = type("L", (), {"root": tmp_path})()
    for _ in range(4):                       # activation 12 → ceiling → fires
        sn.add_note(layout, skill="w", outcome="failed", note="")
    proposed = []
    monkeypatch.setattr(sr, "propose_review",
                        lambda lay, skill, **k: proposed.append(skill) or {"proposed": True})
    decisions = sr.sweep(layout, queue=object(), k=3, rng=random.Random(0))
    assert proposed == ["w"]
    assert decisions and decisions[0]["skill"] == "w" and decisions[0]["fired"] is True
    assert sr.review_log_path(layout).exists()      # decision logged
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py -v -k "flag_fast_path or sweep_proposes"`
Expected: FAIL — `sweep` / `review_log_path` not defined; `maybe_propose_on_note` arity wrong.

- [ ] **Step 3: Implement sweep, logging, flag fast-path**

In `skill_review.py`, add `import json` + `from pathlib import Path` at top, add `DEFAULT_K = 3`, and:

```python
def review_log_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "skill_review_log.jsonl"


def _log_decision(layout: Any, skill: str, s: float, p: float, fired: bool) -> None:
    """Append one explainable trigger decision (S, P, fired) — so 'why did it
    review X?' is never a mystery."""
    from jaeger_os.core.skill_notes import _now
    rec = {"skill": skill, "S": round(s, 3), "P": round(p, 3),
           "fired": bool(fired), "ts": _now()}
    p_ = review_log_path(layout)
    p_.parent.mkdir(parents=True, exist_ok=True)
    with p_.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def sweep(layout: Any, queue: Any, *, k: int = DEFAULT_K, rng=None) -> list[dict]:
    """One idle/Deep-Think sweep: score every skill that has notes, pick the
    worst few probabilistically, propose a review for each, and log every
    decision. No-op when the loop is opted out."""
    if not enabled():
        return []
    import random
    rng = rng or random.Random()
    acts = {skill: activation(layout, skill) for skill in skill_notes.summary(layout)}
    selected = set(select_for_review(acts, k, rng=rng))
    decisions = []
    for skill, s in acts.items():
        fired = skill in selected
        _log_decision(layout, skill, s, fire_probability(s), fired)
        if fired:
            propose_review(layout, skill, force=True)
        decisions.append({"skill": skill, "S": s, "fired": fired})
    return decisions


def maybe_propose_on_note(layout: Any, note: Any) -> dict | None:
    """Called after a note lands. Only the agent's ``flag`` fast-tracks a review;
    everything else defers to the idle ``sweep``. No-op when opted out."""
    if not enabled() or not getattr(note, "flag", False):
        return None
    return propose_review(layout, getattr(note, "skill", ""), force=True)
```

- [ ] **Step 4: Update the on-note hook in `main.py`**

At `jaeger_os/main.py:1216`, change the call to pass the note object:

```python
            proposed = skill_review.maybe_propose_on_note(layout, n)
```

- [ ] **Step 5: Run the targeted tests**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py -v -k "flag_fast_path or sweep_proposes"`
Expected: PASS.

- [ ] **Step 6: Run the full skill-review + skill-notes suites (catch regressions in the existing tests)**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py dev/tests/jaeger_os/core/test_skill_notes.py -v`
Expected: PASS. (If an existing test calls `maybe_propose_on_note(layout, skill_str)`, update it to pass a `SkillNote` — the arity changed by design.)

- [ ] **Step 7: Commit**

```bash
git add jaeger_os/agent/background/skill_review.py jaeger_os/main.py dev/tests/jaeger_os/agent/test_skill_review.py
git commit -m "skill-review: idle sweep (probabilistic) + flag fast-path + decision log"
```

---

### Task 7: Wire the sweep into the Deep Think idle loop

**Files:**
- Modify: `jaeger_os/main.py` (the Deep Think idle entry — where `queue_for_layout` / `next_pending()` is polled)

**Interfaces:**
- Consumes: `skill_review.sweep(layout, queue)` (Task 6); `deep_think.queue_for_layout(layout)`.

- [ ] **Step 1: Find the Deep Think idle entry**

Run: `grep -n "next_pending\|queue_for_layout\|DEFAULT_CODER_MODEL\|deep.think" jaeger_os/main.py`
Expected: locate the block that, when idle/asleep, gets the queue and polls `next_pending()` (the summary places it around `main.py:4001-4053`).

- [ ] **Step 2: Add the sweep at the start of an idle period**

Immediately before the loop that drains `queue.next_pending()`, add (using the queue already resolved there):

```python
            # Refill the queue: score skills from their post-use summaries and
            # probabilistically queue the worst few for review (idle only).
            try:
                from jaeger_os.agent.background import skill_review as _sr
                _sr.sweep(layout, queue)
            except Exception:  # noqa: BLE001 — a sweep failure never blocks deep-think
                pass
```

- [ ] **Step 3: Smoke that main imports + the deep-think module still loads**

Run: `.venv/bin/python -c "import jaeger_os.main; from jaeger_os.agent.background import skill_review; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add jaeger_os/main.py
git commit -m "deep-think: run a skill-review sweep at the start of each idle period"
```

---

### Task 8: Gate + docs

**Files:**
- Modify: `dev/docs/process/SKILL_EVOLUTION_PLAN.md` (mark §1 + §2 shipped), `dev/docs/process/STATUS.md`

- [ ] **Step 1: Full not-model gate**

Run: `.venv/bin/python -m pytest dev/tests -m "not model" -q`
Expected: all pass (existing total + the new skill_notes/skill_review tests).

- [ ] **Step 2: Update the plan + STATUS**

In `SKILL_EVOLUTION_PLAN.md` Refinement §1/§2, mark them shipped (date 2026-06-27). Add a STATUS entry: "Skill-evolution Plan A — structured post-use summary + probabilistic severity-weighted idle trigger (sweep + flag fast-path + decision log)."

- [ ] **Step 3: Commit**

```bash
git add dev/docs/process/SKILL_EVOLUTION_PLAN.md dev/docs/process/STATUS.md
git commit -m "Skill evolution Plan A shipped: structured summary + probabilistic trigger"
```

---

## Self-Review

**Spec coverage (Refinement §1, §2):** §1 structured summary → Tasks 1-2 ✓. §2 activation → T3; sigmoid+rails → T4; weighted budget selection → T5; sweep + idle-timing + flag fast-path + decision log → T6-T7 ✓. (§3-§7 are Plans B/C, out of scope here.)

**Placeholder scan:** no TBD/TODO; every code step has complete code. Task 7 step 1 is a `grep` to locate the (summary-confirmed ~`:4001`) idle block, then step 2 inserts concrete code — the only "find it" step, justified because the exact line shifts.

**Type consistency:** `activation -> float` feeds `fire_probability(s: float)` and the `activations: dict[str,float]` of `select_for_review`; `maybe_propose_on_note(layout, note)` matches the `main.py:1216` call updated in T6 step 4; `sweep` uses `skill_notes.summary` (skill→tally) keys as the skill set. `SkillNote.flag`/`.calls` defined in T1 are read in T3/T6. Consistent.
