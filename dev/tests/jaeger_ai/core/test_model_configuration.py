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


def test_cli_backend_is_a_selectable_jaeger_brain(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        lambda name, path=None: f"/opt/homebrew/bin/{name}" if name == "claude" else None,
    )
    layout = _layout(tmp_path)
    result = configure_model(layout, provider="cli", model="claude")
    config = load_yaml(layout.config_path, Config)
    assert result["provider"] == "cli"
    assert result["model"] == "claude"
    assert config.external_model.enabled is True
    assert config.external_model.provider == "cli"
    assert config.external_model.model == "claude"
    assert config.external_model.api_key_credential == ""


def test_cli_catalog_name_normalizes_to_cli_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        lambda name, path=None: "/bin/true",
    )
    layout = _layout(tmp_path)
    result = configure_model(layout, provider="claude-cli", model="cli:claude")
    assert result["provider"] == "cli"
    assert result["model"] == "claude"


def test_onboarding_stack_switch_replaces_endpoint_and_credentials(tmp_path):
    from jaeger_ai.core.models.configuration import update_configured_stack
    layout = _layout(tmp_path)
    configure_model(layout, provider="anthropic", model="claude-test")
    result = update_configured_stack(layout, {
        "primary_provider": "openai", "primary_model": "gpt-test",
        "tts_voice": "af_heart"})
    cfg = load_yaml(layout.config_path, Config)
    assert result["restart_required"]
    assert cfg.external_model.provider == "openai"
    assert cfg.external_model.base_url == "https://api.openai.com/v1"
    assert cfg.external_model.api_key_credential == "openai_api_key"


def test_onboarding_stack_invalid_fallback_is_atomic(tmp_path):
    import pytest
    from jaeger_ai.core.models.configuration import update_configured_stack
    layout = _layout(tmp_path)
    before = layout.config_path.read_bytes()
    with pytest.raises(ValueError):
        update_configured_stack(layout, {
            "primary_provider": "openai", "primary_model": "gpt-test",
            "fallback_provider": "anthropic", "fallback_model": "gpt-test"})
    assert layout.config_path.read_bytes() == before


def test_onboarding_credentials_survive_process_environment(tmp_path, monkeypatch):
    from jaeger_ai.core.models import onboarding_credentials as onboarding
    from jaeger_agent.core.credentials import get_credential
    layout = _layout(tmp_path)
    monkeypatch.setattr(onboarding, "_pending", {})
    monkeypatch.setenv("OPENAI_API_KEY", "")
    onboarding.calibrate_provider(None, "openai", "test-only-key")
    onboarding.persist_pending(layout)
    monkeypatch.delenv("OPENAI_API_KEY")
    assert get_credential(layout, "openai_api_key") == "test-only-key"
    assert not onboarding._pending


def test_onboarding_selection_builds_the_live_agent_client(tmp_path, monkeypatch):
    import jaeger_ai.main as runtime
    from jaeger_ai.core.models.configuration import update_configured_stack
    layout = _layout(tmp_path)
    selected = object()
    observed = []
    def make_client(config, instance, warmup):
        observed.append((config.external_model.provider, config.external_model.model))
        assert instance == layout
        return selected
    monkeypatch.setattr(runtime, "_pipeline", {"layout": layout, "client": object()})
    monkeypatch.setattr(runtime, "_jaeger_agents_by_session", {})
    monkeypatch.setattr(runtime, "unload_local_brain", lambda: None)
    monkeypatch.setattr(runtime, "make_client", make_client)
    monkeypatch.setattr(runtime, "build_system_prompt", lambda layout: "test")
    update_configured_stack(layout, {"primary_provider": "openai", "primary_model": "gpt-test"})
    assert runtime.apply_live_model()
    assert runtime._pipeline["client"] is selected
    assert observed == [("openai", "gpt-test")]


