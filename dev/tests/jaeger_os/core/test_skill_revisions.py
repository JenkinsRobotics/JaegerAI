"""Skill revision log — the audit trail of recipe-skill modifications."""

import pathlib
import tempfile

from jaeger_os.core import skill_revisions
from jaeger_os.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def test_record_normalises_version_and_appends() -> None:
    layout = _layout()
    # '3' / 'v3' / '_v3' / 'weather_v3' all normalise to the 'v3' revision id.
    for v in ("3", "v3", "_v3", "weather_v3"):
        r = skill_revisions.record(layout, skill="weather", version=v,
                                   summary="fix bad-input", delta="+8%")
        assert r.version == "v3"
    assert len(skill_revisions.revisions_for(layout, "weather")) == 4
    assert skill_revisions.revisions_path(layout).exists()


def test_revisions_for_and_latest() -> None:
    layout = _layout()
    skill_revisions.record(layout, skill="weather", version="v2", summary="a")
    skill_revisions.record(layout, skill="weather", version="v3", summary="b")
    skill_revisions.record(layout, skill="files", version="v2", summary="c")
    weather = skill_revisions.revisions_for(layout, "weather")
    assert len(weather) == 2
    assert skill_revisions.latest(layout, "weather").version == "v3"
    assert skill_revisions.latest(layout, "nope") is None


def test_counts_per_skill() -> None:
    layout = _layout()
    for v in ("v2", "v3", "v4"):
        skill_revisions.record(layout, skill="weather", version=v)
    skill_revisions.record(layout, skill="files", version="v2")
    counts = skill_revisions.counts(layout)
    assert counts == {"weather": 3, "files": 1}


def test_broken_line_skipped() -> None:
    layout = _layout()
    skill_revisions.record(layout, skill="weather", version="v2")
    p = skill_revisions.revisions_path(layout)
    p.write_text(p.read_text() + "{bad json\n", encoding="utf-8")
    assert len(skill_revisions.revisions_for(layout, "weather")) == 1
