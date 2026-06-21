"""``skill(action="list")`` pagination — the new limit / offset
/ category-filter shape.

Default ``list`` returns category counts + first ``limit`` (20)
skills, not the whole 87-skill library. The same args support
deeper paging.

This file pins:
  * default list returns category counts + a capped slice
  * ``limit`` clips the slice
  * ``offset`` skips
  * ``category=X`` filters before paging
  * ``next_offset`` is set when there's more
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from jaeger_os.agent.tools import skills as skill_tool


def _stub_playbook(name: str, category: str, desc: str = "") -> Any:
    """Minimal duck-typed playbook for the list-tool tests."""
    return SimpleNamespace(
        name=name, category=category, description=desc,
        tags=[], path=None,
    )


@pytest.fixture
def fake_playbooks(monkeypatch):
    """Replace ``available_playbooks()`` with a fixed corpus so the
    pagination tests don't depend on the real skill library."""
    corpus = [
        _stub_playbook("alpha",   "files"),
        _stub_playbook("beta",    "files"),
        _stub_playbook("gamma",   "code"),
        _stub_playbook("delta",   "code"),
        _stub_playbook("epsilon", "code"),
        _stub_playbook("zeta",    "research"),
    ]
    from jaeger_os.agent.skill_registry import playbook_skills as _pb
    monkeypatch.setattr(_pb, "available_playbooks", lambda: list(corpus))
    return corpus


# ── default behaviour ─────────────────────────────────────────────


def test_list_default_returns_category_counts(fake_playbooks):
    """Even without paging args, the response carries category
    counts — that's the cheap part the model uses to decide
    where to drill in."""
    out = skill_tool.skill(action="list")
    assert out["ok"] is True
    assert out["total"] == 6
    assert out["category_counts"] == {
        "code": 3, "files": 2, "research": 1,
    }


def test_list_default_limit_is_20(fake_playbooks):
    """Default limit is 20 — large enough that the test fixture
    (6 skills) fits in one page; the real library (~87 skills)
    won't."""
    out = skill_tool.skill(action="list")
    assert out["limit"] == 20
    assert len(out["skills"]) == 6  # fixture has 6


# ── pagination ────────────────────────────────────────────────────


def test_list_limit_clips_slice(fake_playbooks):
    out = skill_tool.skill(action="list", limit=2)
    assert len(out["skills"]) == 2
    assert out["next_offset"] == 2


def test_list_offset_skips(fake_playbooks):
    out = skill_tool.skill(action="list", limit=2, offset=2)
    assert len(out["skills"]) == 2
    assert [s["name"] for s in out["skills"]] == ["gamma", "delta"]


def test_list_no_next_offset_on_last_page(fake_playbooks):
    out = skill_tool.skill(action="list", limit=10)
    assert "next_offset" not in out


# ── category filter ───────────────────────────────────────────────


def test_list_filter_by_category(fake_playbooks):
    out = skill_tool.skill(action="list", category="code")
    assert out["filtered_total"] == 3
    assert {s["name"] for s in out["skills"]} == {"gamma", "delta", "epsilon"}


def test_list_filter_with_pagination(fake_playbooks):
    out = skill_tool.skill(action="list", category="code", limit=2)
    assert len(out["skills"]) == 2
    assert out["next_offset"] == 2


def test_list_unknown_category_returns_empty_with_counts(fake_playbooks):
    """Unknown category isn't an error — return an empty page so
    the model sees "0 skills in that category" with the full
    category list still visible."""
    out = skill_tool.skill(action="list", category="nope")
    assert out["filtered_total"] == 0
    assert out["skills"] == []
    # Category counts still surface so the model can correct.
    assert "code" in out["category_counts"]