def test_setup_rerun_preserves_identity_and_other_settings(tmp_path):
    from jaeger_ai.core.instance.onboarding_setup import complete_setup
    from jaeger_ai.core.instance.first_boot import needs_model_selection
    layout = _layout(tmp_path)
    layout.identity_path.write_text("name: Existing OS\n")
    layout.manifest_path.write_text("{}")
    memory = layout.root / "memory" / "operator-note.txt"
    memory.parent.mkdir(exist_ok=True)
    memory.write_text("preserve me")
    identity = layout.identity_path.read_bytes()
    result = complete_setup(layout, {"awake_provider": "openai", "awake_model": "gpt-test"})
    assert result == layout
    assert load_yaml(layout.config_path, Config).external_model.model == "gpt-test"
    assert layout.identity_path.read_bytes() == identity
    assert memory.read_text() == "preserve me"
    assert not needs_model_selection(layout)


def test_missing_model_selection_does_not_modify_existing_config(tmp_path):
    import pytest
    from jaeger_ai.core.instance.onboarding_setup import complete_setup
    layout = _layout(tmp_path)
    before = layout.config_path.read_bytes()
    with pytest.raises(ValueError, match="Select a provider and model"):
        complete_setup(layout, {})
    assert layout.config_path.read_bytes() == before


def test_resume_setup_keeps_conversation_answers(tmp_path):
    from jaeger_ai.core.instance.onboarding_setup import complete_setup
    from jaeger_ai.core.instance import first_boot as fb
    layout = _layout(tmp_path)
    layout.identity_path.write_text("name: Existing\n")
    layout.manifest_path.write_text("{}")
    fb.begin(layout)
    fb.record_bench(layout, {"tier_label": "32 GB"})
    fb.record_character(layout, "custom")
    before = fb.snapshot(layout)
    complete_setup(layout, {"awake_provider": "openai", "awake_model": "gpt-test",
                            "resume_onboarding": True})
    after = fb.snapshot(layout)
    assert after["status"] == before["status"]
    assert after["hardware_bench"] == before["hardware_bench"]
    assert after["character_path"] == "custom"


def test_inference_probe_accepts_budget_exhausted_reasoning(monkeypatch):
    from types import SimpleNamespace
    from jaeger_ai.core.models.external_model import ExternalModelClient
    client = object.__new__(ExternalModelClient)
    client.provider = "ollama"
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=""), finish_reason="length")],
        usage=SimpleNamespace(completion_tokens=64))
    monkeypatch.setattr(client, "_chat_openai_completion", lambda *args: response)
    client.verify_inference()


def test_inference_probe_rejects_genuinely_empty_completion(monkeypatch):
    import pytest
    from types import SimpleNamespace
    from jaeger_ai.core.models.external_model import ExternalModelClient, ExternalModelError
    client = object.__new__(ExternalModelClient)
    client.provider = "ollama"
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=""), finish_reason="stop")],
        usage=SimpleNamespace(completion_tokens=0))
    monkeypatch.setattr(client, "_chat_openai_completion", lambda *args: response)
    with pytest.raises(ExternalModelError):
        client.verify_inference()


def test_restored_onboarding_identity_and_calibration_are_saved(tmp_path):
    from jaeger_ai.core.instance.onboarding_setup import complete_setup, onboarding_identity
    from jaeger_ai.core.instance.schemas import Identity
    layout = _layout(tmp_path)
    dump_yaml(layout.identity_path, Identity(name="Before", role="assistant", personality="helpful"))
    layout.manifest_path.write_text("{}")
    complete_setup(layout, {"awake_provider": "openai", "awake_model": "gpt-test",
        "display_name": "After", "role": "Research assistant", "character_id": "assistant",
        "voice_profile": "male", "interaction_posture": "pragmatic"})
    saved = onboarding_identity(layout)
    assert saved["display_name"] == "After"
    assert saved["role"] == "Research assistant"
    assert saved["character_id"] == "assistant"
    assert saved["voice_profile"] == "male"
    assert saved["interaction_posture"] == "pragmatic"
    assert load_yaml(layout.config_path, Config).kokoro_tts.voice == "am_michael"
