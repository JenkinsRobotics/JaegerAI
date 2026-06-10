"""Kanban board — the agent's unified task surface.

See docs/kanban_design.md. One board per instance, persisted at
``<instance>/memory/board.json``. Cards move across five fixed columns:

    backlog → ready → in_progress → done
                          ↘ blocked ↗

The board is the single store behind both ad-hoc task planning and Deep
Think — a Deep Think job is a card with ``source="deepthink"`` (see
:class:`jaeger_os.agent.background.deep_think.DeepThinkQueue`, which is a thin view
over this board).

This module is the pure data layer — no dependency on jaeger_os.main,
so it stays import-clean.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


COLUMNS = ("backlog", "ready", "in_progress", "blocked", "done")
PRIORITIES = ("low", "med", "high")


@dataclass
class Card:
    """One unit of work on the board."""

    title: str
    column: str = "backlog"
    id: str = field(default_factory=lambda: "card_" + uuid.uuid4().hex[:10])
    description: str = ""
    # source: who/what the card belongs to — user / agent / goal /
    # deepthink / schedule. created_by: user or agent (origin actor).
    source: str = "user"
    created_by: str = "user"
    tags: list[str] = field(default_factory=list)
    parent: str | None = None
    priority: str = "med"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    notes: str = ""
    result: str = ""
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Card":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


class Board:
    """JSON-backed kanban board at ``<instance>/memory/board.json``.

    Small files — every mutation rewrites the whole document atomically.
    Mirrors the simple persistence the facts store uses; the board
    rarely holds more than a few dozen cards."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ── persistence ─────────────────────────────────────────────────

    def _load(self) -> list[Card]:
        if not self.path.is_file():
            return []
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a corrupt board is an empty board
            return []
        return [Card.from_dict(c) for c in doc.get("cards", []) if isinstance(c, dict)]

    def _save(self, cards: list[Card]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"cards": [c.to_dict() for c in cards]}, indent=2,
                       ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ── operations ──────────────────────────────────────────────────

    def add(
        self,
        title: str,
        *,
        column: str = "backlog",
        description: str = "",
        source: str = "user",
        created_by: str = "user",
        tags: list[str] | None = None,
        parent: str | None = None,
        priority: str = "med",
    ) -> Card:
        """Create a card. Defaults to the ``backlog`` column."""
        if column not in COLUMNS:
            column = "backlog"
        if priority not in PRIORITIES:
            priority = "med"
        card = Card(
            title=title.strip(), column=column, description=description.strip(),
            source=source, created_by=created_by, tags=list(tags or []),
            parent=parent, priority=priority,
        )
        cards = self._load()
        cards.append(card)
        self._save(cards)
        return card

    def get(self, card_id: str) -> Card | None:
        for c in self._load():
            if c.id == card_id:
                return c
        return None

    def list(
        self,
        *,
        column: str | None = None,
        tag: str | None = None,
        source: str | None = None,
    ) -> list[Card]:
        """Cards, optionally filtered. Order: column order, then priority,
        then creation time — so a reader sees the pipeline left to right."""
        cards = self._load()
        if column is not None:
            cards = [c for c in cards if c.column == column]
        if tag is not None:
            cards = [c for c in cards if tag in c.tags]
        if source is not None:
            cards = [c for c in cards if c.source == source]
        col_rank = {c: i for i, c in enumerate(COLUMNS)}
        pri_rank = {"high": 0, "med": 1, "low": 2}
        cards.sort(key=lambda c: (col_rank.get(c.column, 99),
                                  pri_rank.get(c.priority, 1), c.created_at))
        return cards

    def move(self, card_id: str, column: str) -> Card | None:
        """Move a card to ``column``. Stamps started_at / finished_at as
        the card enters in_progress / done."""
        if column not in COLUMNS:
            return None
        return self._mutate(card_id, lambda c: self._apply_move(c, column))

    @staticmethod
    def _apply_move(card: Card, column: str) -> None:
        card.column = column
        if column == "in_progress" and card.started_at is None:
            card.started_at = time.time()
        if column == "done":
            card.finished_at = time.time()

    def update(self, card_id: str, **fields: Any) -> Card | None:
        """Update mutable fields of a card (title, description, tags,
        priority, parent, notes, result, attempts, started/finished_at,
        created_by, source). ``column`` is ignored here — use move()."""
        allowed = {
            "title", "description", "tags", "priority", "parent", "notes",
            "result", "attempts", "started_at", "finished_at",
            "created_by", "source",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        return self._mutate(card_id, lambda c: [setattr(c, k, v) for k, v in clean.items()])

    def remove(self, card_id: str) -> bool:
        cards = self._load()
        kept = [c for c in cards if c.id != card_id]
        if len(kept) == len(cards):
            return False
        self._save(kept)
        return True

    def summary(self) -> dict[str, int]:
        """Card counts per column + total."""
        cards = self._load()
        out: dict[str, int] = {col: 0 for col in COLUMNS}
        for c in cards:
            out[c.column] = out.get(c.column, 0) + 1
        out["total"] = len(cards)
        return out

    # ── internals ───────────────────────────────────────────────────

    def _mutate(self, card_id: str, fn: Any) -> Card | None:
        cards = self._load()
        for c in cards:
            if c.id == card_id:
                fn(c)
                c.updated_at = time.time()
                self._save(cards)
                return c
        return None


def board_for_layout(layout: Any) -> Board:
    """The Board for an instance layout — ``<instance>/memory/board.json``."""
    return Board(layout.memory_dir / "board.json")


# ── prompt digest ──────────────────────────────────────────────────


_DIGEST_TITLE_LEN = 60
_DIGEST_MAX_PER_COL = 6  # cap each column's titles so the digest stays compact


def board_digest(layout: Any) -> str:
    """One short paragraph summarising the actionable cards on the
    board — designed to be injected into the agent's system prompt
    so the model sees "you have N things waiting" on every turn.

    Empty string when there's nothing actionable (no backlog, no
    ready, no in_progress). The "done"/"blocked" columns are NOT
    surfaced — the agent should not be nudged to revisit completed
    or user-blocked work; only the live queue gets attention.

    Format::

        BOARD STATUS — work to pick up when you have free time:
          in_progress (1):
            • card_abc — finish the v0.5 release notes
          ready (2):
            • card_def — write a blog post about Jaeger
            • card_ghi — port the macOS skill to linux
          backlog (3):
            • card_jkl — investigate kanban autonomy
            ...

    Capped at ~6 titles per column so a runaway board doesn't blow
    the context budget. Titles are truncated to ~60 chars."""
    try:
        board = board_for_layout(layout)
        cards = board.list()
    except Exception:  # noqa: BLE001 — digest must never block boot
        return ""

    columns_in_order = ("in_progress", "ready", "backlog")
    bucket: dict[str, list[Card]] = {col: [] for col in columns_in_order}
    for c in cards:
        if c.column in bucket:
            bucket[c.column].append(c)
    if not any(bucket.values()):
        return ""

    # Sort each bucket by priority then created_at so the most
    # important work surfaces at the top of its column.
    prio_rank = {"high": 0, "med": 1, "low": 2}
    for col, items in bucket.items():
        items.sort(key=lambda c: (prio_rank.get(c.priority, 1), c.created_at))

    lines: list[str] = [
        "BOARD STATUS — work to pick up when you have free time:",
    ]
    for col in columns_in_order:
        items = bucket[col]
        if not items:
            continue
        lines.append(f"  {col} ({len(items)}):")
        for card in items[:_DIGEST_MAX_PER_COL]:
            title = (card.title or "").strip().replace("\n", " ")
            if len(title) > _DIGEST_TITLE_LEN:
                title = title[: _DIGEST_TITLE_LEN - 1] + "…"
            tag_hint = f" [{','.join(card.tags)}]" if card.tags else ""
            lines.append(f"    • {card.id} — {title}{tag_hint}")
        if len(items) > _DIGEST_MAX_PER_COL:
            lines.append(f"    … and {len(items) - _DIGEST_MAX_PER_COL} more "
                         f"(call board_view(column={col!r}) to see all)")
    return "\n".join(lines)


def has_actionable_work(layout: Any) -> bool:
    """True when any card sits in backlog / ready / in_progress —
    the trigger for the idle-tick autonomous board worker."""
    try:
        board = board_for_layout(layout)
        for c in board.list():
            if c.column in ("backlog", "ready", "in_progress"):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False
