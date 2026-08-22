"""Topic-shift routing into the single primary session."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime.domain_router import (
    DOMAIN_TAG,
    detect_topic,
    domain_block,
    reset,
)
from jaeger_ai.core.runtime.dispatch import (
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
