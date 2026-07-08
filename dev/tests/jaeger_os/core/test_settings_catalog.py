"""The settings catalog is THE contract — CLI and the Swift app both drive
it, so it's tested hard here: schema-derived descriptors, enum coercion,
out-of-range rejection, nested paths, the restart flag, and the round-trip
back through the Pydantic model onto disk.

The whole point of the architecture is single-source: a setting is one
annotated ``Field`` in ``core/instance/schemas.py`` and everything derives
from it. These tests pin that derivation.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from jaeger_os.core.instance.schemas import (
    Config, ModelConfig, dump_yaml, load_yaml)
from jaeger_os.core.settings.catalog import (
    catalog, describe, get_value, groups, set_value)


class _Layout:
    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path


@pytest.fixture()
def layout(tmp_path) -> _Layout:
    cfg_path = tmp_path / "config.yaml"
    dump_yaml(cfg_path, Config(instance_name="t",
                               model=ModelConfig(model_path="/dev/null")))
    return _Layout(cfg_path)


# ── derivation: descriptors come from the schema, not a hand list ──────────

def test_all_eight_spec_groups_are_live(layout):
    names = {g["name"] for g in groups(layout)}
    assert {"model", "display", "voice", "tts", "autonomy",
            "permissions", "retention", "interaction"} <= names


def test_group_output_is_page_ordered(layout):
    order = [g["name"] for g in groups(layout)]
    # model leads, interaction trails the NAMED eight-group page order —
    # spill-over groups an engine-module contributes (0.8 M1: "kokoro_tts",
    # nested at Config.kokoro_tts) sort alphabetically after it, per
    # GROUP_ORDER's own "eight spec groups, then any spill-over" contract.
    assert order.index("model") < order.index("display") < order.index("voice")
    named_order = [g for g in order if g != "kokoro_tts"]
    assert named_order.index("interaction") == len(named_order) - 1
    assert "kokoro_tts" in order
    assert order.index("kokoro_tts") > order.index("interaction")


def test_kokoro_tts_engine_module_group_is_live(layout):
    """0.8 M1: nesting ``KokoroTTSConfig`` under ``Config.kokoro_tts``
    (jaeger_os/nodes/kokoro_tts/config.py) must expose its ``kokoro_tts``
    group with zero catalog-code edits — the whole point of the
    single-source design this file pins."""
    rows = {g["name"]: g["count"] for g in groups(layout)}
    assert rows.get("kokoro_tts") == 3
    voice = describe(layout, "kokoro_tts.voice")
    assert voice["type"] == "str" and voice["group"] == "kokoro_tts"
    lang = describe(layout, "kokoro_tts.lang")
    assert lang["type"] == "str"
    rate = describe(layout, "kokoro_tts.sample_rate")
    assert rate["type"] == "int" and rate["advanced"] is True


def test_enum_descriptor_carries_choices_from_literal(layout):
    d = describe(layout, "voice.speech_engine")
    assert d["type"] == "enum"
    assert d["choices"] == ["kokoro", "apple"]
    assert d["group"] == "tts"


def test_numeric_descriptor_carries_validation_bounds(layout):
    d = describe(layout, "model.ctx")
    assert d["type"] == "int"
    assert d["validation"] == {"min": 512, "max": 131072}
    assert d["default"] == 8192


def test_bool_and_str_types(layout):
    assert describe(layout, "voice.speak_replies")["type"] == "bool"
    assert describe(layout, "deep_think.coder_model")["type"] == "str"


def test_advanced_flag_and_filtering(layout):
    assert describe(layout, "voice.self_speech_threshold")["advanced"] is True
    voice_basic = catalog(layout, advanced=False)["voice"]
    paths = {d["path"] for d in voice_basic}
    assert "voice.self_speech_threshold" not in paths
    assert "voice.speak_replies" in paths


def test_unexposed_fields_are_absent(layout):
    # Identity key, model weights path (a Path), and deferred blocks
    # (avatar/hardware/plugins/external_model) carry no _setting metadata.
    all_paths = {d["path"] for grp in catalog(layout).values() for d in grp}
    for hidden in ("instance_name", "model.model_path", "avatar.enabled",
                   "hardware.package", "external_model.enabled",
                   "plugins.autostart"):
        assert hidden not in all_paths


def test_current_reflects_loaded_value(layout):
    assert get_value(layout, "voice.speak_replies") is True
    set_value(layout, "voice.speak_replies", False)
    assert get_value(layout, "voice.speak_replies") is False


# ── set(): coercion, validation, persistence, restart flag ─────────────────

def test_set_persists_through_the_model_to_disk(layout):
    res = set_value(layout, "voice.speak_replies", False)
    assert res == {"ok": True, "restart_required": False,
                   "path": "voice.speak_replies", "value": False}
    # Round-tripped onto disk via the schema's own dump_yaml.
    cfg = load_yaml(layout.config_path, Config)
    assert cfg.voice.speak_replies is False


def test_set_restart_flag_from_schema(layout):
    # model.ctx is annotated restart=True; voice fields restart=False.
    assert set_value(layout, "model.ctx", 16384)["restart_required"] is True
    assert set_value(layout, "voice.wake_word", False)["restart_required"] is False


def test_enum_coercion_accepts_valid_rejects_invalid(layout):
    assert set_value(layout, "voice.speech_engine", "apple")["value"] == "apple"
    with pytest.raises(ValueError):
        set_value(layout, "voice.speech_engine", "espeak")


def test_out_of_range_is_rejected(layout):
    with pytest.raises(ValueError):
        set_value(layout, "model.ctx", 999_999)     # le=131072
    with pytest.raises(ValueError):
        set_value(layout, "model.ctx", 10)          # ge=512
    # The bad write never touched disk.
    assert load_yaml(layout.config_path, Config).model.ctx == 8192


def test_string_coercion_from_cli_style_input(layout):
    # The CLI hands values in as strings — Pydantic coerces through the model.
    assert set_value(layout, "model.ctx", "16384")["value"] == 16384
    assert set_value(layout, "voice.wake_word", "false")["value"] is False
    assert set_value(layout, "voice.follow_up_seconds", "12.5")["value"] == 12.5


def test_nested_path_set(layout):
    set_value(layout, "retention.logs_keep_days", 7)
    assert load_yaml(layout.config_path, Config).retention.logs_keep_days == 7


def test_unknown_path_raises(layout):
    with pytest.raises(ValueError):
        set_value(layout, "voice.nonexistent", 1)
    with pytest.raises(KeyError):
        get_value(layout, "voice.nonexistent")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
