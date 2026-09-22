"""A picker id must never reach a provider as a model name.

Live defect (2026-09-21 audit): the WebUI picker persisted
``@ollama-cloud:glm-5.3-flash:cloud`` into ``external_model.model``. The ReAct
lane sent it to Ollama verbatim and got ``400 invalid model name`` on every
tool-using turn, while the text-only lane stripped the hint itself and kept
answering — so the breakage looked like a model that plans but never acts.
"""
from __future__ import annotations

from jaeger_ai.contract.model_ids import provider_model_name, split_routed_model_id
from jaeger_ai.core.instance.schemas import ExternalModelConfig, load_yaml


def test_lane_is_first_segment_and_model_keeps_its_tag_colons():
    assert split_routed_model_id("@ollama-cloud:glm-5.3-flash:cloud") == (
        "ollama-cloud",
        "glm-5.3-flash:cloud",
    )
    assert split_routed_model_id("@ollama-local:qwen3:8b") == ("ollama-local", "qwen3:8b")


def test_bare_model_names_pass_through_untouched():
    for name in ("glm-5.3-flash:cloud", "claude-opus-5", "gpt-5.1", ""):
        assert split_routed_model_id(name) == (None, name)
        assert provider_model_name(name) == name


def test_external_model_field_rejects_the_picker_hint():
    cfg = ExternalModelConfig(provider="ollama", model="@ollama-cloud:kimi-k2.7-code:cloud")
    assert cfg.model == "kimi-k2.7-code:cloud"


def test_a_config_already_holding_a_picker_id_heals_on_load(tmp_path):
    path = tmp_path / "external_model.yaml"
    path.write_text(
        "enabled: true\n"
        "provider: ollama\n"
        "base_url: http://127.0.0.1:11434/v1\n"
        "model: '@ollama-cloud:glm-5.3-flash:cloud'\n",
        encoding="utf-8",
    )

    cfg = load_yaml(path, ExternalModelConfig)

    assert cfg.model == "glm-5.3-flash:cloud"


def test_assignment_is_validated_too():
    """``selected_model_config`` assigns the field; without validate_assignment
    the picker id was written back to config.yaml verbatim."""
    cfg = ExternalModelConfig(provider="ollama", model="glm-5.3-flash:cloud")
    cfg.model = "@ollama-cloud:kimi-k2.7-code:cloud"
    assert cfg.model == "kimi-k2.7-code:cloud"
