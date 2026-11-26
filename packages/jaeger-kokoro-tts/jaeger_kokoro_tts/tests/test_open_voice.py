"""The ``tts`` slot's direct call: a caller that plays the audio itself
(Jaeger Agent's voice loop) asks for chunks, and no device is opened."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import jaeger_kokoro_tts
from jaeger_kokoro_tts import engine as eng


def _voice(pipe):
    tts = eng.KokoroTTS()
    tts._pipeline = pipe
    return tts


def test_synth_hands_over_each_chunk_as_it_renders():
    rendered = []

    def pipe(text, voice, speed):
        for n in (3, None, 2):
            rendered.append((text, n))
            yield SimpleNamespace(audio=None if n is None else np.ones(n))

    tts = _voice(pipe)
    stream = tts.synth("**hi** there")
    first = next(stream)
    assert rendered == [("hi there", 3)]            # cleaned text; nothing rendered ahead
    assert first.dtype == np.float32 and first.shape == (3,)
    assert [len(c) for c in stream] == [2]          # the empty result is dropped
    assert tts._player is None                      # no audio device was opened
    assert tts.sample_rate == 24000


def test_synth_keeps_ssml_pauses_and_says_nothing_for_nothing():
    tts = _voice(lambda text, voice, speed: iter([SimpleNamespace(audio=np.ones(4))]))
    chunks = list(tts.synth('one <break time="100ms"/> two'))
    assert [len(c) for c in chunks] == [4, 2400, 4]
    assert not chunks[1].any()
    assert list(tts.synth("``` ```")) == []


def test_synth_takes_a_voice_and_a_rate_for_one_line():
    asked = []

    def pipe(text, voice, speed):
        asked.append((voice, speed))
        yield SimpleNamespace(audio=np.ones(2))

    tts = _voice(pipe)
    list(tts.synth("hi"))
    list(tts.synth("hi", voice="bf_emma", rate=1.2))
    list(tts.synth("hi"))
    assert asked == [("af_heart", 1.0), ("bf_emma", 1.2), ("af_heart", 1.0)]   # that line only


def test_each_chunk_carries_its_lip_marks():
    def pipe(text, voice, speed):
        yield SimpleNamespace(audio=np.ones(4), marks=[[0.025, 0.075, "p"]])
        yield SimpleNamespace(audio=np.ones(2))     # a backend with no timings: the same sound, no marks

    first, second = _voice(pipe).synth("mom")
    assert [list(first.marks), list(second.marks)] == [[[0.025, 0.075, "p"]], []]
    assert isinstance(first, np.ndarray) and first.dtype == np.float32   # still plain sound to every caller
    assert not len(first[2:].marks)                 # a cut-down copy does not keep marks timed for the whole


def test_a_backend_that_gives_phoneme_timings_gets_lip_marks():
    """PyTorch Kokoro hands back phonemes and their lengths, not marks."""
    def pipe(text, voice, speed):
        yield SimpleNamespace(audio=np.ones(4), phonemes="mˈɑ?f", pred_dur=np.array([4, 2, 1, 3, 2, 4]))
    pipe.model = SimpleNamespace(vocab={"m": 1, "ˈ": 2, "ɑ": 3, "f": 4})

    (chunk,) = _voice(pipe).synth("mom")
    assert chunk.marks == [[0.025, 0.075, "p"], [0.175, 0.225, "f"]]


def _padded(quiet=0.0):
    """0.3 s of dead air, 0.5 s of voice, 0.5 s of dead air — the shape of a Kokoro clip."""
    return np.concatenate([np.full(7200, quiet), np.full(12000, 0.5), np.full(12000, quiet)])


def test_dead_air_around_the_voice_is_cut_and_the_lip_marks_move_with_it():
    """Kokoro pads every clip (measured 2026-11-11 in Jaeger Avatar: 0.28-0.43 s
    before the voice, 0.49 s after). Played as made, that is a wait before
    every sentence. 12 ms is kept before the voice and 90 ms after, as
    Jaeger Avatar's own voice code does."""
    def pipe(text, voice, speed):
        yield SimpleNamespace(audio=_padded(), marks=[[0.1, 0.2, "p"], [0.25, 0.31, "p"], [0.5, 0.55, "f"]])

    (chunk,) = _voice(pipe).synth("mom")
    assert len(chunk) == 288 + 12000 + 2160
    assert (chunk[287], chunk[288], chunk[12287], chunk[12288]) == (0, 0.5, 0.5, 0)
    # a mark that ended in the cut air is gone; one the cut runs through starts at the clip's start
    assert chunk.marks == [[0.0, 0.022, "p"], [0.212, 0.262, "f"]]


