"""Rich rendering for the kanban board — the visual side of ``/board``.

The data layer (:mod:`jaeger_os.agent.background.board`) stays presentation-free; this
module owns the layout decisions: five side-by-side panels (one per
column), each holding stacked card snippets that wrap to the panel width.

The renderer is a pure function — ``render_board(cards) -> RenderableType``
— so the TUI command is a one-liner and tests can pin the output without
booting a TUI.
"""

from __future__ import annotations

from typing import Iterable

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from jaeger_os.agent.background.board import COLUMNS, Card


# Same column-tint as the legacy vertical view, kept stable so the eye
# can tell the columns apart at a glance.
_COLUMN_STYLE: dict[str, str] = {
    "backlog":     "dim",
    "ready":       "cyan",
    "in_progress": "bold yellow",
    "blocked":     "red",
    "done":        "green",
}

# Priority dot — three small marks that don't fight the title for space.
_PRIORITY_MARK: dict[str, str] = {"high": "●", "med": "•", "low": "·"}


def _card_block(card: Card) -> RenderableType:
    """One card's worth of vertical space inside a column panel: a
    priority dot + title line, then dim metadata (id + tags) underneath."""
    title = Text()
    title.append(f"{_PRIORITY_MARK.get(card.priority, '•')} ", style="bold")
    title.append(card.title or "(untitled)")

    meta_parts: list[str] = [card.id]
    if card.tags:
        meta_parts.append(",".join(card.tags))
    meta = Text("  ".join(meta_parts), style="dim")

    return Group(title, meta)


def _column_panel(col: str, cards: list[Card]) -> Panel:
    style = _COLUMN_STYLE.get(col, "white")
    header = Text()
    header.append(col, style=f"bold {style}")
    header.append(f"  ({len(cards)})", style="dim")

    if not cards:
        body: RenderableType = Text("—", style="dim")
    else:
        blocks: list[RenderableType] = []
        for i, card in enumerate(cards):
            if i:
                # Thin divider between cards so they don't visually merge.
                blocks.append(Text("─" * 3, style="dim"))
            blocks.append(_card_block(card))
        body = Group(*blocks)

    return Panel(body, title=header, border_style=style, padding=(0, 1))


def render_board(cards: Iterable[Card], *, width: int | None = None) -> RenderableType:
    """Render the whole board as five side-by-side column panels.

    ``cards`` is the full flat card list (typically ``board.list()``);
    this function buckets them by column. ``width`` lets a caller cap
    total render width — handy when the terminal is narrow enough that
    five equal panels would each be unreadably thin. ``None`` lets Rich
    use the console's full width.
    """
    cards = list(cards)
    by_col: dict[str, list[Card]] = {col: [] for col in COLUMNS}
    for c in cards:
        if c.column in by_col:
            by_col[c.column].append(c)

    panels = [_column_panel(col, by_col[col]) for col in COLUMNS]
    # equal=True makes every column the same width; expand=True fills
    # the available terminal width so the grid feels intentional rather
    # than left-aligned-with-trailing-space.
    return Columns(panels, equal=True, expand=True, width=width)


def render_board_empty_hint() -> RenderableType:
    """Friendly empty-state message — used when there are zero cards."""
    return Text.from_markup(
        "[dim]The board is empty. [bold]/board add <title>[/] to start.[/]"
    )
