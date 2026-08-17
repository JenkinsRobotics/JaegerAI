from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.models.configuration import configure_model


def _layout(tmp_path):
    layout = InstanceLayout(root=tmp_path / "instance")
    layout.root.mkdir(parents=True)
    layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(
        instance_name="test", model=ModelConfig(model_path="/dev/null")))
    return layout


def test_cloud_model_configuration_is_validated_and_owned_by_jaeger(tmp_path):
    layout = _layout(tmp_path)
    result = configure_model(
        layout,
        provider="gemini",
        model="gemini-2.5-pro",
        context_length=1_048_576,
    )
    config = load_yaml(layout.config_path, Config)
    assert result["owner"] == "jaeger"
    assert result["changed"] is True
    assert config.external_model.enabled is True
    assert config.external_model.provider == "gemini"
    assert config.external_model.model == "gemini-2.5-pro"
    assert config.external_model.ctx == 1_048_576
    assert config.model.ctx != 1_048_576


def test_dry_run_does_not_write_config(tmp_path):
    layout = _layout(tmp_path)
    before = layout.config_path.read_bytes()
    result = configure_model(
        layout, provider="openai", model="gpt-4o", dry_run=True)
    assert result["changed"] is True
    assert layout.config_path.read_bytes() == before


def test_keyless_local_server_clears_stale_secret_references(tmp_path):
    layout = _layout(tmp_path)
    configure_model(layout, provider="openai", model="gpt-4o")

    configure_model(layout, provider="ollama", model="qwen3:8b")

    config = load_yaml(layout.config_path, Config)
    assert config.external_model.provider == "ollama"
    assert config.external_model.api_key_credential == ""
    assert config.external_model.api_key_env == ""
