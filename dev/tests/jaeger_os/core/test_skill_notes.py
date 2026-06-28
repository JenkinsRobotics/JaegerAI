"""Skill usage notes — the per-use journal (phase 1 of skill self-improvement)."""

import pathlib
import tempfile

from jaeger_os.core import skill_notes
from jaeger_os.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def test_add_note_appends_and_normalises_outcome() -> None:
    layout = _layout()
    n = skill_notes.add_note(layout, skill="time", outcome="SMOOTH",
                             note="answered instantly")
    assert n.skill == "time" and n.outcome == "smooth" and n.ts
    # Unknown outcome label -> recorded as 'issues' (still a signal).
    n2 = skill_notes.add_note(layout, skill="files", outcome="weird", note="x")
    assert n2.outcome == "issues"
    # Both lines landed in the journal.
    assert len(skill_notes.all_notes(layout)) == 2
    assert skill_notes.notes_path(layout).exists()


def test_notes_for_filters_by_skill() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="time", outcome="smooth", note="a")
    skill_notes.add_note(layout, skill="time", outcome="slow", note="b")
    skill_notes.add_note(layout, skill="files", outcome="failed", note="c")
    time_notes = skill_notes.notes_for(layout, "time")
    assert len(time_notes) == 2 and {n.note for n in time_notes} == {"a", "b"}
    assert skill_notes.notes_for(layout, "nope") == []


def test_summary_tallies_outcomes_per_skill() -> None:
    layout = _layout()
    for o in ("failed", "failed", "issues", "smooth"):
        skill_notes.add_note(layout, skill="files", outcome=o, note="")
    s = skill_notes.summary(layout)
    assert s["files"]["failed"] == 2
    assert s["files"]["issues"] == 1 and s["files"]["smooth"] == 1


def test_broken_line_never_breaks_the_journal() -> None:
    layout = _layout()
    skill_notes.add_note(layout, skill="time", outcome="smooth", note="ok")
    # Corrupt the file with a junk line; loading must skip it, keep the good one.
    p = skill_notes.notes_path(layout)
    p.write_text(p.read_text() + "{not valid json\n", encoding="utf-8")
    assert len(skill_notes.all_notes(layout)) == 1


def test_add_note_stores_structured_fields() -> None:
    layout = _layout()
    n = skill_notes.add_note(layout, skill="weather", outcome="issues",
                             note="slow", objective="get forecast", calls=7,
                             procedure="read,read,read,fetch",
                             errors="404 then retry", flag=True)
    assert n.calls == 7 and n.flag is True and n.objective == "get forecast"
    loaded = skill_notes.notes_for(layout, "weather")[0]
    assert loaded.calls == 7 and loaded.flag is True
    assert loaded.errors == "404 then retry"


def test_old_lines_without_new_fields_still_load() -> None:
    layout = _layout()
    p = skill_notes.notes_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"skill":"x","outcome":"smooth","note":"old","ts":"t"}\n',
                 encoding="utf-8")
    n = skill_notes.notes_for(layout, "x")[0]
    assert n.calls == 0 and n.flag is False        # defaults fill missing fields


def test_tools_registered() -> None:
    from jaeger_os.agent.schemas import tool_registry as R
    import jaeger_os.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"skill_note", "skill_notes"} <= names
