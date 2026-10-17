"""Rough cut: build footage -> dead air trimmed, transcribed, captioned.

1. ``ffmpeg -af silencedetect`` finds the quiet stretches.
2. The loud stretches (plus a little padding) are kept and joined with
   ``trim``/``atrim`` + ``concat`` in one ffmpeg pass.
3. The CUT is transcribed with the offline Whisper module, so caption times
   match the cut, not the raw footage.
4. Captions are written as SRT/VTT/TXT/JSON and muxed into the MP4 as a soft
   ``mov_text`` track. (Burned-in captions need an ffmpeg built with libass;
   the Homebrew ffmpeg on this Mac has no ``subtitles`` filter.)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


@dataclass
class RoughCut:
    source: Path
    cut: Path
    captioned: Path
    captions: tuple[Path, ...]
    kept: list[tuple[float, float]]
    source_s: float
    cut_s: float
    transcript: str = ""
    extra: dict = field(default_factory=dict)


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"{tool} is not installed (brew install ffmpeg)")
    return path


def probe(path: Path) -> dict:
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    return {"duration": float(data["format"]["duration"]),
            "has_video": "video" in kinds, "has_audio": "audio" in kinds}


def parse_silences(stderr: str, duration: float) -> list[tuple[float, float]]:
    """``silencedetect`` log -> [(start, end)], closing a trailing open silence."""
    silences, start = [], None
    for line in stderr.splitlines():
        if (m := _SILENCE_START.search(line)):
            start = max(0.0, float(m.group(1)))
        elif (m := _SILENCE_END.search(line)) and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, duration))
    return silences


def detect_silences(path: Path, *, noise_db: float = -35.0,
                    min_silence_s: float = 0.8) -> list[tuple[float, float]]:
    info = probe(path)
    if not info["has_audio"]:
        return []
    proc = subprocess.run(
        [_require("ffmpeg"), "-nostdin", "-hide_banner", "-i", str(path), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    return parse_silences(proc.stderr, info["duration"])


def keep_intervals(silences: list[tuple[float, float]], duration: float, *,
                   pad_s: float = 0.2, min_keep_s: float = 0.3
                   ) -> list[tuple[float, float]]:
    """Complement of the silences, padded so words aren't clipped."""
    keep, cursor = [], 0.0
    for s_start, s_end in sorted(silences):
        a, b = cursor, min(duration, s_start + pad_s)
        if b - a >= min_keep_s:
            keep.append((round(max(0.0, a), 3), round(b, 3)))
        cursor = max(cursor, s_end - pad_s)
    if duration - cursor >= min_keep_s:
        keep.append((round(max(0.0, cursor), 3), round(duration, 3)))
    merged: list[tuple[float, float]] = []
    for a, b in keep:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def concat_filter(intervals: list[tuple[float, float]], *, video: bool = True) -> str:
    parts, labels = [], []
    for i, (a, b) in enumerate(intervals):
        if video:
            parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
            labels.append(f"[v{i}]")
        parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    v = 1 if video else 0
    parts.append("".join(labels) + f"concat=n={len(intervals)}:v={v}:a=1"
                 + ("[outv][outa]" if video else "[outa]"))
    return ";".join(parts)


def cut_video(src: Path, intervals: list[tuple[float, float]], out: Path, *,
              threads: int = 4) -> Path:
    if not intervals:
        raise ValueError("nothing left after silence trimming")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_require("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(src),
           "-filter_complex", concat_filter(intervals), "-map", "[outv]", "-map", "[outa]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-threads", str(threads),
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out


def mux_captions(video: Path, srt: Path, out: Path) -> Path:
    subprocess.run(
        [_require("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(video),
         "-i", str(srt), "-map", "0:v", "-map", "0:a", "-map", "1:0",
         "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
         "-metadata:s:s:0", "language=eng", str(out)], check=True)
    return out


def make_roughcut(src: Path, out_dir: Path, *, whisper_model: str = "base.en",
                  noise_db: float = -35.0, min_silence_s: float = 0.8,
                  pad_s: float = 0.2, threads: int = 4,
                  transcriber=None) -> RoughCut:
    src = Path(src).expanduser().resolve()
    out_dir = Path(out_dir).expanduser()
    info = probe(src)
    if not (info["has_video"] and info["has_audio"]):
        raise ValueError(f"{src} needs both a video and an audio stream")
    silences = detect_silences(src, noise_db=noise_db, min_silence_s=min_silence_s)
    kept = keep_intervals(silences, info["duration"], pad_s=pad_s)
    stem = src.stem
    cut = cut_video(src, kept, out_dir / f"{stem}.cut.mp4", threads=threads)

    from jaeger_whisper_stt.offline import OfflineTranscriber, write_transcripts

    transcriber = transcriber or OfflineTranscriber(whisper_model, n_threads=threads)
    result = transcriber.transcribe(cut)
    captions = write_transcripts(result, out_dir / f"{stem}-cut",
                                 ("srt", "vtt", "txt", "json"))
    srt = next(p for p in captions if p.suffix == ".srt")
    captioned = mux_captions(cut, srt, out_dir / f"{stem}.roughcut.mp4")
    cut_s = probe(captioned)["duration"]
    edl = {"source": str(src), "source_s": info["duration"], "cut_s": cut_s,
           "removed_s": round(info["duration"] - cut_s, 3),
           "silences": silences, "kept": kept,
           "settings": {"noise_db": noise_db, "min_silence_s": min_silence_s,
                        "pad_s": pad_s, "whisper_model": whisper_model}}
    (out_dir / f"{stem}.edl.json").write_text(json.dumps(edl, indent=2) + "\n")
    return RoughCut(src, cut, captioned, captions, kept, info["duration"], cut_s,
                    transcript=result.text, extra=edl)
