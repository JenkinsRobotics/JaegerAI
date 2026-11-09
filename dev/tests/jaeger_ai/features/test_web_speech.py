import base64
import sys
import types
from pathlib import Path
from unittest.mock import Mock
import pytest
from jaeger_ai.features.voice import web_speech


def test_missing_model_never_downloads_or_constructs_engine(monkeypatch):
    monkeypatch.setattr(web_speech,'cached_model',lambda:None)
    monkeypatch.setattr(web_speech,'_transcriber',None)
    with pytest.raises(RuntimeError,match='no model was downloaded'):
        web_speech.transcribe_recording(base64.b64encode(b'audio').decode(),'audio/wav')
    assert web_speech._transcriber is None


@pytest.mark.parametrize('data,mime', [('','audio/wav'),('not base64!','audio/webm'),('YWJj','text/html')])
def test_invalid_audio_is_rejected_before_engine_load(monkeypatch,data,mime):
    model=Mock(side_effect=AssertionError('must not load'))
    monkeypatch.setattr(web_speech,'cached_model',model)
    with pytest.raises(ValueError):web_speech.transcribe_recording(data,mime)
    model.assert_not_called()


def test_reuses_canonical_decoder_and_removes_recordings(monkeypatch,tmp_path):
    model=tmp_path/'ggml-base.en.bin';model.write_bytes(b'cached')
    monkeypatch.setattr(web_speech,'cached_model',lambda:model)
    monkeypatch.setattr(web_speech,'_transcriber',None)
    seen=[]
    def decode(path):
        seen.append(Path(path));assert Path(path).read_bytes()==b'audio';return types.SimpleNamespace(text='  Hello Jaeger  ')
    engine=Mock();engine.transcribe.side_effect=decode
    module=types.ModuleType('jaeger_whisper_stt.offline');module.OfflineTranscriber=Mock(return_value=engine)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    for _ in range(2):assert web_speech.transcribe_recording('YXVkaW8=','audio/webm;codecs=opus')=='Hello Jaeger'
    module.OfflineTranscriber.assert_called_once_with(str(model),language='en')
    assert all(not path.exists() for path in seen)
