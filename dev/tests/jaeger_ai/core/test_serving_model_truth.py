"""What the agent believes it is running on must be what is running.

Two observed failures motivate this file, both from the same root cause —
self-description assembled from the model registry and training-data
folklore instead of from the live client:

  1. Asked for its context limit while served by a 262144-token Ollama
     Cloud lane, the agent answered "Qwen3.5 typically supports 32K-128K
     tokens".
  2. Asked which model had the largest window, it listed four
     downloadable local GGUFs, reported one as "currently loaded", and
     offered to download a 30B — while a 1M-window cloud model was
     answering the question.

The invariants pinned here:

  - ``serving_model()`` reads the live client, never the config's intent;
  - a configured cloud lane that is NOT what is answering is reported as
    a fallback, loudly, because that is the one state an operator cannot
    otherwise see;
  - the window the agent states is the window the guard enforces;
  - ``list_registered_models()`` leads with the serving model and never
    calls a merely-downloaded model "loaded".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import jaeger_ai.main as main
from jaeger_ai.core.models import model_resolver


def _client(kind="external", provider="ollama-cloud",
            model="qwen3.5:397b", ctx=262_144):
    return SimpleNamespace(
        kind=kind, provider=provider, model_name=model, loaded_ctx=ctx,
        describe=lambda: f"{kind} · {provider} · {model}",
    )


def _cfg(*, external=True, model="qwen3.5:397b", ctx=262_144):
    return SimpleNamespace(
        model=SimpleNamespace(ctx=8192, max_tokens=1024,
                              model_path="/models/local"),
        external_model=SimpleNamespace(
            enabled=external, provider="ollama-cloud", model=model, ctx=ctx,
            max_tokens=4096, base_url="https://ollama.com/v1"),
    )


@pytest.fixture
def pipeline():
    """Swap the module-level pipeline and always put it back."""
    saved = {k: main._pipeline.get(k) for k in ("client", "config", "layout")}
    yield main._pipeline
    for k, v in saved.items():
        main._pipeline[k] = v


# ── serving_model ──────────────────────────────────────────────────


def test_no_client_means_no_claim(pipeline):
    """Pre-boot, the honest answer is "nothing yet" — not the config's
    intent dressed up as fact."""
    pipeline["client"] = None
    assert model_resolver.serving_model() is None


def test_serving_model_reports_the_live_client(pipeline):
    pipeline["client"] = _client()
    pipeline["config"] = _cfg()
    row = model_resolver.serving_model()
    assert row["name"] == "qwen3.5:397b"
    assert row["provider"] == "ollama-cloud"
    assert row["location"] == "cloud"
    assert row["context_length"] == 262_144
    assert row["serving"] is True
    assert row["fallback_active"] is False


def test_a_cloud_lane_that_is_not_answering_is_reported_as_fallback(pipeline):
    """The failure an operator cannot see: config still says cloud, a
    local model is doing the work. Saying "you're on Ollama Cloud" here
    would be the worst possible answer."""
    pipeline["config"] = _cfg(external=True, model="deepseek-v4-pro:0813")
    pipeline["client"] = _client(
        kind="local", provider="", model="gemma-4-E4B-it-Q4_K_M", ctx=8192)
    row = model_resolver.serving_model()
    assert row["fallback_active"] is True
    assert row["name"] == "gemma-4-E4B-it-Q4_K_M"
    assert "deepseek-v4-pro:0813" in row["requested"]
    assert "FALLBACK" in row["status"]


def test_a_different_cloud_model_than_requested_is_also_a_fallback(pipeline):
    pipeline["config"] = _cfg(external=True, model="deepseek-v4-pro:0813")
    pipeline["client"] = _client(model="qwen3.5:397b")
    row = model_resolver.serving_model()
    assert row["fallback_active"] is True
    assert "qwen3.5:397b" in row["status"]


def test_reverse_drift_is_reported_too(pipeline):
    """Config selects the local lane, a cloud client is live. Still a
    disagreement the operator should hear about — they may be paying for
    tokens they think are running on-device."""
    pipeline["config"] = _cfg(external=False)
    pipeline["client"] = _client()
    row = model_resolver.serving_model()
    assert row["fallback_active"] is True


def test_window_falls_back_to_the_guard_budget(pipeline):
    """``loaded_ctx`` can still be 0 when the session prompt is frozen.
    The stated window must then come from the same resolver the guard
    budgets against — a self-description that disagrees with the trimmer
    is worse than no number."""
    pipeline["config"] = _cfg(ctx=262_144)
    pipeline["client"] = _client(ctx=0)
    row = model_resolver.serving_model()
    assert row["context_length"] == 262_144


# ── the list the agent's list_models() tool reports ────────────────


def test_listing_leads_with_the_serving_model(pipeline):
    pipeline["client"] = _client()
    pipeline["config"] = _cfg()
    rows = model_resolver.list_registered_models(include_providers=False)
    assert rows[0]["serving"] is True
    assert rows[0]["name"] == "qwen3.5:397b"


def test_downloaded_is_never_described_as_loaded(pipeline):
    """"ready (user cache)" read as "currently loaded" to anything
    summarising this list, which is how a not-even-loaded Gemma got
    reported as the active model."""
    pipeline["client"] = None
    rows = model_resolver.list_registered_models(include_providers=False)
    registry = [r for r in rows if r.get("source") == "registry"]
    assert registry, "expected the GGUF registry rows"
    for row in registry:
        assert row["serving"] is False
        status = row["status"]
        # Either it says it isn't loaded, or it says it isn't downloaded.
        # What it must never do is read as an active-model claim.
        assert ("not loaded" in status) or status.startswith("not downloaded")
        assert "ready" not in status


def test_registry_rows_state_that_the_window_is_unknown(pipeline):
    """Unknown beats guessed: a name-shaped guess is what produced
    "Qwen3 typically supports up to 256K" about an unloaded model."""
    pipeline["client"] = None
    rows = model_resolver.list_registered_models(include_providers=False)
    for row in [r for r in rows if r.get("source") == "registry"]:
        if not row.get("context_length"):
            assert row["context_length_unknown_reason"]


def test_the_registry_only_view_is_unchanged_for_the_picker(pipeline):
    """``discover_jaeger()`` wants registry rows alone — the serving lane
    and provider catalogues are surveyed separately by ``discover_all``."""
    pipeline["client"] = _client()
    rows = model_resolver.list_registered_models(
        include_serving=False, include_providers=False)
    assert rows
    assert all(r["source"] == "registry" for r in rows)


# ── the system-prompt block ────────────────────────────────────────


def test_runtime_block_states_model_and_window(pipeline):
    pipeline["client"] = _client()
    pipeline["config"] = _cfg()
    block = main._runtime_identity_block()
    assert "qwen3.5:397b" in block
    assert "262,144" in block
    assert "never guess" in block.lower()


def test_runtime_block_announces_a_fallback(pipeline):
    pipeline["config"] = _cfg(external=True, model="deepseek-v4-pro:0813")
    pipeline["client"] = _client(
        kind="local", provider="", model="gemma-4-E4B-it-Q4_K_M", ctx=8192)
    block = main._runtime_identity_block()
    assert "FALLBACK IN EFFECT" in block
    assert "deepseek-v4-pro:0813" in block


def test_runtime_block_is_empty_before_boot(pipeline):
    """No client, no claims — and no empty heading bloating the prompt."""
    pipeline["client"] = None
    assert main._runtime_identity_block() == ""
