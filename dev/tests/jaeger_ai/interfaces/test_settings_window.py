"""Settings window — config round-trip.

The window edits the instance's ``identity.yaml`` + ``config.yaml`` through
the schema. Pin that a save persists the edited fields, re-validates, and
preserves fields the UI doesn't expose (no silent clobber of the rest of
the config).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import (
    Config,
    Identity,
    ModelConfig,
    dump_yaml,
    load_yaml,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def instance(tmp_path):
    """A minimal valid instance on disk (identity + config)."""
    lay = InstanceLayout(root=tmp_path)
    dump_yaml(lay.identity_path,
              Identity(name="Tester", role="helper", personality="curious"))
    dump_yaml(lay.config_path,
              Config(instance_name="tester",
                     model=ModelConfig(model_path="/models/keep-me.gguf")))
    return lay


def test_settings_round_trip_persists_and_preserves(qapp, instance):
    from jaeger_ai.interfaces.pyside6.settings.window import SettingsWindow

    win = SettingsWindow(layout=instance)
    try:
        # Edit across three files/sections.
        win.name_edit.setText("Renamed")
        win.max_tokens_spin.setValue(2048)
        win.permissions_combo.setCurrentText("allow")
        win.voice_enabled.setChecked(True)

        err = win._persist()          # no modal — logic only
        assert err is None, err

        cfg = load_yaml(instance.config_path, Config)
        ident = load_yaml(instance.identity_path, Identity)
        assert ident.name == "Renamed"
        assert cfg.model.max_tokens == 2048
        assert cfg.permissions.mode == "allow"
        assert cfg.voice.enabled is True
        # Field the UI never touched survives the round-trip.
        assert str(cfg.model.model_path) == "/models/keep-me.gguf"
    finally:
        win.close()


def test_settings_rejects_invalid_without_writing(qapp, instance):
    from jaeger_ai.interfaces.pyside6.settings.window import SettingsWindow

    win = SettingsWindow(layout=instance)
    try:
        # A 100-char name violates Identity's 1–64 constraint.
        win.name_edit.setText("x" * 100)
        err = win._persist()
        assert err is not None                      # rejected
        # Disk still has the original name — nothing was written.
        ident = load_yaml(instance.identity_path, Identity)
        assert ident.name == "Tester"
    finally:
        win.close()
