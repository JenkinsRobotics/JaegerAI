from unittest.mock import Mock

from jaeger_kokoro_tts.nodes.kokoro_tts.engine import KokoroTTS
from jaeger_whisper_stt.nodes.whisper_stt.engine.local_agreement.pipeline import WhisperSTTLocalAgreement


def test_kokoro_receives_config_and_environment_override(monkeypatch):
    monkeypatch.delenv('JAEGER_AUDIO_BACKEND', raising=False)
    assert KokoroTTS(audio_backend='avaudio')._resolve_backend() == 'avaudio'
    monkeypatch.setenv('JAEGER_AUDIO_BACKEND', 'sounddevice')
    assert KokoroTTS(audio_backend='avaudio')._resolve_backend() == 'sounddevice'


def test_local_agreement_waits_for_two_decodes_and_resets():
    engine = WhisperSTTLocalAgreement.__new__(WhisperSTTLocalAgreement)
    engine._reset_agreement()
    engine._in_speech = True
    engine._current_phrase_audio = Mock(return_value=object())
    engine._transcribe = Mock(side_effect=['hello world', 'hello there', 'hello there friend'])
    captions = []
    engine.set_on_partial(captions.append)
    engine._rolling_transcribe()
    assert captions == []
    engine._rolling_transcribe()
    assert captions == ['hello']
    engine._rolling_transcribe()
    assert captions == ['hello', 'hello there']
    engine._reset_agreement()
    assert engine._stable_text == engine._previous_hypothesis == ''


def test_playback_amplitude_tracks_pcm_and_underrun():
    import numpy as np
    from jaeger_kokoro_tts.nodes.kokoro_tts.persistent_player import PersistentKokoroPlayer

    player = PersistentKokoroPlayer()
    player.enqueue(np.full(4, 0.5, dtype=np.float32))
    output = np.empty((4, 1), dtype=np.float32)
    player._cb(output, 4, None, None)
    assert player.amplitude == 0.5
    player._cb(output, 4, None, None)
    assert player.amplitude == 0.0
    player.reset()
    assert player.amplitude == 0.0


def test_webui_url_tracks_reassigned_container_ip(monkeypatch):
    import json
    import subprocess
    from jaeger_ai.features.hermes_webui import service

    ui = service.HermesWebUIService.__new__(service.HermesWebUIService)
    ui.webui_port = 8787
    ui.enabled = True
    ui.container_name = "configured-webui"
    ui._cfg = {"engine": "/configured/container"}
    monkeypatch.setattr(service.shutil, 'which', lambda _: '/usr/bin/container')
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps([{'status': {'state': 'running', 'networks': [{'ipv4Address': '192.168.64.99/24'}]}}])))
    assert ui.browser_url() == 'http://192.168.64.99:8787/'


def test_tray_global_lifecycle_does_not_pass_unsupported_instance(monkeypatch):
    from jaeger_ai.interfaces.pyside6.tray import macos
    calls = []
    monkeypatch.setattr(macos, '_jaeger_executable', lambda: ['jaeger'])
    monkeypatch.setattr(macos, '_spawn', lambda args: calls.append(args))
    actions = macos._make_actions('lilith')
    actions.start()
    actions.stop()
    actions.restart()
    actions.open_gui()
    assert calls == [['jaeger', 'start'], ['jaeger', 'stop'], ['jaeger', 'restart'], ['jaeger', 'start']]


def test_accessibility_backend_uses_framework_dependency_resolver(monkeypatch):
    import sys
    from types import SimpleNamespace
    from jaeger_agent.util import lazy_deps
    from jaeger_agent.skills.macos_computer_v1.engines import _ax_lowlevel

    ensured = []
    monkeypatch.setattr(lazy_deps, 'ensure', ensured.append)
    monkeypatch.setitem(sys.modules, 'ApplicationServices', SimpleNamespace(AXIsProcessTrusted=lambda: True))
    ready, detail = _ax_lowlevel.is_available()
    assert ready, detail
    assert ensured == ['macos.background']
