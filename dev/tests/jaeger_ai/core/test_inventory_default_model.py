"""With no certification file, the picker default is the instance's configured model."""
from jaeger_ai.core.models import discovery


def _run(monkeypatch, tmp_path, configured, models):
    monkeypatch.setattr(discovery, "configured_instance_model", lambda root=None: configured)
    monkeypatch.setattr(discovery, "discover_ollama", lambda *a, **k: {"online": True, "models": models})
    for name in ("discover_lmstudio",):
        if hasattr(discovery, name):
            monkeypatch.setattr(discovery, name, lambda *a, **k: {"online": False, "models": []})
    return discovery.canonical_runtime_inventory(tmp_path / "nope", refresh=True)


def test_local_configured_model_is_the_default_on_the_local_lane(monkeypatch, tmp_path):
    inv = _run(monkeypatch, tmp_path, "gemma-4-26b:latest",
               [{"name": "gemma-4-26b:latest"}, {"name": "glm-5.3-flash:cloud", "remote_host": "x"}])
    assert inv["default_model"] == "gemma-4-26b:latest"
    assert inv["default_model_full_id"] == "@ollama-local:gemma-4-26b:latest"


def test_cloud_fallback_only_when_nothing_is_configured(monkeypatch, tmp_path):
    inv = _run(monkeypatch, tmp_path, "", [{"name": "glm-5.3-flash:cloud", "remote_host": "x"}])
    assert inv["default_model_full_id"] == "@ollama-cloud:glm-5.3-flash:cloud"


def test_configured_instance_model_reads_config_yaml(tmp_path, monkeypatch):
    import jaeger_ai.core.instance.first_boot as fb
    monkeypatch.setattr(fb, "instance_dir", lambda root: tmp_path)
    (tmp_path / "config.yaml").write_text("external_model:\n  enabled: true\n  model: gemma-4-26b:latest\n")
    assert discovery.configured_instance_model(tmp_path) == "gemma-4-26b:latest"
    (tmp_path / "config.yaml").write_text("external_model:\n  enabled: false\n  model: m\n")
    assert discovery.configured_instance_model(tmp_path) == ""
