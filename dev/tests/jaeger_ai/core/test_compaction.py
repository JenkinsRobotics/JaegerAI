"""Compaction digests — who writes them, and what actually reaches the transcript.

Two failures pinned here.

**The repr bug.** ``client.chat()`` returns a result OBJECT on every
lane, never a bare string. The wiring called ``str(out or "")`` on it,
so the digest that reached the conversation read
``ExtChatResult(text='…', latency_s=0.4, ttft_s=0.0)`` — the summary
present but wrapped in Python syntax, spending the digest's character
cap on a dataclass repr.

**The local-cost-as-universal-rule bug.** The LLM digest was gated on
``key.startswith("deepthink")``. The reasoning — a compaction call costs
seconds and blocks the turn — is an in-process model's cost, not a
cloud endpoint's. Same shape as the subagent cap that read as physics
and was really one brain's property.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.models.brain_profile import profile_for
from jaeger_ai.core.runtime.compaction import (
    _result_text,
    is_background_session,
    llm_digest_enabled,
    make_summarizer,
    summarizer_for,
)


def _profile(kind="local", provider=""):
    return profile_for(
        SimpleNamespace(kind=kind, provider=provider, model_name="m", loaded_ctx=8192)
    )


LOCAL = "local"
CLOUD = "cloud"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JAEGER_LLM_DIGEST", raising=False)
    monkeypatch.delenv("JAEGER_BRAIN_CONCURRENCY", raising=False)


# ── the text that actually lands in the transcript ──────────────────


def test_the_digest_is_the_text_not_the_repr():
    """The bug: a dataclass reached the transcript as its repr."""
    from jaeger_ai.core.models.external_model import ExtChatResult

    result = ExtChatResult(text="user asked for X; we did Y", latency_s=0.4)
    assert _result_text(result) == "user asked for X; we did Y"
    assert "ExtChatResult" not in _result_text(result)
    assert "latency_s" not in _result_text(result)


def test_every_client_result_shape_yields_its_text():
    """Local and external lanes return different result classes; both
    carry ``.text``, and a future client returning a bare string works
    without another change here."""
    assert _result_text(SimpleNamespace(text=" trimmed ")) == "trimmed"
    assert _result_text("a plain string") == "a plain string"
    assert _result_text(None) == ""
    assert _result_text(SimpleNamespace(no_text_here=1)) == ""


def test_summarizer_returns_clean_text():
    client = SimpleNamespace(
        chat=lambda messages, **kw: SimpleNamespace(text="  the digest  ")
    )
    assert make_summarizer(client)("compress this") == "the digest"


def test_summarizer_asks_for_a_bounded_call():
    """A digest that grows toward the span it replaced has failed."""
    seen = {}

    def _chat(messages, **kw):
        seen.update(kw)
        seen["messages"] = messages
        return SimpleNamespace(text="ok")

    make_summarizer(SimpleNamespace(chat=_chat))("span")
    assert seen["max_tokens"] <= 400
    assert seen["messages"][0]["role"] == "system"
    assert seen["messages"][1]["content"] == "span"


def test_a_failing_summarizer_never_breaks_the_turn():
    """The guard falls back to the deterministic digest — compaction
    must not take the turn down with it."""
    def _boom(messages, **kw):
        raise RuntimeError("endpoint down")

    assert make_summarizer(SimpleNamespace(chat=_boom))("span") == ""


# ── who can afford the call ─────────────────────────────────────────


@pytest.mark.parametrize("key", [
    "deepthink:task-1", "daemon", "cron:nightly", "review:skills",
])
def test_background_sessions_always_get_the_llm_digest(key):
    """Nobody is waiting — the better digest is free on any brain."""
    assert is_background_session(key) is True
    assert llm_digest_enabled(_profile(LOCAL), key) is True


def test_interactive_on_an_in_process_model_stays_deterministic():
    """Seconds of latency AND the only decode lane held — the one cost
    the voice path cannot absorb."""
    assert llm_digest_enabled(_profile(LOCAL), "tui:main") is False


@pytest.mark.parametrize("provider", ["ollama-cloud", "openai", "anthropic"])
def test_interactive_on_a_cloud_brain_gets_the_llm_digest(provider):
    """The latency argument was the local brain's. A cloud call overlaps
    other work and costs a round-trip."""
    assert llm_digest_enabled(_profile("external", provider), "tui:main") is True


def test_a_local_server_brain_also_qualifies():
    assert llm_digest_enabled(_profile("external", "ollama"), "tui:main") is True


def test_the_gate_follows_the_brain_not_the_session_name():
    """The regression guard: switching brains must switch the answer for
    the SAME session key."""
    key = "tui:main"
    assert llm_digest_enabled(_profile(LOCAL), key) is False
    assert llm_digest_enabled(_profile("external", "openai"), key) is True


# ── the override ────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["0", "false", "off", "NO"])
def test_env_can_force_the_deterministic_digest(monkeypatch, raw):
    monkeypatch.setenv("JAEGER_LLM_DIGEST", raw)
    assert llm_digest_enabled(_profile("external", "openai"), "deepthink:1") is False


@pytest.mark.parametrize("raw", ["1", "true", "ON", "yes"])
def test_env_can_force_the_llm_digest(monkeypatch, raw):
    monkeypatch.setenv("JAEGER_LLM_DIGEST", raw)
    assert llm_digest_enabled(_profile(LOCAL), "tui:main") is True


# ── what the agent builder receives ─────────────────────────────────


def test_summarizer_for_returns_none_when_the_lane_cant_pay():
    """``None`` is the guard's default and a valid answer — the
    deterministic digest, not a degraded one."""
    client = SimpleNamespace(
        kind="local", provider="", model_name="m", loaded_ctx=8192,
        chat=lambda messages, **kw: SimpleNamespace(text="x"),
    )
    assert summarizer_for(client, "tui:main") is None


def test_summarizer_for_returns_a_working_callable_when_it_can():
    client = SimpleNamespace(
        kind="external", provider="ollama-cloud", model_name="qwen",
        loaded_ctx=262_144,
        chat=lambda messages, **kw: SimpleNamespace(text="digest body"),
    )
    summarize = summarizer_for(client, "tui:main")
    assert callable(summarize)
    assert summarize("span") == "digest body"


def test_summarizer_for_handles_no_client():
    assert summarizer_for(None, "deepthink:1") is None


# ── end to end through the guard ────────────────────────────────────


def test_guard_uses_the_llm_digest_and_keeps_it_clean():
    """The whole point: a wired summarizer replaces the deterministic
    digest, and what lands in ``messages`` is prose."""
    from jaeger_agent.util.context_guard import ContextBudget, ContextGuard

    client = SimpleNamespace(
        chat=lambda messages, **kw: SimpleNamespace(
            text="User wanted the notes distilled; 12 files read; 3 actions found.",
            latency_s=0.3,
        )
    )
    guard = ContextGuard(
        ContextBudget(ctx_window=2000), summarizer=make_summarizer(client),
    )
    history = [
        {"role": "user", "content": f"question {i} " + ("padding " * 60)}
        for i in range(12)
    ]
    history.append({"role": "user", "content": "the latest ask"})

    result = guard.trim_to_fit(history, system_prompt="sys", tools=[])

    assert result.dropped_count > 0
    assert result.digested is True
    head = str(result.messages[0].get("content") or "")
    assert "12 files read" in head
    assert "ChatResult" not in head and "latency_s" not in head


def test_guard_falls_back_when_the_summarizer_fails():
    """A summarizer hiccup costs digest quality, never the turn."""
    from jaeger_agent.util.context_guard import ContextBudget, ContextGuard

    def _boom(messages, **kw):
        raise RuntimeError("down")

    guard = ContextGuard(
        ContextBudget(ctx_window=2000),
        summarizer=make_summarizer(SimpleNamespace(chat=_boom)),
    )
    history = [
        {"role": "user", "content": f"question {i} " + ("padding " * 60)}
        for i in range(12)
    ]
    history.append({"role": "user", "content": "the latest ask"})

    result = guard.trim_to_fit(history, system_prompt="sys", tools=[])
    assert result.digested is True
    assert result.messages[-1]["content"] == "the latest ask"
