"""Phase 2/3 consolidated tools — kanban + browser.

`kanban` wraps the existing Board; `browser` drives Playwright in a
dedicated worker thread. The live browser is covered by a headless
smoke test outside the suite — here we test the pure dispatch logic
that needs no browser launch.
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent import tools
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.agent.tools.browser import _dispatch, _element, _headless


@pytest.fixture()
def bound(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


# ── board — five individual verbs (no action-dispatch umbrella) ──────


def test_board_add_then_view(bound) -> None:
    r = tools.board_add(title="ship the thing", priority="high")
    assert r["ok"] is True
    view = tools.board_view()
    assert view["ok"] is True
    assert any(c["title"] == "ship the thing" for c in view["cards"])


def test_board_move_then_complete(bound) -> None:
    cid = tools.board_add(title="a task")["card_id"]
    moved = tools.board_move(card_id=cid, column="in_progress")
    assert moved["ok"] is True and moved["column"] == "in_progress"
    done = tools.board_move(card_id=cid, column="done")
    assert done["ok"] is True and done["column"] == "done"


def test_board_delete(bound) -> None:
    cid = tools.board_add(title="throwaway")["card_id"]
    assert tools.board_delete(card_id=cid)["deleted"] is True
    assert tools.board_delete(card_id=cid)["ok"] is False   # already gone
    assert tools.board_delete(card_id="")["ok"] is False     # no id


# ── browser — dispatch logic (no live browser) ───────────────────────


def test_browser_unknown_action_is_clean() -> None:
    assert "unknown" in _dispatch(None, {}, "bogus", {})["error"]


def test_browser_open_requires_a_url() -> None:
    assert _dispatch(None, {}, "open", {})["error"] == "open needs a url"


def test_browser_element_index_resolution() -> None:
    state = {"handles": ["h0", "h1", "h2"]}
    assert _element(state, 1) == "h1"
    assert _element(state, 9) is None       # out of range
    assert _element(state, "bad") is None   # non-numeric


def test_browser_headless_env(monkeypatch) -> None:
    monkeypatch.delenv("JAEGER_BROWSER_HEADLESS", raising=False)
    assert _headless() is False             # headed by default — user watches
    monkeypatch.setenv("JAEGER_BROWSER_HEADLESS", "1")
    assert _headless() is True
