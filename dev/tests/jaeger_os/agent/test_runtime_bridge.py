"""Phase-6 runtime bridge — adapter selection, drive_one_turn, env gate.

These tests stand between the legacy ``_run_turn`` and the new
``_run_turn_via_jaeger_agent``. They exercise the bridge's selection
logic and turn-driving without booting a real Jaeger instance or
hitting a model — fake clients duck-type the surface the bridge probes.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import (
    AnthropicAdapter,
    JaegerAgent,
    LocalLlamaAdapter,
    OpenAIAdapter,
    ProviderAdapter,
    clear_registry,
    register_tool,
)
from jaeger_os.agent.loop.runtime_bridge import (
    _adapter_for_client,
    build_jaeger_agent,
    drive_one_turn,
    jaeger_agent_enabled,
)


# ── Fake clients for adapter selection ─────────────────────────────


class _FakeLocalClient:
    """Duck-types ``main.LlamaCppPythonClient`` — has ``.llm`` and
    ``.model_name``."""

    def __init__(self) -> None:
        self.llm = SimpleNamespace(create_chat_completion=lambda **_: {})
        self.model_name = "test-local.gguf"


class _FakeExternalClient:
    """Duck-types ``core.external_model.ExternalModelClient`` — carries
    an ``.ext`` config object plus a resolved API key."""

    def __init__(self, provider: str, *, model: str = "test-model") -> None:
        self.ext = SimpleNamespace(
            provider=provider,
            model=model,
            base_url="https://example.test/v1",
            timeout_s=30.0,
        )
        self._api_key = "fake-key"


# ── Adapter selection ──────────────────────────────────────────────


def test_local_client_resolves_to_local_llama_adapter():
    client = _FakeLocalClient()
    adapter = _adapter_for_client(client)
    assert isinstance(adapter, LocalLlamaAdapter)
    # The Llama instance flows through, no second load.
    assert adapter._llama is client.llm
    assert adapter.model == "test-local.gguf"


def test_local_adapter_falls_back_to_default_max_tokens_with_no_pipeline():
    """No active pipeline (early boot / unit-test context with no config)
    must keep the 0.1.0-default 4096 — closing the configurability hole
    can't change unsuspecting callers' behaviour."""
    from jaeger_os.agent.loop.runtime_bridge import _resolve_local_max_tokens
    # Force the lazy import to find no pipeline: clear any cached config.
    import jaeger_os.main as _main
    saved = _main._pipeline.get("config")
    _main._pipeline["config"] = None
    try:
        assert _resolve_local_max_tokens() == 4096
    finally:
        _main._pipeline["config"] = saved


def test_local_adapter_honours_config_max_tokens(monkeypatch):
    """When ``config.model.max_tokens`` is set, the adapter must receive
    it — that's the whole point of plumbing it through. 0.1.0 silently
    ignored it because the bridge always constructed the adapter with
    the hardcoded default."""
    from jaeger_os.agent.loop import runtime_bridge as rb
    import types
    fake_cfg = types.SimpleNamespace(
        model=types.SimpleNamespace(max_tokens=1536))
    monkeypatch.setitem(
        __import__("jaeger_os.main", fromlist=["_pipeline"])._pipeline,
        "config", fake_cfg,
    )
    assert rb._resolve_local_max_tokens() == 1536
    # And the wired adapter actually carries it.
    client = _FakeLocalClient()
    adapter = rb._adapter_for_client(client)
    assert adapter.max_tokens == 1536


def test_local_adapter_max_tokens_resolver_swallows_bad_config():
    """A malformed / missing-attribute config must not crash adapter
    construction — fall back to 4096 silently."""
    from jaeger_os.agent.loop import runtime_bridge as rb
    import jaeger_os.main as _main
    import types
    saved = _main._pipeline.get("config")
    _main._pipeline["config"] = types.SimpleNamespace()  # no .model
    try:
        assert rb._resolve_local_max_tokens() == 4096
    finally:
        _main._pipeline["config"] = saved


def test_anthropic_provider_resolves_to_anthropic_adapter():
    client = _FakeExternalClient(provider="anthropic")
    adapter = _adapter_for_client(client)
    assert isinstance(adapter, AnthropicAdapter)
    assert adapter.api_key == "fake-key"


def test_openai_compat_providers_resolve_to_openai_adapter():
    for provider in ("openai", "gemini", "lmstudio", "ollama", "ollama-cloud"):
        client = _FakeExternalClient(provider=provider)
        adapter = _adapter_for_client(client)
        assert isinstance(adapter, OpenAIAdapter), provider
        assert adapter.provider == provider
        assert adapter.api_key == "fake-key"


def test_unknown_client_shape_raises_with_diagnostic():
    class _Mystery:
        pass

    with pytest.raises(RuntimeError, match="adapter for client"):
        _adapter_for_client(_Mystery())


# ── build_jaeger_agent ─────────────────────────────────────────────


def test_build_jaeger_agent_wires_skip_final_tools():
    client = _FakeLocalClient()
    agent = build_jaeger_agent(
        client,
        system_prompt="be brief",
        skip_final_tools={"get_time", "recall"},
    )
    assert isinstance(agent, JaegerAgent)
    assert agent.skip_final_tools == {"get_time", "recall"}
    assert agent.system_prompt == "be brief"
    # The legacy ceiling — keeps backstop comparable across the A/B.
    assert agent.max_iterations == 24


def test_build_jaeger_agent_picks_120s_stall_for_local_backend():
    """In-process llama-cpp can have legitimately slow cold-prefill
    plus a long decode on a 30B Q4. The default stall watchdog must
    leave headroom (120s) so legitimate work doesn't false-positive
    while still catching the multi-minute Metal hangs."""
    agent = build_jaeger_agent(_FakeLocalClient())
    assert agent.stale_call_timeout_s == 120.0


def test_build_jaeger_agent_honors_explicit_stall_timeout():
    """The caller (main.py reading config) can override the default —
    e.g. a power user who wants to surface stalls in 60s instead of
    120s. Pin the override path."""
    agent = build_jaeger_agent(
        _FakeLocalClient(),
        stale_call_timeout_s=42.0,
    )
    assert agent.stale_call_timeout_s == 42.0


def test_build_jaeger_agent_finalizer_delegates_to_legacy():
    """The skip-final finalizer must route through the legacy
    ``_fast_finalize_sync`` so phrasing is identical to the
    pre-refactor path. We can't easily mock that function — instead we
    confirm the finalizer is callable, returns a string, and handles a
    well-known JROS tool result without raising."""
    class _StubClient:
        llm = SimpleNamespace(create_chat_completion=lambda **_: {})
        model_name = "x"

    agent = build_jaeger_agent(_StubClient(), skip_final_tools={"get_time"})
    # ``get_time`` has a deterministic formatter in ``_fast_finalize_sync``
    # that never reaches the model — perfect for a no-network smoke.
    out = agent.skip_final_finalizer(
        "get_time",
        {"datetime": "2025-01-01 12:00", "tz": "UTC"},
        "what time",
    )
    assert isinstance(out, str)
    assert "2025-01-01 12:00" in out


def test_finalizer_wrapper_swallows_legacy_exceptions():
    """Belt-and-braces: if the legacy formatter raises (a future bug),
    the wrapper must surface a fallback diagnostic rather than crash."""
    class _StubClient:
        llm = SimpleNamespace(create_chat_completion=lambda **_: {})
        model_name = "x"

    agent = build_jaeger_agent(_StubClient(), skip_final_tools={"explode"})
    # Force the legacy formatter to raise by feeding a tool name +
    # shape it doesn't recognise paired with a result that triggers
    # str() failure. Simpler: monkey-patch _fast_finalize_sync to raise.
    import jaeger_os.main as main_mod
    original = main_mod._fast_finalize_sync
    main_mod._fast_finalize_sync = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom"))
    try:
        out = agent.skip_final_finalizer("anything", {"x": 1}, "q")
    finally:
        main_mod._fast_finalize_sync = original
    assert "fallback" in out
    assert "RuntimeError" in out


# ── drive_one_turn ─────────────────────────────────────────────────


class _ScriptedAdapter(ProviderAdapter):
    """Same scripted adapter pattern used by the run_turn tests."""

    name = "scripted"

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = list(script)

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages, "tools": tools}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


class _SmallArgs(BaseModel):
    value: str = Field(default="x")


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def test_drive_one_turn_returns_log_row_compatible_shape():
    @register_tool("get_time", "Time.", _SmallArgs)
    def _impl(value: str = "UTC") -> dict:
        return {"now": "12:00", "tz": value}

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {"value": "UTC"}}]},
        {"role": "assistant", "content": "it's noon UTC"},
    ])
    agent = JaegerAgent(adapter=adapter)
    out = drive_one_turn(agent, "what time is it?")
    # Schema the latency log writer keys off of.
    assert out["answer"] == "it's noon UTC"
    assert out["first_decision"] == {
        "tool": "get_time", "args": {"value": "UTC"},
    }
    assert any("get_time" in line for line in out["tool_activity"])
    assert out["iterations"] == 2
    assert out["halt_reason"] is None
    assert out["skipped"] is False
    assert out["elapsed_s"] >= 0.0


def test_drive_one_turn_records_skip_final_path():
    @register_tool("get_time", "Time.", _SmallArgs)
    def _impl(value: str = "UTC") -> dict:
        return {"now": "12:00"}

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {}}]},
    ])
    agent = JaegerAgent(
        adapter=adapter,
        skip_final_tools={"get_time"},
        skip_final_finalizer=lambda n, r, u: "it's noon",
    )
    out = drive_one_turn(agent, "time?")
    assert out["skipped"] is True
    assert out["answer"] == "it's noon"
    assert out["first_decision"] == {"tool": "get_time", "args": {}}


def test_drive_one_turn_surfaces_halt_reason_when_loop_caps():
    """Loop backstop fired → ``halt_reason`` populated → caller can
    write it into the log row."""
    @register_tool("loopy", "Always called.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    from jaeger_os.agent.loop.loop_backstop import MAX_IDENTICAL_CALLS
    script: list[dict[str, Any]] = []
    for _ in range(MAX_IDENTICAL_CALLS + 2):
        script.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "x", "name": "loopy",
                            "arguments": {"value": "a"}}],
        })
    agent = JaegerAgent(adapter=_ScriptedAdapter(script))
    out = drive_one_turn(agent, "loop")
    assert out["halt_reason"] is not None
    assert "loopy" in out["halt_reason"]


def test_drive_one_turn_accumulates_history_across_turns():
    """Multi-turn: the same ``JaegerAgent`` instance keeps growing its
    message list — that's the per-session state the bench's L3 relies
    on for resume."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
    ])
    agent = JaegerAgent(adapter=adapter)
    drive_one_turn(agent, "first")
    drive_one_turn(agent, "second")
    # user, assistant, user, assistant
    assert [m["role"] for m in agent.messages] == [
        "user", "assistant", "user", "assistant",
    ]


# ── env gate ───────────────────────────────────────────────────────


def test_jaeger_agent_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("JAEGER_USE_NEW_AGENT", raising=False)
    assert jaeger_agent_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", " on "])
def test_jaeger_agent_enabled_honours_truthy_values(monkeypatch, val):
    monkeypatch.setenv("JAEGER_USE_NEW_AGENT", val)
    assert jaeger_agent_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "maybe"])
def test_jaeger_agent_enabled_rejects_falsy_or_garbage(monkeypatch, val):
    monkeypatch.setenv("JAEGER_USE_NEW_AGENT", val)
    assert jaeger_agent_enabled() is False
