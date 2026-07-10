# Skill Evolution — Plan B: The Review (second-person) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Turn the Deep Think review task into a **second-person audit** of a skill's accrued post-use summaries that ends in one imperative rule, then applies it measured (benchmark keep-if-better where possible, else apply), with an edit / spawn-new / nothing decision.

**Architecture:** Concentrated in `jaeger_os/agent/background/skill_review.py`. A new `_summaries_block(layout, skill)` renders the structured summaries (Plan A) as the trajectory the auditor reads; `review_description` is rewritten into the second-person 6-step audit + the validation + the edit/spawn/nothing branch + the honesty rule. No new modules; the agent already has `file_write`/`reload_skills`/`benchmark_skill`/`record_skill_revision` to carry out whatever the prompt directs. Scoring/retirement is Plan C.

**Tech Stack:** Python stdlib + pytest. The deliverable is mostly the task PROMPT — tests assert it contains the load-bearing elements.

## Global Constraints

- No new dependencies; no new tools (reuse `file_write`/`reload_skills`/`benchmark_skill`/`record_skill_revision`).
- The audit MUST end in an imperative rule; if it can't, change nothing (honesty rule, verbatim in the prompt).
- Second-person framing is the point — the prompt addresses the agent as "you" reviewing "your own" trajectory.
- Tests via `.venv/bin/python -m pytest`. No `Co-Authored-By` trailer.

## File Structure

- `jaeger_os/agent/background/skill_review.py` — MODIFY: add `_summaries_block`; rewrite `review_description`.
- `dev/tests/jaeger_os/agent/test_skill_review.py` — MODIFY: summaries-block render + the prompt's centerpiece elements.

---

### Task 1: `_summaries_block` — the trajectory the auditor reads

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py`
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Consumes: `skill_notes.notes_for` + `SkillNote.{objective,calls,procedure,errors,note,outcome}` (Plan A).
- Produces: `_summaries_block(layout, skill) -> str`.

- [ ] **Step 1: Write the failing test**

```python
def test_summaries_block_renders_structured_fields() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="w", outcome="reviewing", note="old")  # dropped
    skill_notes.add_note(layout, skill="w", outcome="failed", note="n1",
                         objective="get forecast", calls=7,
                         procedure="read,read,fetch", errors="404 retry")
    block = skill_review._summaries_block(layout, "w")
    assert "old" not in block                       # pre-marker dropped
    assert 'obj="get forecast"' in block and "calls=7" in block
    assert "404 retry" in block and "[failed]" in block


