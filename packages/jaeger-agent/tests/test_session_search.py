"""The agent reviewing its own past conversations.

``episodic`` has stored one row per turn, keyed by ``session_key``, since
the store was written — but the only way to read it back was "the last N
turns of the CURRENT session". Recalling what happened in a conversation
you are no longer in is a memory operation, and it was the one missing.

The ``sessions`` toolset named ``session_search`` and shipped in both
default bundles while no such tool existed anywhere. These tests exist so
that cannot recur silently.
"""

from __future__ import annotations

import tempfile
import types
from pathlib import Path

import pytest

from jaeger_agent.memory import memory as mem


@pytest.fixture()
def history():
    """A bound instance with three turns across two conversations."""
    root = Path(tempfile.mkdtemp())
    mem.bind(types.SimpleNamespace(
        memory_dir=root / "memory", root=root, logs_dir=root / "logs",
    ))
    turns = [
        ("tui", "how do I deploy the agent?", "Use the 1.0.3 branch."),
        ("tui", "what about the context guard?", "Four stages, then refuse."),
        ("voice", "remind me about the deploy", "You asked about deploying earlier."),
    ]
    for i, (session, user, answer) in enumerate(turns):
        mem.append_episodic({
            "session_key": session, "user": user, "answer": answer,
            "decision_raw": answer, "latency_ms": 100 + i,
            "first_decision": "answer",
        })
    return root


def test_search_spans_sessions(history) -> None:
    """The whole point: a hit from a conversation you are not in."""
    hits = mem.search_sessions("deploy")
    assert {h["session"] for h in hits} == {"tui", "voice"}
    assert all("deploy" in (h["user"] + h["answer"]).lower() for h in hits)


def test_search_matches_the_answer_not_just_the_prompt(history) -> None:
    """"What did it tell me about X" is as common as "what did I ask"."""
    hits = mem.search_sessions("Four stages")
    assert len(hits) == 1
    assert hits[0]["user"].startswith("what about the context guard")


def test_search_is_newest_first(history) -> None:
    """Reviewing history, the recent past is the interesting part."""
    hits = mem.search_sessions("")
    assert [h["session"] for h in hits] == ["voice", "tui", "tui"]


def test_session_filter_narrows(history) -> None:
    hits = mem.search_sessions("deploy", session_key="voice")
    assert len(hits) == 1 and hits[0]["session"] == "voice"


def test_empty_query_browses_instead_of_matching_nothing(history) -> None:
    """"What was I doing yesterday" has no search term."""
    assert len(mem.search_sessions("")) == 3


def test_limit_is_clamped(history) -> None:
    """A model that asks for a million rows gets a sane page, and 0 means
    "unspecified" rather than "none" — a tool that returns nothing when
    the model passes 0 looks broken to it."""
    assert len(mem.search_sessions("", limit=10_000)) == 3   # capped at 100
    assert len(mem.search_sessions("", limit=1)) == 1
    assert len(mem.search_sessions("", limit=0)) == 3        # falls back to 10


def test_list_sessions_summarises_conversations(history) -> None:
    rows = {s["session"]: s for s in mem.list_sessions()}
    assert rows["tui"]["turns"] == 2
    assert rows["voice"]["turns"] == 1
    assert rows["tui"]["first_ts"] and rows["tui"]["last_ts"]


def test_the_tool_is_registered_and_matches_the_toolset(history, live_tools) -> None:
    """The gap that started this: ``sessions`` advertised a tool that did
    not exist, in both default bundles."""
    from jaeger_agent.schemas.tool_bundles import JAEGER_TOOLSETS

    live = set(live_tools)
    assert "session_search" in live
    assert set(JAEGER_TOOLSETS["sessions"]["tools"]) <= live


def test_the_tool_lists_when_given_nothing(history, live_tools) -> None:
    fn = live_tools["session_search"].fn
    out = fn()
    assert out["ok"] and out["count"] == 2          # two conversations
    out = fn(query="context guard")
    assert out["ok"] and out["turns"][0]["answer"] == "Four stages, then refuse."


def test_the_tool_reports_failure_rather_than_raising(monkeypatch, live_tools) -> None:
    """A broken lookup must come back as {"ok": False}, not an exception.
    A tool that raises takes the turn with it; one that reports lets the
    model say so and carry on."""

    def _boom(*a, **k):
        raise RuntimeError("no instance bound")

    monkeypatch.setattr(mem, "search_sessions", _boom)
    fn = live_tools["session_search"].fn
    out = fn(query="anything")
    assert out["ok"] is False
    assert "no instance bound" in out["error"]
