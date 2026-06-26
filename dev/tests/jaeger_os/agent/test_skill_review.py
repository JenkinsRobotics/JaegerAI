"""Skill self-improvement review — threshold trigger + Deep Think proposal
(phases 2-3). Approval follows the autonomy mode; the auto-trigger is off by
default.
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


def test_approval_follows_autonomy_mode() -> None:
    from jaeger_os.core.runtime import autonomy
    try:
        autonomy.set_autonomy("auto")
        r = skill_review.propose_review(_layout(), "weather", force=True)
        assert r["proposed"] and r["approved"] is True and r["status"] == "ready"

        autonomy.set_autonomy("scoped")
        r2 = skill_review.propose_review(_layout(), "files", force=True)
        assert r2["proposed"] and r2["approved"] is False and r2["status"] == "backlog"
    finally:
        autonomy.set_autonomy(autonomy.DEFAULT)


def test_auto_trigger_off_by_default_is_noop() -> None:
    layout = _layout()
    assert skill_review.auto_trigger_enabled() is False
    _bad(layout, "weather", 5)
    assert skill_review.maybe_propose_on_note(layout, "weather") is None


def test_auto_trigger_fires_when_enabled() -> None:
    from jaeger_os.core.runtime import autonomy
    try:
        layout = _layout()
        skill_review.set_auto_trigger(True)
        autonomy.set_autonomy("scoped")
        _bad(layout, "weather", 3)
        r = skill_review.maybe_propose_on_note(layout, "weather")
        assert r and r["proposed"] is True and r["status"] == "backlog"
    finally:
        skill_review.set_auto_trigger(False)
        autonomy.set_autonomy(autonomy.DEFAULT)


def test_review_tools_registered() -> None:
    from jaeger_os.agent.schemas import tool_registry as R
    import jaeger_os.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"request_skill_review", "set_skill_review"} <= names