def test_summaries_block_empty() -> None:
    assert "no recent" in skill_review._summaries_block(_layout(), "w").lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_summaries_block_renders_structured_fields -v`
Expected: FAIL — no attribute `_summaries_block`.

- [ ] **Step 3: Implement**

Add to `skill_review.py` (before `review_description`):

```python
def _summaries_block(layout: Any, skill: str) -> str:
    """Render a skill's accrued post-use summaries SINCE the last review as the
    trajectory the auditor reads cold (newest last)."""
    notes = skill_notes.notes_for(layout, skill)
    last = max((i for i, n in enumerate(notes) if n.outcome == "reviewing"),
               default=-1)
    recent = notes[last + 1:]
    if not recent:
        return "(no recent post-use summaries)"
    lines = []
    for i, n in enumerate(recent, 1):
        bits = [f"[{n.outcome}]"]
        if n.objective:
            bits.append(f'obj="{n.objective}"')
        if n.calls:
            bits.append(f"calls={n.calls}")
        if n.procedure:
            bits.append(f'procedure="{n.procedure}"')
        if n.errors:
            bits.append(f'errors="{n.errors}"')
        if n.note:
            bits.append(f"— {n.note}")
        lines.append(f"{i}. " + " ".join(bits))
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py -v -k summaries_block`
Expected: PASS.

- [ ] **Step 5: Commit** (grouped with Task 2 at the §3 milestone.)

---

### Task 2: Rewrite `review_description` — the second-person audit

**Files:**
- Modify: `jaeger_os/agent/background/skill_review.py` (`review_description`)
- Test: `dev/tests/jaeger_os/agent/test_skill_review.py`

**Interfaces:**
- Consumes: `_summaries_block` (Task 1); existing tools named in the prompt.
- Produces: `review_description(layout, skill) -> str` (same signature; new content).

- [ ] **Step 1: Write the failing test**

```python
def test_review_description_is_second_person_audit() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="w", outcome="failed", note="n",
                         objective="o", calls=9)
    d = skill_review.review_description(layout, "w")
    # second-person framing + the trajectory
    assert "AS IF" in d and "calls=9" in d
    # the 6-step audit + the one-lesson imperative + the honesty rule
    assert "THE ONE LESSON" in d and "imperative" in d.lower()
    assert "change nothing" in d.lower()
    # measured validation + spawn-new branch
    assert "benchmark_skill('w')" in d and "REVERT" in d
    assert "NEW skill" in d
    # records the revision when kept
    assert "record_skill_revision('w'" in d
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py::test_review_description_is_second_person_audit -v`
Expected: FAIL — current prompt has no "AS IF" / "THE ONE LESSON".

- [ ] **Step 3: Rewrite `review_description`**

Replace the whole function with:

```python
def review_description(layout: Any, skill: str) -> str:
    """The Deep Think task prompt — a SECOND-PERSON audit of the skill's accrued
    post-use summaries that ends in one imperative rule, then a MEASURED change
    (benchmark keep-if-better where possible) recorded as a revision."""
    block = _summaries_block(layout, skill)
    return (
        f"[{REVIEW_TAG}:{skill}] Improve the '{skill}' skill. Review your own "
        f"logged uses below AS IF THEY WERE SOMEONE ELSE'S — judge each "
        f"trajectory against its objective, not your sympathy for it.\n\n"
        f"Recent uses of '{skill}' (newest last):\n{block}\n\n"
        f"AUDIT — answer each, cite the use #:\n"
        f"1. Objective check — did you meet each objective? full / partial / no.\n"
        f"2. Issues — errors, wrong tools, backtracks, retries.\n"
        f"3. Step economy — fewer calls possible? which were redundant, or could "
        f"have been batched / run in parallel?\n"
        f"4. Guess vs verify — where did you assume instead of checking?\n"
        f"5. THE ONE LESSON — a single reusable imperative ('Batch independent "
        f"reads', NOT 'I read files separately'). If you cannot state it as an "
        f"imperative, the audit found nothing — STOP and change nothing.\n"
        f"6. Skill decision — EDIT '{skill}'s playbook · NEW skill (only if the "
        f"lesson fits no existing skill — check first; prefer EDIT over a "
        f"near-duplicate) · or NOTHING.\n\n"
        f"THEN apply it, MEASURED:\n"
        f"- Benchmarkable skill: baseline benchmark_skill('{skill}'); write "
        f"skills/{skill}_vN/ applying the lesson (keep/extend its smoke test); "
        f"reload_skills; benchmark_skill('{skill}') again; KEEP only if smoke "
        f"passes AND the delta is positive, else REVERT (delete the new dir).\n"
        f"- Pure procedural playbook (not benchmarkable): apply the rule to the "
        f"playbook; it will be scored over its next uses.\n"
        f"- NEW skill: create skills/<name>_v1/ with a use-when trigger + the rule.\n\n"
        f"If you kept a change: record_skill_revision('{skill}', '<vN>', '<the "
        f"imperative rule>', '<benchmark delta or \"scored\">'), then "
        f"skill_note('{skill}', 'smooth', '<one-line summary>')."
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest dev/tests/jaeger_os/agent/test_skill_review.py -v -k "review_description or summaries_block"`
Expected: PASS.

- [ ] **Step 5: Commit (§3 milestone)**

```bash
git add jaeger_os/agent/background/skill_review.py dev/tests/jaeger_os/agent/test_skill_review.py
git commit -m "Skill evolution B §3: second-person audit review prompt over structured summaries"
```

---

### Task 3: Gate + docs

- [ ] **Step 1: Full not-model gate**

Run: `.venv/bin/python -m pytest dev/tests -m "not model" -q`
Expected: all pass.

- [ ] **Step 2: Mark §3 (and the prompt-level §4/§5) shipped**

In `SKILL_EVOLUTION_PLAN.md`: mark §3 ✅ shipped; note §4 validation + §5 spawn-new are **directed by the review prompt** (the keep-if-better gate + the spawn-new branch are instructions the Deep Think task follows; the scoring half of §4 + retirement land in Plan C). Add a STATUS entry.

- [ ] **Step 3: Commit**

```bash
git add dev/docs/process/SKILL_EVOLUTION_PLAN.md dev/docs/process/STATUS.md
git commit -m "Skill evolution B shipped: second-person review (§3) + prompt-level validation/spawn (§4/§5)"
```

## Self-Review

- **Spec coverage:** §3 second-person audit → Task 2 (the 6-step prompt) ✓; the trajectory the auditor reads → Task 1 ✓. §4 validation (benchmark-else-apply) + §5 spawn-new → directed by the Task-2 prompt ✓ (the scoring tally + retirement are Plan C, by design). 
- **Placeholders:** none — full code in every step.
- **Type consistency:** `_summaries_block(layout, skill) -> str` consumed by `review_description`; reads the Plan A `SkillNote` fields; prompt names real tools (`benchmark_skill`, `reload_skills`, `record_skill_revision`, `skill_note`).
- **Note:** §4/§5 are *prompt-directed*, not new code paths — the agent executes them with existing tools. That's deliberate (the review IS an agent task); the only code is the prompt + the trajectory renderer.
