"""Exercise the host output adapter across native and engine-owned turns."""
from types import SimpleNamespace

import pytest

from jaeger_ai import main
from jaeger_agent.core.outputs import multimodal_output_scope, multimodal_output_active


@pytest.mark.parametrize('modality,reply,speech', [
    ('text', '[OUTPUT:TEXT] Hello', ''),
    ('text', '[OUTPUT:SPEECH] Hello', 'Hello'),
    ('speech', '[OUTPUT:BOTH] Hello', 'Hello'),
    ('speech', 'Hello', 'Hello'),
])
def test_native_output_routes_once_with_original_media(monkeypatch, modality, reply, speech):
    media = [{'type': 'text', 'text': 'Describe'},
             {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}}]
    calls = []
    def run(client, text, **kwargs):
        assert multimodal_output_active()
        assert kwargs['content'][1:] == media
        assert '[OUTPUT:SPEECH]' in kwargs['system_prompt_addon']
        calls.append(text)
        return dict(text=reply, tool_activity=[], spoke_via_tool=False, elapsed_s=0,
                    skipped_final=False, error=None)
    monkeypatch.setattr(main, '_run_turn', run)
    monkeypatch.setattr('jaeger_ai.core.sessions.get_store', lambda: None)
    out = main.run_for_voice(None, 'Describe', content=media,
                             input_modality=modality, output_mode='dynamic')
    assert out['text'] == 'Hello'
    assert out['speech_text'] == speech
    assert calls == [f'[input: {modality}]\nDescribe']
    assert len(media) == 2
    assert not multimodal_output_active()


def test_attached_engine_receives_raw_choice_for_its_own_playback(monkeypatch):
    def run(client, text, **kwargs):
        assert text == 'Original prompt'
        return dict(text='[OUTPUT:SPEECH] Hello', tool_activity=[], spoke_via_tool=False,
                    elapsed_s=0, skipped_final=False, error=None)
    monkeypatch.setattr(main, '_run_turn', run)
    monkeypatch.setattr('jaeger_ai.core.sessions.get_store', lambda: None)
    with multimodal_output_scope():
        out = main.run_for_voice(None, 'Original prompt', output_mode='dynamic')
    assert out['text'] == '[OUTPUT:SPEECH] Hello'
    assert 'speech_text' not in out
