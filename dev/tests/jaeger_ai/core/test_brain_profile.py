"""The brain declares its limits; the framework stops assuming them.

The leak this closes: subagent fan-out was capped at the constant 2,
justified by llama-cpp serializing decode. True of an in-process model,
false of every server brain — so swapping to a cloud endpoint kept the
local model's ceiling, and seven eighths of the available concurrency
went unused because a comment about llama.cpp had been written down as
a number.

Pinned here: the profile reads the LIVE client, the defaults track what
the brain IS rather than where it runs, the operator override always
wins, and the delegation site consumes the profile instead of a
constant.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import jaeger_ai.main as main
from jaeger_ai.core.models.brain_profile import (
    MAX_CONCURRENCY,
    BrainProfile,
    active_profile,
    profile_for,
)


def _client(kind="local", provider="", model="m", ctx=8192):
    return SimpleNamespace(
        kind=kind, provider=provider, model_name=model, loaded_ctx=ctx,
    )


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv("JAEGER_BRAIN_CONCURRENCY", raising=False)


# ── defaults track what the brain IS ────────────────────────────────


def test_in_process_model_runs_one_at_a_time():
    """llama.cpp / MLX decode serializes — a second caller only queues."""
    profile = profile_for(_client(kind="local", provider="in-process"))
    assert profile.concurrency == 1
    assert profile.serializes_decode is True
    assert profile.location == "local"


@pytest.mark.parametrize("provider", ["lmstudio", "ollama"])
def test_a_local_server_takes_more_than_one(provider):
    """A server owns a scheduler even when it runs on this machine —
    'local' is about where the weights live, not who schedules."""
    profile = profile_for(_client(kind="external", provider=provider))
    assert profile.concurrency > 1
    assert profile.serializes_decode is False
    assert profile.location == "remote"


@pytest.mark.parametrize("provider", [
    "ollama-cloud", "openai", "anthropic", "gemini", "xai",
])
def test_cloud_brains_fan_out_widest(provider):
    profile = profile_for(_client(kind="external", provider=provider))
    assert profile.concurrency >= 8
    assert profile.location == "cloud"


def test_cloud_beats_local_server_beats_in_process():
    """The ordering is the whole point — assert the relationship, not
    three magic numbers that a tuning pass would have to chase here."""
    in_process = profile_for(_client(kind="local")).concurrency
    server = profile_for(_client(kind="external", provider="ollama")).concurrency
    cloud = profile_for(_client(kind="external", provider="openai")).concurrency
    assert in_process < server < cloud


def test_unknown_external_provider_is_treated_conservatively():
    """Something is on the other end of a wire, but we know nothing
    about it — take the smaller server number, never the cloud one."""
    profile = profile_for(_client(kind="external", provider="some-new-thing"))
    server = profile_for(_client(kind="external", provider="ollama"))
    assert profile.concurrency == server.concurrency


# ── failing safe ────────────────────────────────────────────────────


def test_no_client_yields_the_conservative_profile():
    """Pre-boot, or a client we can't read: under-parallelise rather
    than stampede a backend that cannot take it."""
    profile = profile_for(None)
    assert profile.concurrency == 1
    assert profile == BrainProfile()


def test_a_client_missing_every_attribute_still_profiles():
    profile = profile_for(object())
    assert profile.concurrency == 1
    assert profile.kind == "local"


def test_context_window_is_carried_and_garbage_is_dropped():
    assert profile_for(_client(ctx=262_144)).context_window == 262_144
    assert profile_for(_client(ctx=None)).context_window == 0
    assert profile_for(_client(ctx="wat")).context_window == 0
    assert profile_for(_client(ctx=-5)).context_window == 0


# ── the operator override wins ──────────────────────────────────────


def test_env_override_beats_the_family_default(monkeypatch):
    """A family default is a guess about a class of brain; an operator
    who measured their own always outranks it."""
    monkeypatch.setenv("JAEGER_BRAIN_CONCURRENCY", "4")
    assert profile_for(_client(kind="local")).concurrency == 4
    assert profile_for(_client(kind="external", provider="openai")).concurrency == 4


def test_env_override_is_clamped_not_trusted(monkeypatch):
    monkeypatch.setenv("JAEGER_BRAIN_CONCURRENCY", "9999")
    assert profile_for(_client()).concurrency == MAX_CONCURRENCY


@pytest.mark.parametrize("raw", ["0", "-3", "lots", ""])
def test_unusable_override_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("JAEGER_BRAIN_CONCURRENCY", raw)
    assert profile_for(_client(kind="external", provider="openai")).concurrency >= 8


# ── the live client, not the config ─────────────────────────────────


def test_active_profile_reads_the_serving_client(monkeypatch):
    """Config states an intent; the client is the outcome. Fanning out
    eight subagents against a lane that is actually one local model is
    exactly what reading the config would cause."""
    monkeypatch.setitem(
        main._pipeline, "client",
        _client(kind="external", provider="anthropic", model="claude-x"),
    )
    profile = active_profile()
    assert profile.provider == "anthropic"
    assert profile.concurrency >= 8

    monkeypatch.setitem(main._pipeline, "client", _client(kind="local"))
    assert active_profile().concurrency == 1


# ── the consumer ────────────────────────────────────────────────────


def test_delegation_width_follows_the_brain(monkeypatch):
    monkeypatch.setitem(main._pipeline, "client", _client(kind="local"))
    assert main._max_parallel_subagents() == 1

    monkeypatch.setitem(
        main._pipeline, "client",
        _client(kind="external", provider="ollama-cloud"),
    )
    assert main._max_parallel_subagents() >= 8


def test_delegation_never_widens_past_the_work(monkeypatch):
    """Three subtasks on an eight-wide brain start three workers, not
    eight idle ones."""
    monkeypatch.setitem(
        main._pipeline, "client",
        _client(kind="external", provider="openai"),
    )
    monkeypatch.setattr(
        main, "_delegate_internal",
        lambda client, task: {"delegated": True, "task": task, "answer": "ok"},
    )
    result = main._delegate_parallel(_client(), ["a", "b", "c"])
    assert result["ok"] is True
    assert result["max_concurrent"] == 3
    assert result["subtask_count"] == 3
    assert result["succeeded"] == 3


def test_delegation_reports_the_width_it_used(monkeypatch):
    """``max_concurrent`` is read by the model in the tool result — it
    has to be what actually happened, not the ceiling."""
    monkeypatch.setitem(main._pipeline, "client", _client(kind="local"))
    monkeypatch.setattr(
        main, "_delegate_internal",
        lambda client, task: {"delegated": True, "task": task},
    )
    result = main._delegate_parallel(_client(), ["a", "b", "c", "d"])
    assert result["max_concurrent"] == 1


def test_describe_names_the_lane_and_the_width():
    profile = profile_for(
        _client(kind="external", provider="ollama-cloud",
                model="qwen3.5:397b", ctx=262_144)
    )
    text = profile.describe()
    assert "ollama-cloud" in text and "qwen3.5:397b" in text
    assert "262,144" in text and "concurrent" in text
