"""Asking the model to batch — on the brains where that pays.

The runtime half of parallel dispatch was already built: the loop admits
a batch when every call is a read or a non-conflicting path-scoped file
op, and runs it on a pool. Nothing asked the model to EMIT one, so the
machinery mostly saw a single call at a time.

The guidance is gated rather than always-on because this project has
measured the failure mode: ``agentic_runners.md`` records a planning
gate that took E4B from 73 to 66 and was reverted. Instructions aimed at
a model that improvises well and follows procedure badly are their own
risk, so the sentence follows the brain like everything else here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.models.brain_profile import profile_for
from jaeger_ai.core.runtime.batching import (
    BATCH_GUIDANCE,
    batch_guidance_block,
    guidance_enabled,
)


def _profile(kind="local", provider="", parallel_tools=True):
    client = SimpleNamespace(
        kind=kind, provider=provider, model_name="m", loaded_ctx=8192,
        parallel_tools=parallel_tools,
    )
    return profile_for(client)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JAEGER_BATCH_GUIDANCE", raising=False)
    monkeypatch.delenv("JAEGER_BRAIN_CONCURRENCY", raising=False)


def test_an_in_process_brain_does_not_get_it_by_default():
    """Small local models are where added prompt text has cost points,
    and where parallel dispatch saves the least."""
    assert guidance_enabled(_profile("local")) is False
    assert batch_guidance_block(_profile("local")) == ""


@pytest.mark.parametrize("provider", ["openai", "anthropic", "ollama-cloud"])
def test_a_cloud_brain_gets_it(provider):
    assert guidance_enabled(_profile("external", provider)) is True
    assert batch_guidance_block(_profile("external", provider)) == BATCH_GUIDANCE


def test_a_local_server_brain_gets_it():
    assert guidance_enabled(_profile("external", "ollama")) is True


def test_a_brain_that_cannot_batch_never_gets_it():
    """No point spending tokens asking for something the model does not
    emit — the capability check comes before the cost check."""
    assert guidance_enabled(
        _profile("external", "openai", parallel_tools=False)
    ) is False


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("on", True), ("yes", True),
    ("0", False), ("off", False), ("no", False),
])
def test_the_override_wins_in_both_directions(monkeypatch, raw, expected):
    """``1`` to bench the local case, ``0`` to rule it out while
    bisecting a regression."""
    monkeypatch.setenv("JAEGER_BATCH_GUIDANCE", raw)
    assert guidance_enabled(_profile("local")) is expected
    assert guidance_enabled(_profile("external", "openai")) is expected


def test_the_guidance_says_when_not_to_batch():
    """A blanket 'batch everything' would produce exactly the conflicting
    batches the runtime then has to refuse."""
    assert "depends on another" in BATCH_GUIDANCE
    assert "writing to" in BATCH_GUIDANCE


def test_the_block_is_empty_string_not_none():
    """Callers concatenate without branching, and an absent block must
    change no bytes of an otherwise prefix-cache-stable prompt."""
    assert batch_guidance_block(_profile("local")) == ""


def test_the_session_prompt_carries_it_only_when_it_should(monkeypatch):
    import jaeger_ai.main as main

    monkeypatch.setattr(main, "_runtime_identity_block", lambda: "")
    monkeypatch.setattr(main, "_facts_snapshot_block", lambda: "")

    monkeypatch.setitem(
        main._pipeline, "client",
        SimpleNamespace(kind="local", provider="", model_name="m",
                        loaded_ctx=8192),
    )
    assert "PARALLEL TOOL CALLS" not in main.compose_session_prompt("BASE")

    monkeypatch.setitem(
        main._pipeline, "client",
        SimpleNamespace(kind="external", provider="openai", model_name="gpt",
                        loaded_ctx=128_000),
    )
    assert "PARALLEL TOOL CALLS" in main.compose_session_prompt("BASE")


def test_the_base_prompt_survives_either_way(monkeypatch):
    import jaeger_ai.main as main

    monkeypatch.setattr(main, "_runtime_identity_block", lambda: "")
    monkeypatch.setattr(main, "_facts_snapshot_block", lambda: "")
    monkeypatch.setitem(
        main._pipeline, "client",
        SimpleNamespace(kind="local", provider="", model_name="m",
                        loaded_ctx=8192),
    )
    assert main.compose_session_prompt("BASE").startswith("BASE")
