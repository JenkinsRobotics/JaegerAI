"""Which context window the guard budgets against.

``model.ctx`` sizes the LOCAL worker lane (llama.cpp / MLX KV). Reading
it while a CLOUD model answers is how a 131K-context model got budgeted
against the local default of 8192 and refused turns that would have fit
— the failure ARES surfaced as "I had to stop mid-task: the
conversation plus tool results no longer fit the model's context
window" on its very first turn.

These pin the resolution rules:

  - external lane wins when it is enabled and carries its own ctx;
  - either side fills in for the other when one is unset;
  - the completion reserve tracks the same lane's ``max_tokens``, and
    can never claim more than half the window.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_ai.main import _context_budget_for


def _cfg(*, model=None, external=None):
    """A config stand-in — the real one is a pydantic model, but the
    resolver only ever does attribute reads."""
    return SimpleNamespace(model=model, external_model=external)


def test_local_lane_is_used_when_no_external_model():
    cfg = _cfg(model=SimpleNamespace(ctx=8192, max_tokens=1024))
    assert _context_budget_for(cfg) == (8192, 1024)


def test_external_lane_wins_when_enabled():
    """The regression: both lanes present, cloud model serving. The
    cloud window is the one that matters."""
    cfg = _cfg(
        model=SimpleNamespace(ctx=8192, max_tokens=1024),
        external=SimpleNamespace(enabled=True, ctx=131_072, max_tokens=4096),
    )
    assert _context_budget_for(cfg) == (131_072, 4096)


def test_disabled_external_lane_is_ignored():
    cfg = _cfg(
        model=SimpleNamespace(ctx=8192, max_tokens=1024),
        external=SimpleNamespace(enabled=False, ctx=131_072, max_tokens=4096),
    )
    assert _context_budget_for(cfg) == (8192, 1024)


def test_external_lane_without_ctx_falls_back_to_the_local_number():
    """An external_model block written before ``ctx`` existed (or by a
    sync that couldn't resolve the window) must not zero the budget."""
    cfg = _cfg(
        model=SimpleNamespace(ctx=32_768, max_tokens=2048),
        external=SimpleNamespace(enabled=True, ctx=0, max_tokens=0),
    )
    assert _context_budget_for(cfg) == (32_768, 2048)


def test_missing_config_yields_no_opinion():
    """``(None, None)`` leaves ``build_jaeger_agent`` to its own
    defaults rather than installing a guard budgeted against nothing."""
    assert _context_budget_for(_cfg()) == (None, None)
    assert _context_budget_for(None) == (None, None)


def test_garbage_values_do_not_crash_the_boot():
    cfg = _cfg(model=SimpleNamespace(ctx="not-a-number", max_tokens=None))
    assert _context_budget_for(cfg) == (None, None)


def test_ollama_cloud_does_not_inherit_a_large_local_ctx(monkeypatch):
    """A leftover local 32K must not become the cloud budget when the
    model name is a known 128K family. Probe is stubbed offline."""
    from jaeger_ai.core.models import ollama_context as oc
    import jaeger_ai.main as main

    monkeypatch.setattr(oc, "query_ollama_show", lambda *a, **k: None)
    saved = main._pipeline.get("client")
    main._pipeline["client"] = None
    try:
        cfg = _cfg(
            model=SimpleNamespace(ctx=32_768, max_tokens=1024),
            external=SimpleNamespace(
                enabled=True, provider="ollama-cloud", ctx=0, max_tokens=4096,
                model="qwen3.5:397b", base_url="https://ollama.com/v1",
            ),
        )
        assert _context_budget_for(cfg) == (131_072, 4096)
    finally:
        main._pipeline["client"] = saved


def test_local_loaded_ctx_wins_over_wizard_model_ctx(monkeypatch):
    """The process's n_ctx is the hard ceiling; the wizard value can
    drift after a /switch-model without a config rewrite."""
    import jaeger_ai.main as main

    saved = main._pipeline.get("client")
    main._pipeline["client"] = SimpleNamespace(kind="local", loaded_ctx=32_768)
    try:
        cfg = _cfg(model=SimpleNamespace(ctx=8192, max_tokens=1024))
        assert _context_budget_for(cfg) == (32_768, 1024)
    finally:
        main._pipeline["client"] = saved
