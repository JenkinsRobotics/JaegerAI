"""Bounded, local transcription for owner-recorded Droid chat clips."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_WAKE_PREFIX = r"(?:(?:hey|hi|ok|okay)\s+)?(?:(?:jaeger|jager|yeager|yager|truth|droid)\s+)?(?:please\s+)?"
_TRAILING_SUFFIX = r"(?:\s+(?:now|please|jaeger|jager|yeager|yager|truth|droid)){0,2}"

_SLEEP_COMMAND_RE = re.compile(
    rf"^{_WAKE_PREFIX}"
    r"(?:"
    r"go\s+to\s+sleep"
    r"|park\s+(?:the\s+)?camera"
    r"|(?:turn\s+off|shut\s+off|shut\s+down|power\s+down|disable|stop)\s+(?:the\s+)?droid(?:\s+mode)?"
    r"|(?:exit|leave)\s+(?:the\s+)?droid\s+mode"
    r"|(?:turn|shut|power)\s+(?:the\s+)?droid(?:\s+mode)?\s+(?:off|down)"
    r"|droid\s+mode\s+off"
    r"|droid\s+(?:go\s+to\s+)?sleep"
    r")"
    rf"{_TRAILING_SUFFIX}$",
    re.IGNORECASE,
)

_ADDRESSED_SLEEP_RE = re.compile(
    r"^(?:(?:hey|hi|ok|okay)\s+)?"
    r"(?:jaeger|jager|yeager|yager|truth|droid)\s+"
    r"(?:please\s+)?"
    r"sleep"
    r"(?:\s+(?:now|please)){0,2}$",
    re.IGNORECASE,
)


def detect_voice_intent(transcript: str) -> str | None:
    """Detect explicit local Droid voice commands (e.g. privacy sleep) without conversational false triggers."""
    raw = (transcript or "").strip()
    if not raw or "?" in raw:
        return None
    cleaned = re.sub(r"[^\w\s']", " ", raw.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if _SLEEP_COMMAND_RE.fullmatch(cleaned) or _ADDRESSED_SLEEP_RE.fullmatch(cleaned):
        return "sleep"
    return None


def transcribe_clip(audio: bytes, *, enroll: bool = False) -> dict[str, str]:
    from .speaker_gate import verify_voice
    from .sound_gate import background_label
    ffmpeg = shutil.which("ffmpeg")
    whisper = shutil.which("whisper-cli")
    model = Path(os.environ.get("JAEGER_DROID_WHISPER_MODEL", "~/.whisper/ggml-base.en.bin")).expanduser()
    if not ffmpeg or not whisper or not model.is_file():
        raise RuntimeError("Local Droid voice requires ffmpeg, whisper-cli, and a Whisper model.")
    with tempfile.TemporaryDirectory(prefix="jaeger-droid-voice-") as folder:
        scratch = Path(folder)
        wav = scratch / "clip.wav"
        report = scratch / "transcript"
        try:
            subprocess.run(
                [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0",
                 "-t", "20", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
                input=audio, capture_output=True, check=True, timeout=10,
            )
            background = background_label(wav)
            if background:
                return {"transcript": "", "notice": f"Background audio detected ({background}). Clip held locally."}
            decision = verify_voice(wav, enroll)
            if decision:
                return {"transcript": "", "notice": decision}
            subprocess.run(
                [whisper, "-m", str(model), "-f", str(wav), "-nt", "-t", "2", "-ng", "-oj", "-of", str(report)],
                capture_output=True, check=True, timeout=30,
            )
            segments = json.loads(report.with_suffix(".json").read_text())["transcription"]
            transcript = " ".join(segment["text"].strip() for segment in segments).replace("[BLANK_AUDIO]", "").strip()
            if not transcript or re.fullmatch(r"[\[\(\*♪].*[\]\)\*♪]", transcript):
                return {"transcript": "", "notice": "Silence or non-speech audio ignored."}
            intent = detect_voice_intent(transcript)
            result: dict[str, str] = {"transcript": transcript}
            if intent:
                result["intent"] = intent
            return result
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            raise RuntimeError("Local speech transcription failed or timed out.") from None
