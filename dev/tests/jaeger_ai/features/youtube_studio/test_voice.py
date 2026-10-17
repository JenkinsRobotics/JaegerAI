from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from jaeger_ai.features.youtube_studio import voice

SCRIPT = """# Ep
## Shot list
| 1 | HOST: not narration | AI HOST | |
## Narration
HOST: Welcome to the garage workshop.
**ROBOT:** Power is nominal.
- HOST: Let's build.

## Open questions for Matthew
HOST: ignored
"""


def test_narration_lines_only_from_narration_section() -> None:
    assert voice.narration_lines(SCRIPT) == [
        voice.Line("HOST", "Welcome to the garage workshop."),
        voice.Line("ROBOT", "Power is nominal."),
        voice.Line("HOST", "Let's build."),
    ]


class _FakeEngine:
    def __init__(self, voice_id: str, used: list):
        self.voice = voice_id
        used.append(voice_id)

    def render(self, text: str):
        return np.full(int(0.5 * voice.SAMPLE_RATE), 0.1, dtype=np.float32)


def test_render_uses_two_voices_and_writes_wav_and_cues(tmp_path: Path) -> None:
    used: list = []
    out = tmp_path / "n.wav"
    cues = voice.render_narration(voice.narration_lines(SCRIPT), out,
                                  host_voice="am_adam", robot_voice="bm_george",
                                  engine_factory=lambda v: _FakeEngine(v, used))
    assert used == ["am_adam", "bm_george"]          # one engine per voice, reused
    with wave.open(str(out)) as handle:
        assert handle.getframerate() == 24_000
        assert handle.getnframes() == pytest.approx(3 * (0.5 + voice.GAP_S) * 24_000, abs=3)
    assert [c.speaker for c in cues] == ["HOST", "ROBOT", "HOST"]
    assert cues[1].start_s == pytest.approx(0.5 + voice.GAP_S)
    saved = json.loads(out.with_suffix(".cues.json").read_text())
    assert saved[2]["text"] == "Let's build."


def test_no_lines_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        voice.render_narration([], tmp_path / "x.wav", engine_factory=lambda v: None)
