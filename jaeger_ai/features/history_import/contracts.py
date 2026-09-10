"""Source-neutral transcript import contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ParsedConversation:
    source: str
    source_path: Path
    original_id: str
    title: str
    messages: tuple[dict[str, Any], ...]
    model: str = ""
    workspace: str = ""


class HistorySource(Protocol):
    source_id: str

    def discover(self) -> tuple[Path, ...]: ...

    def parse(self, path: Path) -> ParsedConversation | None: ...
