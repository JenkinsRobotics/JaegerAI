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


def test_invalid_research_claim_is_not_written(status, sources):
    assert not insights.record_insight("trial", "claim", "Something", status, sources)["ok"]
    assert mem.list_facts(subject="research:trial") == {}
