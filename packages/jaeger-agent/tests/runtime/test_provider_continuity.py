"""A run checkpointed under one provider resumes under another.

This is the success criterion "replace Claude with Gemini → a
configuration change" expressed as a test. It holds because a
checkpoint stores task progress and nothing else: no conversation
handle, no provider cursor, no SDK object. If someone later puts
provider state in a checkpoint, this file is where it surfaces.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def store(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteRunStore()
    finally:
        sqlite_store.close()


def test_run_resumes_on_a_different_provider(store):
    commitment = SqliteCommitmentStore().create("summarise the archive")
    run = store.create(commitment.id, provider="claude")
    store.transition(run.id, "active")
    store.checkpoint(run.id, {"processed": 42})
    store.transition(run.id, "failed", reason="provider outage")

    resumed, checkpoint = store.resume(run.id, provider="gemini")

    assert resumed.state == "active"
    assert resumed.provider == "gemini"
    assert checkpoint.cursor == {"processed": 42}


def test_resume_without_a_provider_keeps_the_old_one(store):
    commitment = SqliteCommitmentStore().create("summarise")
    run = store.create(commitment.id, provider="claude")
    store.transition(run.id, "active")
    store.transition(run.id, "paused")

    resumed, _ = store.resume(run.id)

    assert resumed.provider == "claude"


def test_provider_swap_does_not_reset_progress(store):
    """Three providers, one continuous piece of work."""
    commitment = SqliteCommitmentStore().create("long haul")
    run = store.create(commitment.id, provider="claude")
    store.transition(run.id, "active")

    for provider, processed in (("claude", 10), ("gemini", 20), ("ollama", 30)):
        store.checkpoint(run.id, {"processed": processed})
        store.transition(run.id, "paused")
        resumed, checkpoint = store.resume(run.id, provider=provider)
        assert checkpoint.cursor["processed"] == processed
        assert resumed.provider == provider

    assert store.latest_checkpoint(run.id).seq == 3


def test_checkpoints_carry_no_provider_identity(store):
    """The stored cursor must be provider-agnostic JSON, not SDK state."""
    commitment = SqliteCommitmentStore().create("summarise")
    run = store.create(commitment.id, provider="claude")
    store.checkpoint(run.id, {"processed": 42, "stage": "extract"})

    raw = sqlite_store.connection().execute(
        "SELECT cursor_json FROM checkpoints WHERE run_id = ?", (run.id,)
    ).fetchone()["cursor_json"]

    assert json.loads(raw) == {"processed": 42, "stage": "extract"}
    for leaked in ("claude", "anthropic", "gemini", "openai", "api_key"):
        assert leaked not in raw.lower()


def test_the_runtime_layer_imports_no_provider_sdk():
    """Architecture fitness: durable cognition stays provider-free.

    The cognitive core may not depend on a vendor SDK — adapters may.
    """
    import jaeger_agent.cognition as cognition
    from pathlib import Path

    banned = ("anthropic", "openai", "google.generativeai", "mlx", "ollama")
    for path in Path(cognition.__file__).parent.glob("*.py"):
        source = path.read_text()
        for name in banned:
            assert f"import {name}" not in source, f"{path.name} imports {name}"
            assert f"from {name}" not in source, f"{path.name} imports {name}"


def test_in_memory_store_has_the_same_continuity_behaviour():
    store = InMemoryRunStore()
    run = store.create("c-1", provider="claude")
    store.transition(run.id, "active")
    store.checkpoint(run.id, {"processed": 42})
    store.transition(run.id, "failed")

    resumed, checkpoint = store.resume(run.id, provider="gemini")

    assert resumed.provider == "gemini"
    assert checkpoint.cursor == {"processed": 42}
