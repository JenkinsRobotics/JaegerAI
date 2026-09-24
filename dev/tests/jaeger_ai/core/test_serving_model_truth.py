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

from jaeger_ai import main
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
    assert row["model"] == "qwen3.5:397b"
    assert row["provider"] == "ollama-cloud"
    assert row["location"] == "cloud"
    assert row["context_length"] == 262_144
    assert row["serving"] is True
    assert row["fallback_active"] is False


def test_cloud_tag_through_signed_in_local_ollama_is_location_cloud(pipeline):
    pipeline["client"] = _client(
        provider="ollama", model="glm-5.2:cloud", ctx=1_048_576)
    pipeline["config"] = SimpleNamespace(
        model=SimpleNamespace(ctx=8192, max_tokens=1024),
        external_model=SimpleNamespace(
            enabled=True,
            provider="ollama",
            model="glm-5.2:cloud",
            ctx=1_048_576,
            max_tokens=4096,
            base_url="http://localhost:11434/v1",
        ),
    )
    row = model_resolver.serving_model()
    assert row["provider"] == "ollama"  # the real transport owner
    assert row["location"] == "cloud"


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


def test_cloud_catalog_omits_local_ollama_rows(pipeline, monkeypatch):
    """Same model id on Ollama Cloud and local Ollama is how a cloud pick
    started the on-device daemon. While a hosted brain is selected, local
    rows stay out of the default catalog."""
    pipeline["client"] = _client()
    pipeline["config"] = _cfg()
    monkeypatch.setattr(
        "jaeger_ai.core.models.discovery.discover_ollama",
        lambda: {"online": True, "models": [{"name": "qwen3.5:397b"}]},
    )
    rows = model_resolver.list_registered_models()
    assert all(r.get("provider") != "ollama" for r in rows)
    assert all(r.get("location") != "local" for r in rows)


def test_hybrid_ollama_catalog_separates_local_and_cloud_rows(pipeline, monkeypatch):
    pipeline["client"] = _client(
        provider="ollama", model="gemma4:latest", ctx=65_536)
    pipeline["config"] = SimpleNamespace(
        model=SimpleNamespace(ctx=8192, max_tokens=1024),
        external_model=SimpleNamespace(
            enabled=True,
            provider="ollama",
            model="gemma4:latest",
            ctx=65_536,
            max_tokens=4096,
            base_url="http://localhost:11434/v1",
        ),
    )
    monkeypatch.setattr(
        "jaeger_ai.core.models.discovery.discover_ollama",
        lambda: {
            "online": True,
            "models": [
                {"name": "local", "capabilities": ["completion", "tools"]},
                {
                    "name": "cloud:cloud",
                    "remote_host": "https://ollama.com",
                    "capabilities": ["completion", "tools"],
                },
                {"name": "embed", "capabilities": ["embedding"]},
            ],
        },
    )
    monkeypatch.setattr(
        "jaeger_ai.core.models.ollama_context.probe_ollama_context",
        lambda *_args, **_kwargs: (65_536, "model_info"),
    )
    rows = model_resolver.list_registered_models()
    assert any(row.get("provider") == "ollama" and row.get("name") == "local" for row in rows)
    assert any(
        row.get("provider") == "ollama-cloud"
        and row.get("location") == "cloud"
        and row.get("name") == "cloud:cloud"
        for row in rows
    )
    assert all(row.get("name") != "embed" for row in rows)


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


def test_gateway_turn_model_overrides_stale_legacy_state_and_restores(pipeline):
    from jaeger_ai.core.runtime.modes import mode_info, set_mode

    pipeline['client'] = _client(kind='local', provider='mlx', model='old-local')
    pipeline['config'] = _cfg(external=False)
    with model_resolver.serving_model_scope(_client(model='actual-session:cloud'), _cfg(model='actual-session:cloud')):
        info = mode_info()
        assert info['model'] == 'actual-session:cloud'
        assert info['mode'] is None
        assert info['local_preset_active'] is False
        assert info['local_preset_model'] is None
        assert info['voice'] is None
        assert info['options'] == []
        assert info['serving']['location'] == 'cloud'
        assert 'actual-session:cloud' in main._runtime_identity_block()
        assert 'old-local' not in main._runtime_identity_block()
        assert set_mode('high')['ok'] is False
        rows = model_resolver.list_registered_models(include_providers=False)
        assert rows[0]['model'] == info['model']
        assert rows[0]['fallback_active'] is False
    assert model_resolver.serving_model()['model'] == 'old-local'


def test_empty_legacy_pipeline_cannot_claim_default_gemma(pipeline):
    from jaeger_ai.core.runtime.modes import mode_info

    pipeline['client'] = None
    pipeline['config'] = _cfg(external=False)
    info = mode_info()
    assert info['model'] is None
    assert info['mode'] is None
    assert info['kind'] == 'unknown'


def test_simultaneous_turns_report_their_own_model(pipeline):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from jaeger_ai.core.runtime.modes import mode_info

    barrier = Barrier(2)
    def turn(name):
        with model_resolver.serving_model_scope(_client(model=name), _cfg(model=name)):
            barrier.wait(timeout=5)
            return mode_info()['model']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(turn, name) for name in ('session-a', 'session-b')]
        assert [future.result() for future in futures] == ['session-a', 'session-b']


def test_runtime_status_does_not_report_certification_as_live_provider(pipeline, monkeypatch):
    from jaeger_ai.core.entity.runtime_status import collect_runtime_status
    pipeline['client'] = _client(provider='ollama', model='configured:cloud')
    pipeline['config'] = _cfg(model='configured:cloud')
    monkeypatch.setenv('JAEGER_CHAT_PROVIDER', 'stale-provider')
    status = collect_runtime_status(include_network=False)
    assert status['Provider']['active_chat_provider'] == 'ollama'
    assert status['Provider']['model'] == 'configured:cloud'
    assert status['Provider']['location'] == 'cloud'
    pipeline['client'] = None
    assert collect_runtime_status(include_network=False)['Provider']['active_chat_provider'] == ''
