from pathlib import Path

from jaeger_ai.core.sessions import SessionStore
from jaeger_ai.features.history_import.contracts import ParsedConversation
from jaeger_ai.features.history_import.service import HistoryImportService


class FakeSource:
    source_id = "codex"

    def __init__(self, path: Path) -> None:
        self.path = path

    def discover(self):
        return (self.path,)

    def parse(self, path):
        return ParsedConversation(
            "codex",
            path,
            "original-session",
            "Imported title",
            (
                {"role": "user", "text": "question", "ts": 10.0},
                {"role": "assistant", "text": "answer", "ts": 20.0},
            ),
            "gpt-test",
            "/workspace",
        )


def test_history_import_is_atomic_searchable_and_idempotent(tmp_path) -> None:
    source_path = tmp_path / "source.jsonl"
    source_path.write_text("{}\n", encoding="utf-8")
    sessions = SessionStore(tmp_path / "sessions.db")
    service = HistoryImportService(sessions, (FakeSource(source_path),))

    first = service.import_all()[0]
    second = service.import_all()[0]

    assert first.imported == 1
    assert first.messages == 2
    assert second.imported == 0
    assert second.skipped == 1
    rows = sessions.search("answer")
    assert len(rows) == 1
    assert rows[0]["origin"] == "codex"
    history = sessions.history(rows[0]["id"])
    assert [row["ts"] for row in history] == [10.0, 20.0]
    assert history[0]["metadata"]["original_session_id"] == "original-session"
    sessions.close()
