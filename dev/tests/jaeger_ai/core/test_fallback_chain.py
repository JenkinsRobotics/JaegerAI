"""Configured fallback chain — walk only when the brain is dead."""

from __future__ import annotations

from jaeger_ai.core.models.configuration import (
    configure_fallback_chain,
    dead_brain_reason,
)
from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, FallbackModel


def test_connect_failure_is_a_dead_brain():
    assert dead_brain_reason("unreachable — Connection refused") is True
    assert dead_brain_reason("not configured — needs an API key") is True
    assert dead_brain_reason("401 Unauthorized") is True


def test_timeouts_and_rate_limits_do_not_walk():
    assert dead_brain_reason("timeout waiting for tokens") is False
    assert dead_brain_reason("429 rate limit") is False
    assert dead_brain_reason("context length exceeded") is False


def test_schema_round_trip():
    ext = ExternalModelConfig(
        enabled=True,
        provider="ollama-cloud",
        model="gemma4:31b",
        fallback=[
            FallbackModel(provider="anthropic", model="claude-sonnet-4-6"),
            FallbackModel(provider="local", model="gemma-4-e4b"),
        ],
    )
    dumped = ext.model_dump()
    again = ExternalModelConfig.model_validate(dumped)
    assert len(again.fallback) == 2
    assert again.fallback[1].provider == "local"


def test_configure_rejects_local_fallback(tmp_path):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import ModelConfig, dump_yaml

    layout = InstanceLayout(root=tmp_path / "instance")
    layout.root.mkdir(parents=True)
    layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null")))
    try:
        configure_fallback_chain(layout, [
            {"provider": "local", "model": "gemma-4-e4b"},
        ])
    except ValueError as exc:
        assert "local fallback is disabled" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("local fallback must be rejected")


def test_configure_writes_the_chain(tmp_path):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import ModelConfig, dump_yaml, load_yaml

    layout = InstanceLayout(root=tmp_path / "instance")
    layout.root.mkdir(parents=True)
    layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null")))
    result = configure_fallback_chain(layout, [
        {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    ])
    assert result["ok"] is True
    assert result["changed"] is True
    loaded = load_yaml(layout.config_path, Config)
    assert loaded.external_model.fallback[0].model == "claude-sonnet-4-6"
