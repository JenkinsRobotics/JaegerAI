from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from jaeger_whisper_stt.offline import (
    TranscriptSegment, TranscriptionResult, write_transcripts,
)


def sample_result(tmp_path: Path) -> TranscriptionResult:
    return TranscriptionResult(
        source=tmp_path / "sample.wav",
        model="base.en",
        language="en",
        decode_s=0.25,
        audio_s=2.0,
        segments=(
            TranscriptSegment(0, 900, "Hello, robot.", 0.9),
            TranscriptSegment(1000, 2000, "Ready to work?", None),
        ),
    )


def test_result_text_and_rtf(tmp_path: Path) -> None:
    result = sample_result(tmp_path)
    assert result.text == "Hello, robot. Ready to work?"
    assert result.rtf == pytest.approx(0.125)


def test_all_export_formats_are_machine_readable(tmp_path: Path) -> None:
    result = sample_result(tmp_path)
    paths = write_transcripts(
        result, tmp_path / "out" / "sample",
        ("txt", "srt", "vtt", "csv", "json"),
    )
    assert {path.suffix for path in paths} == {
        ".txt", ".srt", ".vtt", ".csv", ".json",
    }
    assert paths[0].read_text().strip() == result.text
    assert "00:00:00,000 --> 00:00:00,900" in paths[1].read_text()
    assert paths[2].read_text().startswith("WEBVTT\n\n")
    with paths[3].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["text"] == "Ready to work?"
    assert json.loads(paths[4].read_text())["segments"][0]["start_ms"] == 0


def test_unknown_export_format_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported transcript format"):
        write_transcripts(sample_result(tmp_path), tmp_path / "out", ("docx",))


def _write_wav(path: Path, rate: int) -> Path:
    import wave
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * (rate // 10))
    return path


def test_kokoro_rate_wav_is_resampled_before_whisper(tmp_path: Path) -> None:
    """Kokoro writes 24 kHz WAV; pywhispercpp rejects any WAV not at 16 kHz."""
    import shutil
    import wave
    from jaeger_whisper_stt.offline import _whisper_ready_audio, wav_is_whisper_ready

    ready = _write_wav(tmp_path / "ready.wav", 16_000)
    kokoro = _write_wav(tmp_path / "kokoro.wav", 24_000)
    assert wav_is_whisper_ready(ready)
    assert not wav_is_whisper_ready(kokoro)
    assert wav_is_whisper_ready(tmp_path / "clip.mp4")  # pywhispercpp converts it
    with _whisper_ready_audio(ready) as same:
        assert same == ready
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    with _whisper_ready_audio(kokoro) as converted:
        assert converted != kokoro
        with wave.open(str(converted), "rb") as handle:
            assert handle.getframerate() == 16_000
    assert not converted.exists()  # temp copy is cleaned up
