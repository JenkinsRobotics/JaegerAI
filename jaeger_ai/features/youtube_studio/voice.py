"""Narration: the script's ``## Narration`` lines -> one WAV with Kokoro.

``HOST:`` lines use the host voice, ``ROBOT:`` lines the robot voice. A cue
sheet (JSON, one entry per line with start/end seconds) is written next to the
WAV so a later face or robot-motion step can sync to the same clock.
"""

from __future__ import annotations

import json
import re
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

SAMPLE_RATE = 24_000          # Kokoro's native rate (jaeger_kokoro_tts.engine)
DEFAULT_HOST_VOICE = "am_adam"
DEFAULT_ROBOT_VOICE = "bm_george"
GAP_S = 0.35

_SPEAKER = re.compile(r"^\s*(?:[-*]\s*)?\**\s*(HOST|ROBOT)\s*\**\s*:\s*\**\s*(.+)$", re.I)


@dataclass(frozen=True)
class Line:
    speaker: str
    text: str


@dataclass(frozen=True)
class Cue:
    index: int
    speaker: str
    text: str
    start_s: float
    end_s: float


def narration_lines(script_md: str) -> list[Line]:
    """``HOST:``/``ROBOT:`` lines under ``## Narration`` (whole doc if absent)."""
    body = script_md
    match = re.search(r"^##\s*Narration\b.*?$(.*?)(?=^##\s|\Z)", script_md, re.M | re.S | re.I)
    if match:
        body = match.group(1)
    lines = []
    for raw in body.splitlines():
        m = _SPEAKER.match(raw)
        if m:
            text = m.group(2).strip().strip("*").strip()
            if text:
                lines.append(Line(m.group(1).upper(), text))
    return lines


def render_narration(lines: list[Line], out_wav: Path, *,
                     host_voice: str = DEFAULT_HOST_VOICE,
                     robot_voice: str = DEFAULT_ROBOT_VOICE,
                     engine_factory=None) -> list[Cue]:
    """Render every line, join with short gaps, write a 16-bit mono WAV."""
    import numpy as np

    if not lines:
        raise ValueError("no HOST:/ROBOT: narration lines found")
    if engine_factory is None:
        from jaeger_kokoro_tts.engine import KokoroTTS

        def engine_factory(voice):
            return KokoroTTS(voice=voice, lang=voice[:1] or "a")
    voices = {"HOST": host_voice, "ROBOT": robot_voice}
    engines: dict[str, object] = {}
    gap = np.zeros(int(GAP_S * SAMPLE_RATE), dtype=np.float32)
    chunks, cues, cursor = [], [], 0
    for index, line in enumerate(lines, 1):
        voice = voices.get(line.speaker, host_voice)
        if voice not in engines:      # load each Kokoro voice once
            engines[voice] = engine_factory(voice)
        engine = engines[voice]
        audio = engine.render(line.text)
        if audio is None or len(audio) == 0:
            continue
        audio = np.asarray(audio, dtype=np.float32)
        start = cursor
        chunks += [audio, gap]
        cursor += len(audio) + len(gap)
        cues.append(Cue(index, line.speaker, line.text,
                        round(start / SAMPLE_RATE, 3),
                        round((start + len(audio)) / SAMPLE_RATE, 3)))
    if not chunks:
        raise RuntimeError("Kokoro rendered no audio")
    pcm = (np.clip(np.concatenate(chunks), -1.0, 1.0) * 32767).astype(np.int16)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    out_wav.with_suffix(".cues.json").write_text(
        json.dumps([asdict(c) for c in cues], indent=2) + "\n", encoding="utf-8")
    return cues
