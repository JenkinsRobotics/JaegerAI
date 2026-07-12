"""Slash-command session-state mutations on Phase-9 message lists.

``/new`` and ``/undo`` (via ``reset_session`` / ``pop_last_exchange``)
used to touch only ``_session_histories`` — the legacy pydantic-ai
storage. Phase-9 conversation state actually lives on
``JaegerAgent.messages`` for sessions that have been routed through
the new agent path, so the old code path made those commands silent
no-ops for current sessions.

These tests pin the corrected behavior: both APIs operate on the
JaegerAgent's messages first, with the legacy list as fallback.

We don't need a real LLM or adapter — just a stub JaegerAgent-like
object with a ``messages`` attribute, plugged into
``_jaeger_agents_by_session`` via monkeypatch.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import jaeger_ai.main as main


@pytest.fixture
def stub_agent(monkeypatch):
    """Plant a stub JaegerAgent in the per-session cache with a
    pre-populated message list. Returns the same object so tests can
    assert on it directly."""
    agent = SimpleNamespace(messages=[])
    # Replace the session-cache so we don't pollute other tests.
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"_default_": agent})
    # Clear legacy histories too so the path doesn't accidentally
    # satisfy the test via the fallback.
    monkeypatch.setattr(main, "_session_histories", {})
    return agent


# ── reset_session (/new, /reset) ─────────────────────────────────────


def test_reset_session_clears_jaeger_agent_messages(stub_agent):
    """The original bug — `/new` left the JaegerAgent's messages
    untouched so the next turn still saw the old context. Reset must
    clear that list."""
    stub_agent.messages = [
        {"role": "user", "content": "old turn 1"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "old turn 2"},
    ]
    dropped = main.reset_session("_default_")
    assert dropped == 3
    assert stub_agent.messages == []


def test_reset_session_with_no_agent_is_a_noop(monkeypatch):
    """If no agent has been built for the session yet (very fresh
    boot), reset should still succeed — there's just nothing to drop."""
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {})
    monkeypatch.setattr(main, "_session_histories", {})
    assert main.reset_session("nonexistent") == 0


def test_reset_session_clears_both_paths_when_present(monkeypatch):
    """Hybrid session that's accumulated history in BOTH the legacy
    list AND the Phase-9 messages list — reset clears everything."""
    legacy_msgs = [object(), object()]
    monkeypatch.setattr(main, "_session_histories",
                        {"hybrid": list(legacy_msgs)})
    agent = SimpleNamespace(messages=[
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "y"},
    ])
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"hybrid": agent})
    dropped = main.reset_session("hybrid")
    assert dropped == 4    # 2 legacy + 2 phase-9
    assert agent.messages == []
    assert main._session_histories["hybrid"] == []


# ── pop_last_exchange (/undo, /retry) ────────────────────────────────


def test_pop_last_exchange_drops_phase_9_tail(stub_agent):
    """`/undo` must drop the most recent user→assistant exchange from
    the JaegerAgent's messages. Earlier turns stay."""
    stub_agent.messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "turn 2 — the one to undo"},
        {"role": "assistant", "content": "reply 2"},
    ]
    user_text = main.pop_last_exchange("_default_")
    assert user_text == "turn 2 — the one to undo"
    # The latest user message + everything after is gone.
    assert len(stub_agent.messages) == 2
    assert stub_agent.messages[-1]["content"] == "reply 1"


def test_pop_last_exchange_drops_in_flight_tool_chain(stub_agent):
    """The dropped slice must include any assistant/tool messages
    AFTER the latest user message — that's the in-flight turn,
    inseparable from the user prompt that started it."""
    stub_agent.messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second — undo me"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_time",
         "content": "noon"},
        {"role": "assistant", "content": "It's noon."},
    ]
    user_text = main.pop_last_exchange("_default_")
    assert user_text == "second — undo me"
    # Pre-turn-2 state remains.
    assert len(stub_agent.messages) == 2
    assert all(m.get("role") in ("user", "assistant")
               and m.get("content") in ("first", "ack")
               for m in stub_agent.messages)


def test_pop_last_exchange_on_empty_session_returns_none(stub_agent):
    stub_agent.messages = []
    assert main.pop_last_exchange("_default_") is None


def test_pop_last_exchange_with_only_assistant_messages_returns_none(stub_agent):
    """Edge case: a session that somehow has only assistant turns (no
    user — should never happen but defensive). Returns None instead
    of mangling the list."""
    stub_agent.messages = [
        {"role": "assistant", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    assert main.pop_last_exchange("_default_") is None
    # Unchanged.
    assert len(stub_agent.messages) == 2


# ── last_ctx_snapshot (status-bar ctx gauge) ─────────────────────────


def test_last_ctx_snapshot_empty_without_agent(monkeypatch):
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {})
    assert main.last_ctx_snapshot("nope") == {}


def test_last_ctx_snapshot_computes_pct(monkeypatch):
    guard = SimpleNamespace(
        estimate_messages_tokens=lambda msgs, system_prompt, tools: 500,
        budget=SimpleNamespace(prompt_budget=2000),
    )
    agent = SimpleNamespace(messages=[], system_prompt="", tools=[],
                            context_guard=guard)
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"s": agent})
    assert main.last_ctx_snapshot("s") == {"tokens": 500, "pct": 25}


