"""Memory upgrades (2026-06-12) — facts snapshot + background review.

The Hermes-comparison verdict: JROS recorded everything but the agent
only knew what it thought to search for. These tests pin the two
fixes: a bounded known-facts block frozen into the session system
prompt, and the background review that promotes conversational
signals into durable facts.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import jaeger_os.main as m


# ── facts snapshot block ───────────────────────────────────────────


def test_snapshot_renders_facts_with_lead_categories_first(monkeypatch):
    monkeypatch.setattr(m.mem, "list_facts_by_category", lambda: {
        "projects": {"jros_goal": "embodied robot brain"},
        "user": {"name": "Jon", "answer_style": "short answers"},
    })
    block = m._facts_snapshot_block()
    assert "Known facts" in block
    assert "name: Jon" in block
    assert "jros_goal" in block
    # User-identity facts lead — they shape behaviour most.
    assert block.index("name: Jon") < block.index("jros_goal")


def test_snapshot_respects_char_budget(monkeypatch):
    monkeypatch.setattr(m.mem, "list_facts_by_category", lambda: {
        "user": {f"fact_{i}": "v" * 150 for i in range(50)},
    })
    block = m._facts_snapshot_block(max_chars=600)
    assert len(block) < 800  # budget + truncation marker line
    assert "more in memory" in block


def test_snapshot_empty_when_no_facts_or_unbound(monkeypatch):
    monkeypatch.setattr(m.mem, "list_facts_by_category", lambda: {})
    assert m._facts_snapshot_block() == ""

    def _boom():
        raise RuntimeError("store not bound")
    monkeypatch.setattr(m.mem, "list_facts_by_category", _boom)
    assert m._facts_snapshot_block() == ""


# ── background memory review ───────────────────────────────────────


class _StubClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[Any] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.reply


def _wire_review_stubs(monkeypatch, *, known: dict[str, str] | None = None):
    saved: list[tuple[str, str, str]] = []
    known = known or {}
    monkeypatch.setattr(m.mem, "load_recent_turns", lambda n, session_key=None: [
        {"role": "user", "content": "by the way, call me Jon"},
        {"role": "assistant", "content": "Got it, Jon."},
    ])
    monkeypatch.setattr(m.mem, "recall", lambda key: known.get(key))
    monkeypatch.setattr(
        m.mem, "remember",
        lambda key, value, category=None: saved.append((key, value, category)),
    )
    monkeypatch.setattr(
        m.mem, "record_audit_event",
        lambda **kw: None,
    )
    return saved


def test_review_worker_promotes_facts(monkeypatch):
    saved = _wire_review_stubs(monkeypatch)
    client = _StubClient(json.dumps([
        {"key": "preferred_name", "value": "Jon", "category": "user"},
        {"key": "", "value": "junk dropped"},          # invalid → skipped
        "not a dict",                                   # invalid → skipped
    ]))
    monkeypatch.setitem(m._pipeline, "llm_lock", None)
    m._memory_review_worker(client, "voice")
    assert saved == [("preferred_name", "Jon", "user")]
    assert client.calls  # the bounded review call happened


def test_review_worker_skips_unchanged_facts(monkeypatch):
    saved = _wire_review_stubs(monkeypatch, known={"preferred_name": "Jon"})
    client = _StubClient(json.dumps([
        {"key": "preferred_name", "value": "Jon", "category": "user"},
    ]))
    monkeypatch.setitem(m._pipeline, "llm_lock", None)
    m._memory_review_worker(client, "voice")
    assert saved == []


def test_review_worker_caps_fact_count(monkeypatch):
    saved = _wire_review_stubs(monkeypatch)
    items = [{"key": f"k{i}", "value": f"v{i}", "category": "user"}
             for i in range(12)]
    client = _StubClient(json.dumps(items))
    monkeypatch.setitem(m._pipeline, "llm_lock", None)
    m._memory_review_worker(client, "voice")
    assert len(saved) == m._MEMORY_REVIEW_MAX_FACTS


def test_review_worker_never_raises_on_garbage(monkeypatch):
    _wire_review_stubs(monkeypatch)
    client = _StubClient("the model rambled with no JSON at all")
    monkeypatch.setitem(m._pipeline, "llm_lock", None)
    m._memory_review_worker(client, "voice")  # must not raise


def test_review_worker_steps_aside_when_model_busy(monkeypatch):
    import threading
    saved = _wire_review_stubs(monkeypatch)
    client = _StubClient(json.dumps([{"key": "k", "value": "v"}]))
    busy = threading.Lock()
    busy.acquire()  # simulate an in-flight voice turn
    monkeypatch.setitem(m._pipeline, "llm_lock", busy)
    try:
        m._memory_review_worker(client, "voice")
    finally:
        busy.release()
    assert saved == []          # never queued behind the live turn
    assert not client.calls     # no model call while busy
    # Re-armed to retry after the next turn.
    assert m._pipeline["turns_since_memory_review"] == m._MEMORY_REVIEW_EVERY - 1


def test_spawn_gate_counts_and_skips_background_sessions(monkeypatch):
    fired: list[str] = []
    monkeypatch.setattr(
        m, "_memory_review_worker", lambda client, key: fired.append(key),
    )
    # Threads run the target inline for determinism.
    class _InlineThread:
        def __init__(self, target=None, args=(), **kw):
            self._target, self._args = target, args
        def start(self):
            self._target(*self._args)
    monkeypatch.setattr(m.threading, "Thread", _InlineThread)
    monkeypatch.setitem(m._pipeline, "turns_since_memory_review", 0)

    if m._MEMORY_REVIEW_EVERY <= 0:
        pytest.skip("review disabled via env")
    # Deep-think sessions never trigger a review.
    for _ in range(m._MEMORY_REVIEW_EVERY + 1):
        m._maybe_spawn_memory_review(object(), "deepthink_dt_1")
    assert fired == []

    for _ in range(m._MEMORY_REVIEW_EVERY - 1):
        m._maybe_spawn_memory_review(object(), "voice")
    assert fired == []
    m._maybe_spawn_memory_review(object(), "voice")
    assert fired == ["voice"]
    # Counter reset after firing.
    assert m._pipeline["turns_since_memory_review"] == 0


# ── cross-restart session resume digest ────────────────────────────


def test_resume_digest_renders_recent_pairs(monkeypatch):
    monkeypatch.setattr(m.mem, "recent_qa_pairs", lambda n, session_key=None: [
        {"user": "what's the weather", "answer": "Sunny, 22C in Tokyo."},
        {"user": "remind me at 5pm", "answer": "Scheduled for 5pm."},
    ])
    digest = m._previous_session_digest("voice")
    assert digest.startswith("[PREVIOUS SESSION — REFERENCE ONLY]")
    assert "what's the weather" in digest
    assert "Scheduled for 5pm" in digest
    # The anti-stale-bleed framing is part of the contract.
    assert "Do NOT resume old tasks" in digest


def test_resume_digest_skips_background_and_empty(monkeypatch):
    monkeypatch.setattr(m.mem, "recent_qa_pairs", lambda n, session_key=None: [
        {"user": "q", "answer": "a"},
    ])
    assert m._previous_session_digest("deepthink_dt_1") == ""
    assert m._previous_session_digest("bench_case_x") == ""

    monkeypatch.setattr(m.mem, "recent_qa_pairs", lambda n, session_key=None: [])
    assert m._previous_session_digest("voice") == ""


def test_resume_digest_kill_switch(monkeypatch):
    monkeypatch.setattr(m.mem, "recent_qa_pairs", lambda n, session_key=None: [
        {"user": "q", "answer": "a"},
    ])
    monkeypatch.setenv("JAEGER_SESSION_RESUME", "0")
    assert m._previous_session_digest("voice") == ""


def test_resume_digest_bounded(monkeypatch):
    monkeypatch.setattr(m.mem, "recent_qa_pairs", lambda n, session_key=None: [
        {"user": "q" * 300, "answer": "a" * 300} for _ in range(20)
    ])
    digest = m._previous_session_digest("voice")
    assert len(digest) <= m._SESSION_RESUME_MAX_CHARS + 300  # header + clamp
