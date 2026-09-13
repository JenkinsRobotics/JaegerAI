"""Agent settings are persisted once, distinct from optional speech tools."""

import json
from types import SimpleNamespace

from jaeger_agent.core.config import MultimodalConfig

from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.settings import catalog


def test_agent_settings_defaults_and_roundtrip(tmp_path):
    layout = SimpleNamespace(config_path=tmp_path / "config.yaml")
    config = Config(instance_name="test", model=ModelConfig(model_path="/dev/null"))
    assert isinstance(config.multimodal, MultimodalConfig)
    assert config.multimodal.audio_mode == "structured"
    assert config.multimodal.output_mode == "dynamic"
    dump_yaml(layout.config_path, config)
    descriptors = catalog._descriptors(layout)
    json.dumps(descriptors)  # default-factory model paths must be serializable
    settings = {row["path"]: row for row in descriptors}
    assert settings["multimodal.stt_model"]["restart"] is True
    assert settings["multimodal.kokoro_voice"]["current"] == "af_heart"
    result = catalog.set_value(layout, "multimodal.kokoro_voice", "am_adam")
    assert result["restart_required"] is True
    restored = load_yaml(layout.config_path, Config)
    assert restored.multimodal.kokoro_voice == "am_adam"
    assert restored.kokoro_tts == config.kokoro_tts
    assert restored.whisper_stt == config.whisper_stt
