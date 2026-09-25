"""Settings inline in jaeger.toml — so a small app is ONE file.

config.yaml predates the app format; nothing chose YAML for settings
and TOML for topology, the newer file just chose better. Two formats
for one app is a thing to learn twice, and the YAML half is the one
with no schema — so it is where `country: NO` silently becomes False.
"""

from __future__ import annotations

import pytest

from jaeger_os.app import JaegerApp, load_manifest

_BASE = '''
[app]
name = "inline-test"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
control = false
{config_line}

[bus]
backend = "inproc"
'''


def _write(tmp_path, *, config_line="", extra="", yaml_text=None):
    (tmp_path / "jaeger.toml").write_text(
        _BASE.format(config_line=config_line) + extra)
    if yaml_text is not None:
        (tmp_path / "config.yaml").write_text(yaml_text)
    return tmp_path


def test_settings_can_live_in_the_manifest(tmp_path):
    _write(tmp_path, config_line='config = ""', extra='''
[config.animation]
width = 256
height = 256

[config.player]
character = "emotes"
dwell_s = 1.5
''')
    spec = load_manifest(tmp_path)
    assert spec.inline_config["animation"]["width"] == 256
    assert spec.inline_config["player"]["character"] == "emotes"


def test_a_node_receives_its_inline_slice(tmp_path):
    _write(tmp_path, config_line='config = ""',
           extra='\n[config.animation]\nwidth = 320\n')
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        assert app.config["animation"]["width"] == 320
    finally:
        app.shutdown()


def test_toml_keeps_the_types_yaml_mangles(tmp_path):
    """The reason this is worth doing rather than just tidier. YAML
    reads `1.10` as the float 1.1 and `NO` as False; TOML has real
    types and does neither."""
    _write(tmp_path, config_line='config = ""', extra='''
[config.thing]
version = "1.10"
country = "NO"
enabled = "on"
''')
    cfg = load_manifest(tmp_path).inline_config["thing"]
    assert cfg["version"] == "1.10", "a digit went missing"
    assert cfg["country"] == "NO", "the Norway problem"
    assert cfg["enabled"] == "on"


# ── the ambiguity this must never create ─────────────────────────

def test_settings_in_both_places_is_refused(tmp_path):
    """"Which file is my setting in" is a question nobody should have
    to ask, and a silent precedence rule is how you spend an afternoon
    editing the copy that is not being read."""
    _write(tmp_path, extra='\n[config.a]\nx = 1\n', yaml_text="a:\n  x: 2\n")
    with pytest.raises(ValueError, match="BOTH"):
        load_manifest(tmp_path)


def test_the_refusal_says_how_to_fix_it(tmp_path):
    _write(tmp_path, extra='\n[config.a]\nx = 1\n', yaml_text="a:\n  x: 2\n")
    with pytest.raises(ValueError) as exc:
        load_manifest(tmp_path)
    assert 'config = ""' in str(exc.value)


def test_a_config_file_still_works_alone(tmp_path):
    """Existing apps must not move. JP01 has a config.yaml."""
    _write(tmp_path, yaml_text="animation:\n  width: 128\n")
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        assert app.config["animation"]["width"] == 128
    finally:
        app.shutdown()


def test_neither_is_fine(tmp_path):
    """An app with no tunables is normal."""
    _write(tmp_path, config_line='config = ""')
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        assert app.config == {}
    finally:
        app.shutdown()


def test_a_non_table_config_is_refused(tmp_path):
    _write(tmp_path, config_line='config = ""', extra='\nconfig = 5\n')
    with pytest.raises(ValueError):
        load_manifest(tmp_path)
