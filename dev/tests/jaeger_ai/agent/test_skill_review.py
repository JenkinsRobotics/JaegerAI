"""Skill self-improvement review — threshold trigger + Deep Think proposal
(phases 2-3). ON by default (opt-out); when enabled, reviews auto-approve and
run, smoke/benchmark-gated. Opted out → manual + backlog.
"""

import pathlib
import tempfile

from jaeger_ai.agent.background import skill_review
from jaeger_ai.core.skill_improvement import skill_notes
from jaeger_ai.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def _bad(layout, skill, n) -> None:
    for _ in range(n):
        skill_notes.add_note(layout, skill=skill, outcome="failed", note="x")


def test_needs_review_threshold_and_marker_reset() -> None:
    layout = _layout()
    assert not skill_review.needs_review(layout, "weather", threshold=3)
    _bad(layout, "weather", 3)
    assert skill_review.needs_review(layout, "weather", threshold=3)
    # A 'reviewing' marker resets the counter so a finished review isn't re-fired.
    skill_notes.add_note(layout, skill="weather", outcome="reviewing", note="q")
    assert not skill_review.needs_review(layout, "weather", threshold=3)


def test_propose_below_threshold_skips() -> None:
    layout = _layout()
    _bad(layout, "weather", 2)
    r = skill_review.propose_review(layout, "weather", threshold=3)
    assert r["proposed"] is False and r["reason"] == "below threshold"


def test_propose_dedups_while_open() -> None:
    layout = _layout()
    _bad(layout, "weather", 3)
    r1 = skill_review.propose_review(layout, "weather", threshold=3)
    assert r1["proposed"] is True and r1["task_id"]
    _bad(layout, "weather", 3)                       # more failures pile up
    r2 = skill_review.propose_review(layout, "weather", threshold=3)
    assert r2["proposed"] is False                   # a review is already queued


def test_enabled_by_default_auto_approves() -> None:
    assert skill_review.enabled() is True            # ON by default (opt-out)
    r = skill_review.propose_review(_layout(), "weather", force=True)
    assert r["proposed"] and r["approved"] is True and r["status"] == "ready"


def test_opt_out_proposes_to_backlog_and_disables_trigger() -> None:
    try:
        skill_review.set_enabled(False)
        # Manual request now lands in the backlog (operator approves).
        r = skill_review.propose_review(_layout(), "weather", force=True)
        assert r["proposed"] and r["approved"] is False and r["status"] == "backlog"
        # And the on-note fast-path is a no-op when opted out (even if flagged).
        layout = _layout()
        flagged = skill_notes.add_note(layout, skill="files", outcome="failed",
                                       note="x", flag=True)
        assert skill_review.maybe_propose_on_note(layout, flagged) is None
    finally:
        skill_review.set_enabled(True)               # restore the default


# ── probabilistic severity-weighted trigger (Plan A §2) ────────────


def test_severity_and_activation_since_last_review() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="w", outcome="failed", note="")     # 3
    skill_notes.add_note(layout, skill="w", outcome="reviewing", note="")  # resets
    skill_notes.add_note(layout, skill="w", outcome="issues", note="")     # 2
    skill_notes.add_note(layout, skill="w", outcome="slow", note="", flag=True)  # 1+4
    assert skill_review.activation(layout, "w") == 7.0     # pre-marker dropped
    assert skill_review.severity(skill_notes.SkillNote(outcome="failed")) == 3
    assert skill_review.severity(skill_notes.SkillNote(outcome="bogus")) == 0


def test_fire_probability_rails_and_shape() -> None:
    sr = skill_review
    assert sr.fire_probability(0.0) == 0.0                 # below gate
    assert sr.fire_probability(sr.S_MIN - 0.01) == 0.0     # gate
    assert sr.fire_probability(sr.S_MAX) == 1.0            # ceiling
    assert sr.fire_probability(sr.S_MAX + 5) == 1.0        # past ceiling
    mid = sr.fire_probability(sr.S0)                       # midpoint ≈ 0.5
    assert 0.49 <= mid <= 0.51
    assert sr.fire_probability(sr.S0 - 1) < mid < sr.fire_probability(sr.S0 + 1)


def test_select_respects_gate_budget_and_draw() -> None:
    import random
    sr = skill_review
    acts = {"low": 0.0, "mid": sr.S0, "hi1": sr.S_MAX, "hi2": sr.S_MAX + 3}

    class _AlwaysFire(random.Random):
        def random(self):              # noqa: D401 — always "draws low" → fires
            return 0.0

    fired = sr.select_for_review(acts, k=5, rng=_AlwaysFire())
    assert "low" not in fired                          # gated out (P==0)
    assert set(fired) >= {"hi1", "hi2"}                # ceilings always fire
    capped = sr.select_for_review(acts, k=1, rng=_AlwaysFire())
    assert capped == ["hi2"]                           # highest activation first


def test_flag_fast_path_proposes_immediately(monkeypatch) -> None:
    layout = _layout()
    called = {}
    monkeypatch.setattr(skill_review, "propose_review",
                        lambda lay, skill, **k: (called.update(skill=skill),
                                                 {"proposed": True})[1])
    flagged = skill_notes.add_note(layout, skill="w", outcome="slow", note="", flag=True)
    assert skill_review.maybe_propose_on_note(layout, flagged) == {"proposed": True}
    assert called["skill"] == "w"
    # an unflagged note defers to the sweep → no immediate proposal
    unflagged = skill_notes.add_note(layout, skill="w", outcome="slow", note="")
    assert skill_review.maybe_propose_on_note(layout, unflagged) is None


def test_sweep_proposes_selected_and_logs(monkeypatch) -> None:
    import random
    layout = _layout()
    _bad(layout, "w", 4)                               # activation 12 → ceiling
    proposed: list[str] = []
    monkeypatch.setattr(skill_review, "propose_review",
                        lambda lay, skill, **k: (proposed.append(skill),
                                                 {"proposed": True})[1])
    decisions = skill_review.sweep(layout, queue=object(), k=3, rng=random.Random(0))
    assert proposed == ["w"]
    assert decisions and decisions[0]["skill"] == "w" and decisions[0]["fired"] is True
    assert skill_review.review_log_path(layout).exists()      # decision logged


# ── the second-person review (Plan B §3) ───────────────────────────


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


def test_review_description_is_second_person_audit() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="w", outcome="failed", note="n",
                         objective="o", calls=9)
    d = skill_review.review_description(layout, "w")
    assert "AS IF" in d and "calls=9" in d                  # 2nd-person + trajectory
    assert "THE ONE LESSON" in d and "imperative" in d.lower()
    assert "change nothing" in d.lower()                    # honesty rule
    assert "benchmark_skill('w')" in d and "REVERT" in d     # measured validation
    assert "NEW skill" in d                                  # spawn-new branch
    assert "record_skill_revision('w'" in d


def test_review_tools_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"request_skill_review", "set_skill_review",
            "record_skill_revision"} <= names
