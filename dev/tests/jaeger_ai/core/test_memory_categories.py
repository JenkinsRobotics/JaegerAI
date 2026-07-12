"""Categorised memory — remember(category=…) and grouped list_facts.

Memory stays organised: a fact can carry a category ('contacts',
'preferences', …); list_facts_by_category groups them; the flat
list_facts contract is unchanged so existing callers keep working; and
a facts.json written before categories existed still reads cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.memory import memory as mem


@pytest.fixture()
def bound(tmp_path: Path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


def test_uncategorised_fact_lands_in_general(bound) -> None:
    mem.remember("sky_color", "blue")
    assert mem.list_facts_by_category() == {"general": {"sky_color": "blue"}}


def test_category_groups_facts(bound) -> None:
    mem.remember("sara_phone", "555-0142", category="contacts")
    mem.remember("fav_color", "teal", category="preferences")
    mem.remember("misc_thing", "whatever")
    grouped = mem.list_facts_by_category()
    assert grouped["contacts"] == {"sara_phone": "555-0142"}
    assert grouped["preferences"] == {"fav_color": "teal"}
    assert grouped["general"] == {"misc_thing": "whatever"}


def test_list_facts_stays_flat_for_back_compat(bound) -> None:
    # Existing callers expect a flat {key: value} map — must not change.
    mem.remember("a", "1", category="contacts")
    mem.remember("b", "2")
    assert mem.list_facts() == {"a": "1", "b": "2"}


def test_recall_works_regardless_of_category(bound) -> None:
    mem.remember("sara_phone", "555-0142", category="contacts")
    assert mem.recall("sara_phone") == "555-0142"


def test_forget_drops_the_category_entry_too(bound) -> None:
    """DB-2 (0.2.0): facts and their category live in one SQL row, so
    DELETE removes both at once — no separate category map to clean
    up. Previously two JSON sections had to stay consistent."""
    mem.remember("sara_phone", "555-0142", category="contacts")
    assert mem.forget("sara_phone") is True
    assert mem.list_facts_by_category() == {}


def test_general_category_sorts_last(bound) -> None:
    mem.remember("z_fact", "1")                       # general
    mem.remember("a_fact", "2", category="contacts")
    assert list(mem.list_facts_by_category())[-1] == "general"


def test_legacy_flat_facts_file_reads_as_general(tmp_path) -> None:
    """0.1.x → 0.2.0 upgrade: a plain ``{k: v}`` facts.json written
    BEFORE the SQLite store ever opens gets lazy-imported into the
    'general' category. Pin the bind-time migration path."""
    from types import SimpleNamespace
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "facts.json").write_text(
        json.dumps({"old_key": "old_val"}), encoding="utf-8",
    )
    # Now bind — the lazy-import in ``memory.bind`` pulls the JSON
    # rows into SQL.
    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    assert mem.list_facts_by_category() == {"general": {"old_key": "old_val"}}
