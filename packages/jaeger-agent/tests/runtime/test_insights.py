from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from jaeger_agent.memory import memory as mem, sqlite_store
from jaeger_agent.tools import insights


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    old = mem.set_memory_source("benchmark")
    yield
    mem.set_memory_source(old)
    sqlite_store.close()


def record(**extra):
    return insights.record_insight("chronicle-test", "question-2", "Which regions recovered first?",
        "open_question", ["https://www.nature.com/articles/ngeo2652"], **extra)


def test_exact_recall_survives_reopen_and_is_not_an_owner_fact(tmp_path):
    out = record()
    assert out["local_verified"]
    assert out["honcho"]["status"] == "not_requested"
    assert mem.list_facts(subject="user") == {}
    sqlite_store.close()
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    assert insights.recall_insight("chronicle-test", "question-2")["record"] == out["record"]
    assert not insights.recall_insight("chronicle-test", "question")["found"]
    assert not insights.recall_insight("other-topic", "question-2")["found"]


def test_duplicate_is_idempotent_and_different_content_is_rejected():
    assert record()["ok"]
    assert record()["ok"]
    conflict = insights.record_insight("chronicle-test", "question-2", "Different question", "open_question", ["https://example.org"])
    assert not conflict["ok"]
    assert len(mem.recall_history("insight:question-2", subject="research:chronicle-test")) == 1


def test_concurrent_admission_has_one_winner():
    def admit(i):
        return mem.remember_if_absent("id", str(i), subject="research:race", category="research")
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(admit, range(8)))
    assert len(set(values)) == 1
    assert len(mem.recall_history("id", subject="research:race")) == 1


def test_honcho_outage_does_not_masquerade_as_remote_durability(monkeypatch):
    class Offline:
        def health(self): return False
        def list_messages(self, session): return {"error": "offline"}
    monkeypatch.setattr(insights, "_honcho", Offline)
    out = record(share_publicly_with_honcho=True)
    assert out["local_verified"]
    assert not out["honcho"]["verified"]
    remote = insights.recall_insight("chronicle-test", "question-2", backend="honcho")
    assert not remote["ok"] and not remote["found"]


def test_honcho_requires_message_readback_and_never_retries_lost_write(monkeypatch):
    class Remote:
        def __init__(self): self.writes = []; self.lost = False
        def health(self): return True
        def get_peer(self, peer): return {"id": peer}
        def get_session(self, session): return {"id": session}
        def list_messages(self, session):
            return {"items": [{"id": str(i), "content": body} for i, body in enumerate(self.writes)]}
        def add_message(self, session, peer, body):
            self.writes.append(body)
            return {"error": "response lost"} if self.lost else {"ok": True}
    remote = Remote()
    monkeypatch.setattr(insights, "_honcho", lambda: remote)
    remote.lost = True
    first = record(share_publicly_with_honcho=True)
    assert not first["honcho"]["verified"]
    assert len(remote.writes) == 1
    # Explicit later call reconciles by readback, without a second write.
    assert record(share_publicly_with_honcho=True)["honcho"]["verified"]
    assert len(remote.writes) == 1
    assert insights.recall_insight("chronicle-test", "question-2", "honcho")["found"]


@pytest.mark.parametrize("status,sources", [("certain", ["https://example.org"]), ("supported", []), ("hypothesis", ["file:///tmp/x"])])
def test_invalid_research_claim_is_not_written(status, sources):
    assert not insights.record_insight("trial", "claim", "Something", status, sources)["ok"]
    assert mem.list_facts(subject="research:trial") == {}
