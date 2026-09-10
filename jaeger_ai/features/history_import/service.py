"""Idempotent import coordinator for external agent transcripts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jaeger_ai.core.sessions import SessionStore

from .ares import AresHistorySource
from .claude import ClaudeHistorySource
from .codex import CodexHistorySource
from .contracts import HistorySource
from .gemini import GeminiHistorySource
from .grok import GrokHistorySource


@dataclass(frozen=True, slots=True)
class ImportReport:
    source: str
    discovered: int
    imported: int
    skipped: int
    failed: int
    messages: int


class HistoryImportService:
    def __init__(
        self,
        sessions: SessionStore,
        sources: tuple[HistorySource, ...] | None = None,
    ) -> None:
        self.sessions = sessions
        self.sources = sources or (
            AresHistorySource(),
            ClaudeHistorySource(),
            CodexHistorySource(),
            GeminiHistorySource(),
            GrokHistorySource(),
        )

    def scan(self) -> dict[str, int]:
        return {source.source_id: len(source.discover()) for source in self.sources}

    def import_all(
        self,
        *,
        selected: set[str] | None = None,
        limit_per_source: int | None = None,
    ) -> tuple[ImportReport, ...]:
        reports = []
        for source in self.sources:
            if selected and source.source_id not in selected:
                continue
            paths = source.discover()
            if limit_per_source is not None:
                paths = paths[: max(0, limit_per_source)]
            imported = skipped = failed = messages = 0
            for path in paths:
                try:
                    parsed = source.parse(path)
                    if parsed is None:
                        skipped += 1
                        continue
                    digest = hashlib.sha256(
                        f"{parsed.source}:{parsed.original_id}:{parsed.source_path}".encode()
                    ).hexdigest()[:24]
                    result = self.sessions.import_transcript(
                        f"import:{parsed.source}:{digest}",
                        [
                            {
                                **row,
                                "metadata": {
                                    "import_source": parsed.source,
                                    "original_session_id": parsed.original_id,
                                    "source_path": str(parsed.source_path),
                                    "workspace": parsed.workspace,
                                },
                            }
                            for row in parsed.messages
                        ],
                        title=parsed.title,
                        model=parsed.model,
                        provider=parsed.source,
                        origin=parsed.source,
                    )
                    if result["created"]:
                        imported += 1
                        messages += int(result.get("messages") or 0)
                    else:
                        skipped += 1
                except (OSError, ValueError):
                    failed += 1
            reports.append(
                ImportReport(
                    source.source_id,
                    len(paths),
                    imported,
                    skipped,
                    failed,
                    messages,
                )
            )
        return tuple(reports)
