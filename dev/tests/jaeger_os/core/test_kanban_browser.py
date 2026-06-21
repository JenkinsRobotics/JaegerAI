"""Phase 2/3 consolidated tools — kanban + browser.

`kanban` wraps the existing Board; `browser` drives Playwright in a
dedicated worker thread. The live browser is covered by a headless
smoke test outside the suite — here we test the pure dispatch logic
that needs no browser launch.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent import tools
from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.agent.tools.browser import _dispatch, _element, _headless


@pytest.fixture()
def bound(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


# ── kanban — one tool, action-dispatch over the board ────────────────


def test_kanban_add_then_view(bound) -> None:
    r = tools.kanban(action="add", title="ship the thing", priority="high")
    assert r["ok"] is True
    view = tools.kanban(action="view")
    assert view["ok"] is True
    assert any(c["title"] == "ship the thing" for c in view["cards"])


def test_kanban_move_and_complete(bound) -> None:
    cid = tools.kanban(action="add", title="a task")["card_id"]
    moved = tools.kanban(action="move", card_id=cid, column="in_progress")
    assert moved["ok"] is True and moved["column"] == "in_progress"
    done = tools.kanban(action="complete", card_id=cid)
    assert done["ok"] is True and done["column"] == "done"


def test_kanban_unknown_action(bound) -> None:
    r = tools.kanban(action="teleport")
    assert r["ok"] is False and "unknown" in r["error"]


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
