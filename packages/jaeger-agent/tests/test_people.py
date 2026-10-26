"""The person index, on the agent's own memory.

Knowing who someone is, is recall — the same argument that put
``session_search`` in memory. The facts table has always modelled
``(subject, key, value, category)``, and a person is a subject with
facts, so this needed no new table and no migration.

Until 1.0.5 these three tools read ``jaeger_ai.core.people``, so an
embedder that was not JaegerAI had a ``remember_person`` tool that always
answered "no instance bound".
"""

from __future__ import annotations

import tempfile
import types
from pathlib import Path

import pytest

from jaeger_agent.memory import memory as mem


@pytest.fixture()
def bound():
    root = Path(tempfile.mkdtemp())
    mem.bind(types.SimpleNamespace(
        memory_dir=root / "memory", root=root, logs_dir=root / "logs",
    ))
    return root


def test_upsert_creates_then_updates(bound) -> None:
    mem.upsert_person("Ada", note="wrote the first program")
    mem.upsert_person("Ada", note="likes engines", access="admin")
    ada = mem.get_person("Ada")
    assert ada["name"] == "Ada"
    assert ada["access"] == "admin"
    assert ada["notes"] == ["wrote the first program", "likes engines"]


def test_notes_and_likes_append_but_access_replaces(bound) -> None:
    """Appending is right for observations and wrong for trust level: two
    notes are two facts, two access levels are a contradiction."""
    mem.upsert_person("Bob", note="a", like="x", access="member")
    mem.upsert_person("Bob", note="b", like="y", access="blocked")
    bob = mem.get_person("Bob")
    assert bob["notes"] == ["a", "b"]
    assert bob["likes"] == ["x", "y"]
    assert bob["access"] == "blocked"


def test_a_handle_finds_the_person_who_owns_it(bound) -> None:
    """The messaging case: a chat id arrives, and the agent needs to know
    whose it is before deciding what it may do for them."""
    mem.upsert_person("Cleo", channel="telegram", handle="8777030623")
    assert mem.get_person("8777030623")["name"] == "Cleo"


def test_handles_do_not_duplicate(bound) -> None:
    mem.upsert_person("Dev", channel="telegram", handle="1")
    mem.upsert_person("Dev", channel="telegram", handle="1")
    assert mem.get_person("Dev")["handles"]["telegram"] == ["1"]


def test_unknown_person_is_none_not_an_error(bound) -> None:
    assert mem.get_person("Nobody") is None
    assert mem.get_person("") is None


def test_a_person_needs_a_name(bound) -> None:
    with pytest.raises(ValueError):
        mem.upsert_person("   ")


def test_list_and_forget(bound) -> None:
    mem.upsert_person("Eve")
    mem.upsert_person("Frank")
    assert {p["name"] for p in mem.list_people()} == {"Eve", "Frank"}
    assert mem.forget_person("Eve") is True
    assert {p["name"] for p in mem.list_people()} == {"Frank"}


def test_the_tools_use_the_agents_store(bound, live_tools) -> None:
    """The coupling removal, asserted: these answer from the agent's own
    memory, with no host present."""
    tools = {name: t.fn for name, t in live_tools.items()}
    assert tools["remember_person"](name="Grace", note="compiler")["ok"]
    assert tools["get_person"](name="Grace")["found"]
    assert any(p["name"] == "Grace" for p in tools["list_people"]()["people"])


def test_tools_degrade_rather_than_raise(monkeypatch, bound, live_tools) -> None:
    """A memory failure must not take the turn with it."""

    def _boom(*a, **k):
        raise RuntimeError("db gone")

    tools = {name: t.fn for name, t in live_tools.items()}
    monkeypatch.setattr(mem, "list_people", _boom)
    assert tools["list_people"]() == {"people": []}
    monkeypatch.setattr(mem, "get_person", _boom)
    assert tools["get_person"](name="Grace")["found"] is False
    monkeypatch.setattr(mem, "upsert_person", _boom)
    assert tools["remember_person"](name="Grace")["ok"] is False
