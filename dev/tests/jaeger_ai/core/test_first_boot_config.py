"""First-boot turn boot must not die on a missing instance config.yaml.

A scratch/first-boot instance has no config.yaml — `jaeger setup` writes it.
The Gateway turn path previously crashed every such turn with
FileNotFoundError at run boot (proven live on the scratch daemon, 2026-10-22).
The loader falls back to the wizard's defaults; it never persists anything.
"""
from pathlib import Path

from jaeger_ai.core.entity.runtime import load_instance_config_or_default
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import (
    Config, ModelConfig, dump_yaml, load_yaml,
)
from jaeger_ai.core.models.model_resolver import DEFAULT_MODEL


def _layout(tmp_path: Path) -> InstanceLayout:
    layout = InstanceLayout(root=tmp_path / "state" / "instances" / "default")
    layout.ensure_dirs()
    return layout


def test_first_boot_instance_loads_wizard_defaults_without_config_file(tmp_path):
    layout = _layout(tmp_path)
    assert not layout.config_path.exists()
    cfg = load_instance_config_or_default(layout)
    assert cfg.instance_name == "default"
    assert str(cfg.model.model_path) == DEFAULT_MODEL
    assert cfg.automation.interaction_tier == "agent"


def test_existing_config_wins_over_defaults(tmp_path):
    layout = _layout(tmp_path)
    dump_yaml(layout.config_path, Config(
        instance_name="custom", model=ModelConfig(model_path="/dev/null"),
    ))
    cfg = load_instance_config_or_default(layout)
    assert cfg.instance_name == "custom"
    # Round-trip: what the wizard wrote is what the loader returns.
    assert load_yaml(layout.config_path, Config).instance_name == "custom"


def test_loader_never_persists_a_default_config(tmp_path):
    layout = _layout(tmp_path)
    load_instance_config_or_default(layout)
    assert not layout.config_path.exists(), (
        "a turn-boot read must not write operator config — the wizard is the "
        "one authoritative writer"
    )