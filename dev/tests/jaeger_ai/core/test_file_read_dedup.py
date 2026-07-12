"""file_read unchanged-read dedup.

Re-reading a file that has not changed re-injects its whole content into the
context for no gain — a common spin in long execution chains. ``file_read``
now tracks each (file, offset, limit) read for the turn; once the same
unchanged read has been served twice it returns a stub. ``reset_read_tracker``
is called once per turn so dedup only ever fires within a single turn.
"""

from __future__ import annotations

import os
import time

import pytest

from jaeger_ai.agent import tools
from jaeger_ai.core.instance.instance import InstanceLayout


@pytest.fixture()
def bound_instance(tmp_path):
    """A temp instance with tools bound and a clean read tracker."""
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    tools.reset_read_tracker()
    return layout


def test_first_two_reads_return_content(bound_instance):
    tools.file_write("t.txt", "hello\n")
    r1 = tools.file_read("skills/t.txt")
    r2 = tools.file_read("skills/t.txt")
    assert r1["content"] == "hello\n"
    assert r2["content"] == "hello\n"
    assert r1.get("unchanged") is not True
    assert r2.get("unchanged") is not True


def test_third_identical_read_is_stubbed(bound_instance):
    tools.file_write("s.txt", "hello\n")
    tools.file_read("skills/s.txt")
    tools.file_read("skills/s.txt")
    r3 = tools.file_read("skills/s.txt")
    assert r3["read"] is True
    assert r3["unchanged"] is True
    assert "content" not in r3
    assert "note" in r3


def test_changed_file_is_re_read_fresh(bound_instance):
    """A different mtime means the file changed — dedup must not stub it,
    even past the read threshold."""
    layout = bound_instance
    tools.file_write("c.txt", "v1\n")
    tools.file_read("skills/c.txt")
    tools.file_read("skills/c.txt")
    assert tools.file_read("skills/c.txt").get("unchanged") is True

    real = layout.skills_dir / "c.txt"
    real.write_text("v2\n", encoding="utf-8")
    future = time.time() + 100
    os.utime(real, (future, future))

    fresh = tools.file_read("skills/c.txt")
    assert fresh.get("unchanged") is not True
    assert fresh["content"] == "v2\n"


def test_paged_reads_have_independent_dedup(bound_instance):
    """A paged read is a distinct (file, offset, limit) key — it is not
    deduped against whole-file reads."""
    tools.file_write("big.txt", "".join(f"l{i}\n" for i in range(50)))
    tools.file_read("skills/big.txt")
    tools.file_read("skills/big.txt")
    assert tools.file_read("skills/big.txt").get("unchanged") is True

    page = tools.file_read("skills/big.txt", offset=0, limit=5)
    assert page.get("unchanged") is not True
    assert "content" in page


def test_reset_read_tracker_clears_state(bound_instance):
    tools.file_write("r.txt", "data\n")
    tools.file_read("skills/r.txt")
    tools.file_read("skills/r.txt")
    assert tools.file_read("skills/r.txt").get("unchanged") is True

    tools.reset_read_tracker()
    fresh = tools.file_read("skills/r.txt")
    assert fresh.get("unchanged") is not True
    assert fresh["content"] == "data\n"
