"""Topic-shift routing into the single primary session."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime.domain_router import (
    DOMAIN_TAG,
    detect_topic,
    domain_block,
    reset,
)
from jaeger_ai.features.dispatcher.router import (
    is_primary_session,
    normalize_session_key,
    prepare_turn_text,
)


@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


def test_detects_project_and_switch_phrasing():
    assert detect_topic("let's work on Project Atlas") == "project Atlas"
    assert detect_topic("switch to the notes") == "notes"
    assert detect_topic("what's 2+2?") == ""


def test_same_domain_is_not_re_injected():
    # No memory bound — first shift still records the domain so a
    # repeat does not keep prepending an empty block.
    assert domain_block("let's work on Project Atlas") == ""
    assert domain_block("let's work on Project Atlas") == ""


def test_primary_session_keys():
    assert is_primary_session("desktop-app")
    assert is_primary_session("main")
    assert is_primary_session("cli")
    assert not is_primary_session("delegate:ab12")
    assert not is_primary_session("heartbeat")
    assert normalize_session_key("main", default="desktop-app") == "desktop-app"


def test_prepare_turn_text_keeps_the_user_words():
    class _Agent:
        messages: list = []
        system_prompt = ""
        context_guard = None

    out = prepare_turn_text(_Agent(), "hello there", session_key="desktop-app")
    assert out.endswith("hello there")


def test_domain_block_includes_a_matching_ledger():
    from jaeger_ai.core.runtime import work_ledger
    work_ledger.reset()
    work_ledger.work_ledger(
        action="create", task_name="Project Atlas notes", total_items=3,
    )
    reset()  # clear last-domain so the shift fires
    block = domain_block("let's work on Project Atlas")
    assert DOMAIN_TAG in block
    assert "Atlas" in block
    work_ledger.reset()


def test_dispatcher_world_context_survives_next_turn_without_recording_scaffolding(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore
    from jaeger_ai.features.dispatcher import router
    layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / 'memory')
    layout.memory_dir.mkdir()
    sqlite_store.bind(layout)
    agent = SimpleNamespace(messages=[], system_prompt='', context_guard=None)
    monkeypatch.setattr(router, 'compact_agent', lambda agent: None)
    try:
        router.prepare_turn_text(agent, 'Ben approves electrical changes.',
                                 session_key='dispatcher', ledger=False, domain=False)
        prepared = router.prepare_turn_text(agent, 'Who approves electrical changes?',
                                            session_key='dispatcher', ledger=False, domain=False)
        assert '"subject": "Ben"' in prepared
        assert agent._world_event.text == 'Who approves electrical changes?'
        claims = SqliteKnowledgeStore().list_claims(predicate='said')
        assert len(claims) == 2
        assert all('World context' not in c.value for c in claims)
        other = router.prepare_turn_text(agent, 'Who approves electrical changes?',
                                         session_key='separate', ledger=False, domain=False)
        assert '"subject": "Ben"' not in other
    finally:
        sqlite_store.close()