def test_a_cut_edge_fades_so_it_does_not_click_and_uncut_sound_is_untouched():
    hiss = _voice(lambda text, voice, speed: iter([SimpleNamespace(audio=_padded(quiet=0.004))]))
    (chunk,) = hiss.synth("mom")
    assert chunk[0] == 0 and chunk[-1] == 0                 # 6 ms up from nothing, 6 ms down to nothing
    assert abs(chunk[200] - 0.004) < 1e-6 and chunk[288] == 0.5

    whole = np.full(1000, 0.5)
    for sound in (whole, np.zeros(1000)):                   # voice from edge to edge, or no voice at all: nothing to cut
        (chunk,) = _voice(lambda text, voice, speed: iter([SimpleNamespace(audio=sound)])).synth("mom")
        np.testing.assert_array_equal(chunk, sound.astype(np.float32))


def test_the_cut_is_a_setting_a_robot_can_change_or_turn_off():
    tts = _voice(lambda text, voice, speed: iter([SimpleNamespace(audio=_padded())]))
    tts.trim = (0.05, 0.2)                                  # a speaker that swallows the first milliseconds wants more lead
    assert len(next(tts.synth("mom"))) == 1200 + 12000 + 4800
    tts.trim = None                                         # Kokoro's own padding, as before
    assert len(next(tts.synth("mom"))) == 31200


def test_what_is_played_on_a_device_is_the_same_sound_as_synth():
    class Player:
        def __init__(self): self.heard = []
        def begin(self, correlation_id): pass
        def enqueue(self, audio): self.heard.append(np.asarray(audio).copy())
        def finish(self): pass
        def wait_until_drained(self, *a, **k): return True
        def __getattr__(self, name): return lambda *a, **k: True

    tts = _voice(lambda text, voice, speed: iter([SimpleNamespace(audio=_padded())]))
    player = Player()
    tts._ensure_player = lambda: player
    tts._player = player
    tts.speak("mom")
    np.testing.assert_array_equal(np.concatenate(player.heard), np.concatenate(list(tts.synth("mom"))))


def test_render_is_the_same_audio_as_synth_joined():
    tts = _voice(lambda text, voice, speed: iter(
        [SimpleNamespace(audio=np.full(3, 0.5)), SimpleNamespace(audio=np.full(2, -0.5))]))
    np.testing.assert_array_equal(tts.render("hello"), np.concatenate(list(tts.synth("hello"))))


def test_open_voice_returns_a_loaded_primed_voice(monkeypatch):
    said = []

    def pipe(text, voice, speed):
        said.append((text, voice))
        yield SimpleNamespace(audio=np.ones(1))

    monkeypatch.setattr(eng.KokoroTTS, "_ensure_pipeline", lambda self: pipe)
    tts = jaeger_kokoro_tts.open_voice(voice="bf_emma", language="b")
    assert (tts.voice, tts.lang) == ("bf_emma", "b")
    assert said == [("ready", "bf_emma")]           # primed once, so the first real line is fast
    assert tts._player is None
    assert callable(tts.synth) and hasattr(tts, "compute")