# ── resume_session_from_store (native History → load_session) ───────────


def test_resume_session_from_store_replays_capped_history(monkeypatch, tmp_path):
    """load_session's EXPLICIT resume: full turn list returned for the UI,
    and (capped to the same window a live turn trims to) replayed into the
    target session's JaegerAgent.messages so the next turn sees context."""
    from jaeger_ai.core.sessions import SessionStore

    store = SessionStore(tmp_path / "s.db")
    for i in range(3):
        store.record("picked", "user", f"question {i}")
        store.record("picked", "assistant", f"answer {i}")
    monkeypatch.setattr("jaeger_ai.core.sessions.get_store", lambda layout=None: store)

    built = SimpleNamespace(messages=[{"role": "user", "content": "stale seed"}])
    calls = []

    def fake_ensure(client, session_key):
        calls.append((client, session_key))
        return built

    monkeypatch.setattr(main, "_ensure_session_agent", fake_ensure)
    monkeypatch.setattr(main, "_session_loaded", set())
    monkeypatch.setattr(main, "_session_state", {"picked": {"stale": 1}})

    client = object()
    turns = main.resume_session_from_store(client, "picked")

    assert len(turns) == 6                       # the FULL turn list
    assert calls == [(client, "picked")]
    assert built.messages == [
        {"role": "user", "content": "question 0"},
        {"role": "assistant", "content": "answer 0"},
        {"role": "user", "content": "question 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "question 2"},
        {"role": "assistant", "content": "answer 2"},
    ]
    assert "picked" in main._session_loaded
    assert "picked" not in main._session_state
    store.close()


def test_resume_session_from_store_caps_to_max_history_window(monkeypatch, tmp_path):
    from jaeger_ai.core.sessions import SessionStore

    store = SessionStore(tmp_path / "s.db")
    for i in range(30):                           # well over _MAX_HISTORY_MESSAGES*2
        store.record("long", "user", f"q{i}")
        store.record("long", "assistant", f"a{i}")
    monkeypatch.setattr("jaeger_ai.core.sessions.get_store", lambda layout=None: store)

    built = SimpleNamespace(messages=[])
    monkeypatch.setattr(main, "_ensure_session_agent",
                        lambda client, key: built)

    turns = main.resume_session_from_store(object(), "long")
    assert len(turns) == 60                        # uncapped return
    cap = main._MAX_HISTORY_MESSAGES * 2
    assert len(built.messages) == cap
    assert built.messages[-1] == {"role": "assistant", "content": "a29"}
    store.close()


def test_resume_session_from_store_without_client_skips_replay(monkeypatch, tmp_path):
    """Browsing History before the agent has booted: still returns the
    turns for the UI, but there's no live agent to seed."""
    from jaeger_ai.core.sessions import SessionStore

    store = SessionStore(tmp_path / "s.db")
    store.record("s1", "user", "hi")
    monkeypatch.setattr("jaeger_ai.core.sessions.get_store", lambda layout=None: store)

    def explode(client, key):
        raise AssertionError("must not build an agent with no client")

    monkeypatch.setattr(main, "_ensure_session_agent", explode)
    turns = main.resume_session_from_store(None, "s1")
    assert len(turns) == 1
    store.close()


def test_resume_session_from_store_replay_failure_still_returns_turns(monkeypatch, tmp_path):
    """The replay is best-effort: if building the session's live agent
    blows up (e.g. a client shape the adapter layer doesn't recognize),
    the operator must still get their History view back, just without
    live continuation — display must not fail with the replay."""
    from jaeger_ai.core.sessions import SessionStore

    store = SessionStore(tmp_path / "s.db")
    store.record("s1", "user", "hi")
    store.record("s1", "assistant", "hello")
    monkeypatch.setattr("jaeger_ai.core.sessions.get_store", lambda layout=None: store)

    def explode(client, key):
        raise RuntimeError("no adapter for this client shape")

    monkeypatch.setattr(main, "_ensure_session_agent", explode)
    turns = main.resume_session_from_store(object(), "s1")
    assert [t["text"] for t in turns] == ["hi", "hello"]
    store.close()


def test_resume_session_from_store_unknown_session_returns_empty(monkeypatch, tmp_path):
    from jaeger_ai.core.sessions import SessionStore

    store = SessionStore(tmp_path / "s.db")
    monkeypatch.setattr("jaeger_ai.core.sessions.get_store", lambda layout=None: store)
    assert main.resume_session_from_store(object(), "nope") == []
    store.close()
