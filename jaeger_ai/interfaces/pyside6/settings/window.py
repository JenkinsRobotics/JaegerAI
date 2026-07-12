"""Settings — the operator-facing preferences window.

A tabbed editor over the instance's ``identity.yaml`` + ``config.yaml``
(the same files the wizard / ``jaeger config`` write). Loads the live
config, exposes the end-user-facing knobs grouped into tabs, and writes
back via the schema's ``dump_yaml`` — re-validating through Pydantic so a
bad value is rejected with a message, never persisted.

Scope: the high-traffic settings an operator actually changes (agent
identity, model/engine, voice, behaviour, permissions). The full
~100-field schema is reachable via ``jaeger config`` / YAML; this surfaces
the ones worth a GUI. Model/engine changes need an agent restart — the
footer says so.

GUI/logic separation: this is a thin Qt view; all the config *meaning*
lives in ``core.instance.schemas``. A Swift settings window would write
the same files through the same schema (via the bridge/CLI).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
from jaeger_ai.core.instance.schemas import (
    SCHEMA_VERSION,
    Config,
    Identity,
    dump_yaml,
    load_yaml,
)


class SettingsWindow(QWidget):
    """Tabbed preferences over the running instance's config files."""

    def __init__(self, layout: InstanceLayout | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout_ = layout or InstanceLayout(root=resolve_instance_dir())
        self._cfg: Config = load_yaml(self.layout_.config_path, Config)
        self._ident: Identity = load_yaml(self.layout_.identity_path, Identity)

        self.setWindowTitle("JROS — Settings")
        self.resize(560, 520)
        self._build_ui()
        self._load_values()

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(self._agent_tab(), "Agent")
        self.tabs.addTab(self._model_tab(), "Model & Engine")
        self.tabs.addTab(self._voice_tab(), "Voice")
        self.tabs.addTab(self._behavior_tab(), "Behavior")
        self.tabs.addTab(self._about_tab(), "About")

        note = QLabel("Model & engine changes take effect after restarting "
                      "the agent.")
        note.setStyleSheet("color: #888; padding: 2px 4px;")
        root.addWidget(note)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        root.addWidget(self.save_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _agent_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.name_edit = QLineEdit()
        self.role_edit = QLineEdit()
        self.personality_edit = QPlainTextEdit()
        self.personality_edit.setMaximumHeight(110)
        self.voice_tone_edit = QLineEdit()
        self.voice_id_edit = QLineEdit()
        self.voice_id_edit.setPlaceholderText("e.g. am_michael (blank = default)")
        f.addRow("Name", self.name_edit)
        f.addRow("Role", self.role_edit)
        f.addRow("Personality", self.personality_edit)
        f.addRow("Voice tone", self.voice_tone_edit)
        f.addRow("Voice ID", self.voice_id_edit)
        return w

    def _model_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["llama_cpp_python", "mlx_lm"])
        self.model_path_edit = QLineEdit()
        self.ctx_spin = _spin(512, 131072, 512)
        self.max_tokens_spin = _spin(16, 32768, 16)
        self.gguf_engine_combo = QComboBox()
        self.gguf_engine_combo.addItems(["auto", "llama-cpp-python"])
        self.mlx_engine_combo = QComboBox()
        self.mlx_engine_combo.addItems(["auto", "mlx-lm", "mlx-vlm"])
        self.idle_spin = _spin(0, 240, 1)
        f.addRow("Backend", self.backend_combo)
        f.addRow("Model path", self.model_path_edit)
        f.addRow("Context window", self.ctx_spin)
        f.addRow("Max tokens / turn", self.max_tokens_spin)
        f.addRow("GGUF engine", self.gguf_engine_combo)
        f.addRow("MLX engine", self.mlx_engine_combo)
        f.addRow("Deep-think auto-idle (min)", self.idle_spin)
        return w

    def _voice_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.voice_enabled = QCheckBox("Always-on mic from boot")
        self.wake_word = QCheckBox("Require wake phrase")
        self.follow_up = QCheckBox("Follow-up window after replies")
        self.barge_in = QCheckBox("Allow interrupting mid-sentence")
        self.audio_backend_combo = QComboBox()
        self.audio_backend_combo.addItems(["sounddevice", "avaudio"])
        self.warm_tts = QCheckBox("Pre-load TTS")
        self.warm_stt = QCheckBox("Pre-load STT")
        self.warm_vision = QCheckBox("Pre-load vision")
        f.addRow(self.voice_enabled)
        f.addRow(self.wake_word)
        f.addRow(self.follow_up)
        f.addRow(self.barge_in)
        f.addRow("Audio backend", self.audio_backend_combo)
        f.addRow("Warm at boot", self.warm_tts)
        f.addRow("", self.warm_stt)
        f.addRow("", self.warm_vision)
        return w

    def _behavior_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.show_latency = QCheckBox("Show per-turn latency")
        self.show_tool_activity = QCheckBox("Show tool activity")
        self.busy_mode_combo = QComboBox()
        self.busy_mode_combo.addItems(["interrupt", "queue", "steer"])
        self.default_mode_combo = QComboBox()
        self.default_mode_combo.addItems(["tui", "gui", "voice"])
        self.permissions_combo = QComboBox()
        self.permissions_combo.addItems(["confirm", "allow"])
        self.lazy_installs = QCheckBox("Auto-install optional backends on first use")
        f.addRow(self.show_latency)
        f.addRow(self.show_tool_activity)
        f.addRow("Enter while busy", self.busy_mode_combo)
        f.addRow("Default interface", self.default_mode_combo)
        f.addRow("Permission mode", self.permissions_combo)
        f.addRow(self.lazy_installs)
        return w

    def _about_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Instance", QLabel(self.layout_.root.name))
        f.addRow("Schema version", QLabel(SCHEMA_VERSION))
        f.addRow("Model", QLabel(str(self._cfg.model.model_path)))
        f.addRow("Backend", QLabel(self._cfg.model.backend))
        return w

    # ── load / save ───────────────────────────────────────────────
    def _load_values(self) -> None:
        i, c = self._ident, self._cfg
        self.name_edit.setText(i.name)
        self.role_edit.setText(i.role)
        self.personality_edit.setPlainText(i.personality)
        self.voice_tone_edit.setText(i.voice_tone)
        self.voice_id_edit.setText(i.voice_id or "")

        self.backend_combo.setCurrentText(c.model.backend)
        self.model_path_edit.setText(str(c.model.model_path))
        self.ctx_spin.setValue(c.model.ctx)
        self.max_tokens_spin.setValue(c.model.max_tokens)
        self.gguf_engine_combo.setCurrentText(c.runtime.gguf_engine)
        self.mlx_engine_combo.setCurrentText(c.runtime.mlx_engine)
        self.idle_spin.setValue(c.deep_think.auto_idle_minutes)

        self.voice_enabled.setChecked(c.voice.enabled)
        self.wake_word.setChecked(c.voice.wake_word)
        self.follow_up.setChecked(c.voice.follow_up)
        self.barge_in.setChecked(c.voice.barge_in)
        self.audio_backend_combo.setCurrentText(c.voice.audio_backend)
        self.warm_tts.setChecked(c.warmup.tts)
        self.warm_stt.setChecked(c.warmup.stt)
        self.warm_vision.setChecked(c.warmup.vision)

        self.show_latency.setChecked(c.display.show_latency)
        self.show_tool_activity.setChecked(c.display.show_tool_activity)
        self.busy_mode_combo.setCurrentText(c.display.busy_input_mode)
        self.default_mode_combo.setCurrentText(c.interaction.default_mode)
        self.permissions_combo.setCurrentText(c.permissions.mode)
        self.lazy_installs.setChecked(c.security.allow_lazy_installs)

    def _save(self) -> None:
        err = self._persist()
        if err:
            QMessageBox.warning(self, "Invalid setting", err)
        else:
            QMessageBox.information(
                self, "Saved",
                "Settings saved. Restart the agent for model/engine changes.")

    def _persist(self) -> str | None:
        """Apply the widgets to the config files. Returns an error string
        if a value is invalid (nothing written), else None."""
        # Reload fresh so fields this UI doesn't expose are preserved.
        ident = load_yaml(self.layout_.identity_path, Identity)
        cfg = load_yaml(self.layout_.config_path, Config)

        ident.name = self.name_edit.text().strip() or ident.name
        ident.role = self.role_edit.text().strip() or ident.role
        ident.personality = self.personality_edit.toPlainText().strip() or ident.personality
        ident.voice_tone = self.voice_tone_edit.text().strip() or "neutral"
        ident.voice_id = self.voice_id_edit.text().strip() or None

        cfg.model.backend = self.backend_combo.currentText()
        cfg.model.model_path = self.model_path_edit.text().strip()
        cfg.model.ctx = self.ctx_spin.value()
        cfg.model.max_tokens = self.max_tokens_spin.value()
        cfg.runtime.gguf_engine = self.gguf_engine_combo.currentText()
        cfg.runtime.mlx_engine = self.mlx_engine_combo.currentText()
        cfg.deep_think.auto_idle_minutes = self.idle_spin.value()

        cfg.voice.enabled = self.voice_enabled.isChecked()
        cfg.voice.wake_word = self.wake_word.isChecked()
        cfg.voice.follow_up = self.follow_up.isChecked()
        cfg.voice.barge_in = self.barge_in.isChecked()
        cfg.voice.audio_backend = self.audio_backend_combo.currentText()
        cfg.warmup.tts = self.warm_tts.isChecked()
        cfg.warmup.stt = self.warm_stt.isChecked()
        cfg.warmup.vision = self.warm_vision.isChecked()

        cfg.display.show_latency = self.show_latency.isChecked()
        cfg.display.show_tool_activity = self.show_tool_activity.isChecked()
        cfg.display.busy_input_mode = self.busy_mode_combo.currentText()
        cfg.interaction.default_mode = self.default_mode_combo.currentText()
        cfg.permissions.mode = self.permissions_combo.currentText()
        cfg.security.allow_lazy_installs = self.lazy_installs.isChecked()

        # Re-validate through Pydantic before writing — a bad value is
        # rejected with a message, never persisted to disk.
        try:
            ident = Identity.model_validate(ident.model_dump())
            cfg = Config.model_validate(cfg.model_dump())
        except Exception as exc:  # noqa: BLE001 — surface validation errors
            return str(exc)

        dump_yaml(self.layout_.identity_path, ident)
        dump_yaml(self.layout_.config_path, cfg)
        self._ident, self._cfg = ident, cfg
        return None


def _spin(lo: int, hi: int, step: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    return s


def open_settings(layout: Any = None) -> SettingsWindow:
    """Build + show the settings window (used by the tray gear)."""
    win = SettingsWindow(layout=layout)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
