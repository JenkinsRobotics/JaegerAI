"""``jaeger settings`` CLI verb — list / groups / get / set, all driving the
ONE schema-derived catalog (``core/settings/catalog.py``). Terminal-first:
the same backend the Swift app reaches over the bridge.
"""

from __future__ import annotations

import pytest

from jaeger_ai.cli.verbs.settings_verb import _cmd_settings_argv
from jaeger_ai.core.instance.schemas import (
    Config, Identity, Manifest, ModelConfig, dump_json, dump_yaml, load_yaml)


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    """A schema-valid instance on disk, made the resolver's default."""
    root = tmp_path / "inst"
    root.mkdir()
    dump_yaml(root / "config.yaml",
              Config(instance_name="t", model=ModelConfig(model_path="/dev/null")))
    dump_yaml(root / "identity.yaml",
              Identity(name="T", role="r", personality="p"))
    dump_json(root / "manifest.json", Manifest(instance_name="t"))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(root))
    return root


def test_groups_lists_the_eight_pages(instance, capsys):
    assert _cmd_settings_argv(["groups"]) == 0
    out = capsys.readouterr().out
    for g in ("model", "display", "voice", "tts", "autonomy",
              "permissions", "retention", "interaction"):
        assert g in out


def test_list_and_group_filter(instance, capsys):
    assert _cmd_settings_argv(["list", "--group", "tts"]) == 0
    out = capsys.readouterr().out
    assert "voice.speech_engine" in out
    assert "voice.speak_replies" not in out   # different group


def test_get_shows_detail(instance, capsys):
    assert _cmd_settings_argv(["get", "voice.speak_replies"]) == 0
    out = capsys.readouterr().out
    assert "voice.speak_replies" in out
    assert "bool" in out


def test_get_unknown_path_errors(instance):
    assert _cmd_settings_argv(["get", "voice.nope"]) == 1


def test_set_persists_through_catalog(instance):
    assert _cmd_settings_argv(["set", "voice.speak_replies", "false"]) == 0
    cfg = load_yaml(instance / "config.yaml", Config)
    assert cfg.voice.speak_replies is False


def test_set_invalid_value_errors_without_writing(instance):
    assert _cmd_settings_argv(["set", "model.ctx", "999999"]) == 1
    assert load_yaml(instance / "config.yaml", Config).model.ctx == 8192


def test_set_restart_setting_notes_restart(instance, capsys):
    assert _cmd_settings_argv(["set", "model.ctx", "16384"]) == 0
    assert "restart" in capsys.readouterr().out.lower()


def test_advanced_hidden_by_default(instance, capsys):
    _cmd_settings_argv(["list", "--group", "voice"])
    assert "self_speech_threshold" not in capsys.readouterr().out
    _cmd_settings_argv(["list", "--group", "voice", "--advanced"])
    assert "self_speech_threshold" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
