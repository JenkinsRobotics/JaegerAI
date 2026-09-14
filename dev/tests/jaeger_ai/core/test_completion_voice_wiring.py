from unittest.mock import Mock

from jaeger_kokoro_tts.engine import KokoroTTS
from jaeger_whisper_stt.engine.local_agreement.pipeline import WhisperSTTLocalAgreement


def test_kokoro_receives_config_and_environment_override(monkeypatch):
    monkeypatch.delenv('JAEGER_AUDIO_BACKEND', raising=False)
    assert KokoroTTS(audio_backend='avaudio')._resolve_backend() == 'avaudio'
    monkeypatch.setenv('JAEGER_AUDIO_BACKEND', 'sounddevice')
    assert KokoroTTS(audio_backend='avaudio')._resolve_backend() == 'sounddevice'


def test_local_agreement_waits_for_two_decodes_and_keeps_a_cursor():
    """The shared streaming engine commits only agreed words, once."""
    from collections import deque
    engine = WhisperSTTLocalAgreement.__new__(WhisperSTTLocalAgreement)
    engine.commit = "agreement"
    engine._committed_words = deque(maxlen=200)
    engine._prev_tail = []
    engine._no_anchor = 0
    engine._resync_after_passes = 4
    engine.min_overlap_words = 1
    engine.min_commit_words = 1
    engine.max_commit_words = 28
    engine._emit_partial = Mock()
    engine._commit = Mock()
    engine._commit_from("hello world", 1.0)
    engine._commit.assert_not_called()
    engine._commit_from("hello there", 2.0)
    engine._commit.assert_called_once_with("hello", 2.0)
    engine._commit_from("hello there friend", 3.0)
    assert [call.args[0] for call in engine._commit.call_args_list] == ["hello", "there"]
    assert list(engine._committed_words) == ["hello", "there"]



def test_playback_amplitude_tracks_pcm_and_underrun():
    import numpy as np
    from jaeger_kokoro_tts.persistent_player import PersistentKokoroPlayer

    player = PersistentKokoroPlayer()
    player.enqueue(np.full(4, 0.5, dtype=np.float32))
    output = np.empty((4, 1), dtype=np.float32)
    player._cb(output, 4, None, None)
    assert player.amplitude == 0.5
    player._cb(output, 4, None, None)
    assert player.amplitude == 0.0
    player.reset()
    assert player.amplitude == 0.0


def test_webui_url_ignores_obsolete_container_runtime(monkeypatch):
    from jaeger_ai.features.webui.service import service

    ui = service.WebUIService.__new__(service.WebUIService)
    ui.webui_port = 8790
    ui.adapter_port = 8791
    ui.adapter_host = "127.0.0.1"
    monkeypatch.setattr(service, '_tailscale_ipv4', lambda: None)
    assert ui.browser_url() == 'http://127.0.0.1:8790/'


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
