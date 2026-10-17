from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jaeger_ai.features.youtube_studio import roughcut

LOG = """[silencedetect @ 0x1] silence_start: 2.5
[silencedetect @ 0x1] silence_end: 6.0 | silence_duration: 3.5
[silencedetect @ 0x1] silence_start: 9.0
"""


def test_parse_silences_closes_trailing_silence() -> None:
    assert roughcut.parse_silences(LOG, 12.0) == [(2.5, 6.0), (9.0, 12.0)]


def test_keep_intervals_pads_and_drops_slivers() -> None:
    kept = roughcut.keep_intervals([(2.5, 6.0), (9.0, 12.0)], 12.0, pad_s=0.2)
    assert kept == [(0.0, 2.7), (5.8, 9.2)]
    # a silence that swallows everything leaves nothing
    assert roughcut.keep_intervals([(0.0, 5.0)], 5.0) == []
    # no silence keeps the whole clip
    assert roughcut.keep_intervals([], 4.0) == [(0.0, 4.0)]


def test_concat_filter_shape() -> None:
    f = roughcut.concat_filter([(0.0, 1.0), (2.0, 3.0)])
    assert "[0:v]trim=start=2.0:end=3.0,setpts=PTS-STARTPTS[v1]" in f
    assert f.endswith("[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]")


class _StubTranscriber:
    def transcribe(self, path):
        from jaeger_whisper_stt.offline import TranscriptionResult, TranscriptSegment
        return TranscriptionResult(Path(path), "stub", "en", 0.1, 2.0,
                                   (TranscriptSegment(0, 900, "tone one"),
                                    TranscriptSegment(1000, 1900, "tone two")))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_make_roughcut_trims_silence_and_muxes_captions(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    # 1 s tone, 3 s silence, 1 s tone, over a 5 s test pattern
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=5",
         "-f", "lavfi", "-i", "sine=f=440:d=1", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
         "-f", "lavfi", "-i", "sine=f=660:d=1",
         "-filter_complex", "[2:a]atrim=0:3[s];[1:a][s][3:a]concat=n=3:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-shortest", str(src)], check=True)
    result = roughcut.make_roughcut(src, tmp_path / "out", pad_s=0.1,
                                    transcriber=_StubTranscriber())
    assert len(result.kept) == 2
    assert 1.8 < result.cut_s < 3.0 < result.source_s
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
         "-of", "csv=p=0", str(result.captioned)], capture_output=True, text=True).stdout
    assert "mov_text,subtitle" in streams and "h264,video" in streams
    assert (tmp_path / "out" / "clip-cut.srt").read_text().count("-->") == 2
    assert (tmp_path / "out" / "clip.edl.json").exists()
