"""Unit and contract tests for the 3-Tier Agency architecture (Chat, Agent, Jaeger)."""
from __future__ import annotations

import pathlib
import pytest
from pydantic import ValidationError

from jaeger_ai.contract.modes import (
    DEFAULT_INTERACTION_TIER,
    INTERACTION_TIERS,
    TIER_DESCRIPTIONS,
    TIER_NAMES,
    TIER_NUMBERS,
    InteractionTier,
)
from jaeger_ai.core.instance.schemas import AutomationConfig, Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.settings.catalog import describe


def test_interaction_tiers_contract() -> None:
    """The canonical contract defines chat=1, agent=2, jaeger=3."""
    assert INTERACTION_TIERS == ("chat", "agent", "jaeger")
    assert DEFAULT_INTERACTION_TIER == "agent"
    assert TIER_NUMBERS["chat"] == 1
    assert TIER_NUMBERS["agent"] == 2
    assert TIER_NUMBERS["jaeger"] == 3
    assert TIER_NAMES[1] == "chat"
    assert TIER_NAMES[2] == "agent"
    assert TIER_NAMES[3] == "jaeger"
    for t in INTERACTION_TIERS:
        assert t in TIER_DESCRIPTIONS
        assert len(TIER_DESCRIPTIONS[t]) > 10


def test_automation_config_interaction_tier_schema() -> None:
    """AutomationConfig defaults to 'agent' and validates allowable tiers."""
    cfg = AutomationConfig()
    assert cfg.interaction_tier == "agent"
    assert cfg.autonomy == "auto"

    cfg_chat = AutomationConfig(interaction_tier="chat")
    assert cfg_chat.interaction_tier == "chat"

    cfg_jaeger = AutomationConfig(interaction_tier="jaeger")
    assert cfg_jaeger.interaction_tier == "jaeger"

    with pytest.raises(ValidationError):
        AutomationConfig(interaction_tier="droid")  # forbidden string


def test_settings_catalog_derives_interaction_tier(tmp_path: pathlib.Path) -> None:
    """Single-source derivation: the settings catalog exposes automation.interaction_tier automatically."""
    class _Layout:
        def __init__(self, p: pathlib.Path) -> None:
            self.config_path = p

    cfg_path = tmp_path / "config.yaml"
    dump_yaml(cfg_path, Config(instance_name="test-inst", model=ModelConfig(model_path="/dev/null")))

    desc = describe(_Layout(cfg_path), "automation.interaction_tier")
    assert desc is not None
    assert desc["type"] == "enum"
    assert desc["group"] == "autonomy"
    assert desc["default"] == "agent"
    assert desc["current"] == "agent"
    assert desc["choices"] == ["chat", "agent", "jaeger"]
    assert "Agency tier:" in desc["description"]
