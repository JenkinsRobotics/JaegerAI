"""Static kanban grid renderer.

The renderer is a pure function — cards in, RenderableType out — so we
exercise it through a width-pinned :class:`Console` and inspect the
captured text. We're not asserting exact layout (Rich is allowed to
choose its own border characters and padding), only what *must* appear:

  - every column header, with its count
  - card titles in the right column
  - the priority dot for each card
  - the empty-state hint when the board has no cards
"""

from __future__ import annotations

from rich.console import Console

from jaeger_ai.agent.background.board import Card
from jaeger_ai.interfaces.tui.board_view import (
    render_board,
    render_board_empty_hint,
)


def _capture(renderable, *, width: int = 160) -> str:
    """Render to a sized in-memory console and return the raw text. We
    pick a wide console (160) so five panels have room — the renderer's
    job is to fill the width, not to fit a phone screen."""
    console = Console(width=width, record=True, force_terminal=False)
    console.print(renderable)
    return console.export_text()


# ── headers + counts ────────────────────────────────────────────────


def test_every_column_appears_even_when_empty():
    """A board with zero cards should still show all five column
    headers — the grid is the navigational surface, so it can't
    collapse to whatever happens to be populated today."""
    out = _capture(render_board([]))
    for col in ("backlog", "ready", "in_progress", "blocked", "done"):
        assert col in out, f"missing column header: {col}"


def test_column_count_reflects_card_membership():
    """A card in ``in_progress`` should bump that column's count to 1
    and leave the others at 0."""
    cards = [Card(title="Wire the kanban grid", column="in_progress")]
    out = _capture(render_board(cards))
    # Cheap assertion: the header line contains "in_progress" and "(1)"
    # close together. Don't pin exact spacing — Rich owns that.
    assert "in_progress" in out
    assert "(1)" in out
    # Other columns still render at (0).
    assert out.count("(0)") == 4


# ── card content ────────────────────────────────────────────────────


def test_card_title_lands_in_its_column():
    """A title in the ``ready`` column should appear in the rendered
    grid (we don't try to assert *which* visual column it landed in,
    just that the title is present and the ready header shows 1)."""
    cards = [Card(title="Ship the React/ReactPy split", column="ready")]
    out = _capture(render_board(cards))
    assert "Ship the React/ReactPy split" in out
    # The ready column's count went up.
    assert "ready" in out and "(1)" in out


def test_priority_marks_distinguish_high_med_low():
    """High/med/low map to ●/•/· — the dot needs to be present so
    readers can scan priorities without reading every title."""
    cards = [
        Card(title="urgent", column="ready", priority="high"),
        Card(title="normal", column="ready", priority="med"),
        Card(title="someday", column="ready", priority="low"),
    ]
    out = _capture(render_board(cards))
    assert "●" in out  # high
    assert "•" in out  # med
    assert "·" in out  # low (this glyph is U+00B7 middle dot)


def test_card_id_and_tags_appear_in_metadata():
    """The card id is part of the metadata line so the user can copy
    it into ``/board move <id> <col>``; tags get joined with commas."""
    card = Card(title="t", column="backlog", tags=["bench", "deepthink"])
    out = _capture(render_board([card]))
    assert card.id in out
    assert "bench,deepthink" in out


def test_unknown_column_is_silently_dropped():
    """A card with a column outside the canonical five (corrupt board
    on disk, or an old persisted card) shouldn't crash the renderer —
    it just doesn't appear in the grid."""
    cards = [
        Card(title="legit", column="ready"),
        Card(title="orphan", column="archive"),  # not in COLUMNS
    ]
    out = _capture(render_board(cards))
    assert "legit" in out
    assert "orphan" not in out


# ── empty-state hint ────────────────────────────────────────────────


def test_empty_hint_points_at_the_add_command():
    """The empty-state message is a teaching moment — it has to name
    the slash command that unblocks the user, not just say 'empty'."""
    out = _capture(render_board_empty_hint())
    assert "empty" in out.lower()
    assert "/board add" in out
