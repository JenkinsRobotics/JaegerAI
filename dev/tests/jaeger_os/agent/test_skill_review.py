"""Skill self-improvement review — threshold trigger + Deep Think proposal
(phases 2-3). ON by default (opt-out); when enabled, reviews auto-approve and
run, smoke/benchmark-gated. Opted out → manual + backlog.
"""

import pathlib
import tempfile

from jaeger_os.agent.background import skill_review
from jaeger_os.core import skill_notes
from jaeger_os.core.instance.instance import InstanceLayout


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
        # And the automatic on-note trigger is a no-op.
        layout = _layout()
        _bad(layout, "files", 5)
        assert skill_review.maybe_propose_on_note(layout, "files") is None
    finally:
        skill_review.set_enabled(True)               # restore the default


def test_auto_trigger_fires_by_default() -> None:
    layout = _layout()
    _bad(layout, "weather", 3)
    r = skill_review.maybe_propose_on_note(layout, "weather")
    assert r and r["proposed"] is True and r["status"] == "ready"


def test_review_tools_registered() -> None:
    from jaeger_os.agent.schemas import tool_registry as R
    import jaeger_os.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"request_skill_review", "set_skill_review",
            "record_skill_revision"} <= names
