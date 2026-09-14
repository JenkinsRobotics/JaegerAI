"""Offline file transcription with the same Whisper runtime as live STT.

Realtime apps consume JaegerOS microphone frames through the engine registry.
Files do not need a bus or audio device, so this small public API loads the
same ``pywhispercpp`` backend directly and returns stable, serializable data.
One :class:`OfflineTranscriber` can process many files without reloading model
weights between files.
"""

from __future__ import annotations

import csv
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TranscriptSegment:
    """One timestamped piece of an offline transcript."""

    start_ms: int
    end_ms: int
    text: str
    probability: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    """Device-independent result returned by :meth:`transcribe`."""

    source: Path
    model: str
    language: str
    decode_s: float
    audio_s: float
    segments: tuple[TranscriptSegment, ...]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    @property
    def rtf(self) -> float:
        """Real-time factor; values below 1 are faster than playback."""
        return self.decode_s / max(self.audio_s, 1e-9)


class OfflineTranscriber:
    """Reusable Whisper model for files and recorded clips."""

    def __init__(
        self,
        model: str = "base.en",
        *,
        language: str = "en",
        n_threads: int | None = None,
        translate: bool = False,
    ) -> None:
        from pywhispercpp.model import Model

        params = {
            "language": language,
            "translate": translate,
            "single_segment": False,
            "no_context": True,
            "print_progress": False,
            "print_realtime": False,
            "print_timestamps": False,
        }
        if n_threads is not None:
            params["n_threads"] = n_threads
        self.model_name = model
        self.language = language
        self._model = Model(model, **params)

    def transcribe(self, source: str | Path) -> TranscriptionResult:
        """Transcribe any media path supported by ``pywhispercpp``/ffmpeg."""
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        started = time.perf_counter()
        raw_segments = self._model.transcribe(str(path), language=self.language)
        decode_s = time.perf_counter() - started
        segments = tuple(_convert_segment(s) for s in raw_segments)
        audio_s = max((s.end_ms for s in segments), default=0) / 1000.0
        return TranscriptionResult(
            source=path,
            model=self.model_name,
            language=self.language,
            decode_s=decode_s,
            audio_s=audio_s,
            segments=segments,
        )


def _convert_segment(segment) -> TranscriptSegment:
    probability = getattr(segment, "probability", None)
    if probability is not None and math.isnan(float(probability)):
        probability = None
    return TranscriptSegment(
        # whisper.cpp timestamps are centiseconds.
        start_ms=int(getattr(segment, "t0", 0)) * 10,
        end_ms=int(getattr(segment, "t1", 0)) * 10,
        text=str(getattr(segment, "text", "")).strip(),
        probability=None if probability is None else float(probability),
    )


def write_transcripts(
    result: TranscriptionResult,
    output_base: str | Path,
    formats: Iterable[str] = ("txt",),
) -> tuple[Path, ...]:
    """Write TXT, SRT, VTT, CSV, or JSON exports and return their paths."""
    base = Path(output_base).expanduser()
    base.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for raw_format in formats:
        fmt = raw_format.lower().lstrip(".")
        path = base.with_suffix(f".{fmt}")
        if fmt == "txt":
            path.write_text(result.text + "\n", encoding="utf-8")
        elif fmt == "srt":
            path.write_text(_subtitles(result.segments, vtt=False), encoding="utf-8")
        elif fmt == "vtt":
            path.write_text("WEBVTT\n\n" + _subtitles(
                result.segments, vtt=True), encoding="utf-8")
        elif fmt == "csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(("start_ms", "end_ms", "text", "probability"))
                for segment in result.segments:
                    writer.writerow((segment.start_ms, segment.end_ms,
                                     segment.text, segment.probability))
        elif fmt == "json":
            import json
            payload = {
                "source": str(result.source),
                "model": result.model,
                "language": result.language,
                "decode_s": result.decode_s,
                "audio_s": result.audio_s,
                "rtf": result.rtf,
                "text": result.text,
                "segments": [asdict(s) for s in result.segments],
            }
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        else:
            raise ValueError(
                f"unsupported transcript format {fmt!r}; "
                "choose txt, srt, vtt, csv, or json"
            )
        written.append(path.resolve())
    return tuple(written)


def _timestamp(milliseconds: int, *, vtt: bool) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _subtitles(segments: tuple[TranscriptSegment, ...], *, vtt: bool) -> str:
    blocks = []
    for index, segment in enumerate(segments, 1):
        times = (f"{_timestamp(segment.start_ms, vtt=vtt)} --> "
                 f"{_timestamp(segment.end_ms, vtt=vtt)}")
        prefix = "" if vtt else f"{index}\n"
        blocks.append(f"{prefix}{times}\n{segment.text}\n")
    return "\n".join(blocks)


__all__ = [
    "OfflineTranscriber", "TranscriptSegment", "TranscriptionResult",
    "write_transcripts",
]
