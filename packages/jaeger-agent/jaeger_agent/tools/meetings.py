"""Meetings, the free and local way: prep, record, transcribe, summarize.

Jaeger does not join Meet/Zoom/Teams as a bot (no free, ToS-safe way to do
that). Instead, while the owner is in the call on this Mac:

  • meeting_prep(title, day)      the event from Calendar.app, its join link
                                  and notes, plus what memory knows
  • meeting_record("start")       records this Mac's microphone to a local
                                  WAV under ~/.jaeger/meetings/ (the far side
                                  is captured only as far as the mic hears
                                  the speakers; with headphones only the
                                  owner's side is recorded)
  • meeting_record("stop")        stops, transcribes on this Mac with Whisper
                                  (large-v3-turbo via whisper.cpp)
  • meeting_transcribe(path)      transcribe any recording (Zoom/Meet local
                                  recording, Voice Memos, QuickTime)
  • meeting_summary(path)         decisions, action items and open questions
                                  written by a LOCAL Ollama model

Audio, transcripts and summaries never leave the Mac: transcription and the
summary both run locally, and the tools return file paths plus the summary.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

_WHISPER_MODEL = os.environ.get("JAEGER_MEETING_STT_MODEL", "large-v3-turbo")
_OLLAMA = os.environ.get("JAEGER_OLLAMA_URL", "http://127.0.0.1:11434")
_SUMMARY_MODELS = ("gemma4:12b", "qwen3:8b", "qwen3:4b", "llama3.2:3b", "gemma3:4b")
_MAX_RECORD_S = 3 * 3600


def _root() -> Path:
    base = os.environ.get("JAEGER_STATE_DIR") or str(Path.home() / ".jaeger")
    root = Path(base) / "meetings"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def _active_path() -> Path:
    return _root() / "active.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "meeting").lower()).strip("-")[:40] or "meeting"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ── prep ────────────────────────────────────────────────────────────


def meeting_prep(title: str = "", day: str = "today") -> dict[str, Any]:
    from .calendar import get_events
    res = get_events(day=day)
    events = res.get("events") or []
    if not events:
        return {"ok": res.get("listed", True) is not False, "event": None,
                "note": res.get("error") or f"No calendar events {day}."}
    now = datetime.now()
    chosen = None
    if title:
        chosen = next((e for e in events if title.lower() in str(e.get("title", "")).lower()), None)
    if chosen is None:
        def _start(e):
            raw = str(e.get("start") or "").replace("\u202f", " ").strip()
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
            # Calendar.app via AppleScript: "Monday, November 16, 2026 at 2:30:00 PM"
            for fmt in ("%A, %B %d, %Y at %I:%M:%S %p", "%A, %B %d, %Y at %H:%M:%S"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
            return now
        upcoming = [e for e in events if _start(e) >= now] or events
        chosen = sorted(upcoming, key=_start)[0]
    blob = " ".join(str(chosen.get(k) or "") for k in ("location", "notes", "url"))
    link = re.search(r"https://[^\s\"']*(zoom\.us|meet\.google\.com|teams\.microsoft\.com|webex\.com)[^\s\"']*", blob)
    memory: list = []
    try:
        from .memory import recall
        for word in [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", str(chosen.get("title", "")))][:4]:
            hit = recall(word)
            if hit and hit.get("found"):
                memory.append({"key": word, "value": hit.get("value")})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "event": chosen, "join_link": link.group(0) if link else None,
            "memory": memory, "events_today": len(events),
            "next": "When the call starts, meeting_record('start'); afterwards meeting_record('stop') "
                    "and meeting_summary(path)."}


# ── record ──────────────────────────────────────────────────────────


def meeting_record(action: str = "status", title: str = "") -> dict[str, Any]:
    action = (action or "status").lower()
    active = _active_path()
    state = json.loads(active.read_text()) if active.exists() else None
    if state and not _alive(int(state.get("pid", 0))) and action != "stop":
        state = None
        active.unlink(missing_ok=True)
    if action == "status":
        if not state:
            return {"ok": True, "recording": False}
        return {"ok": True, "recording": True, "title": state["title"], "path": state["audio"],
                "seconds": round(time.time() - state["started"])}
    if action == "start":
        if state:
            return {"ok": False, "error": f"Already recording '{state['title']}' since "
                    f"{datetime.fromtimestamp(state['started']).strftime('%-I:%M %p')}."}
        folder = _root() / f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-{_slug(title)}"
        folder.mkdir(parents=True, exist_ok=True)
        audio = folder / "audio.wav"
        log = open(folder / "recorder.log", "w")
        recorder = Path(__file__).with_name("meeting_recorder.py")
        proc = subprocess.Popen([sys.executable, str(recorder), str(audio)],
                                stdout=log, stderr=log, start_new_session=True)
        time.sleep(1.5)
        if proc.poll() is not None:
            return {"ok": False, "error": "The recorder stopped at once; see "
                    f"{folder / 'recorder.log'} (microphone permission?)"}
        active.write_text(json.dumps({"pid": proc.pid, "title": title or "Meeting",
                                      "audio": str(audio), "folder": str(folder), "started": time.time()}))
        return {"ok": True, "recording": True, "path": str(audio),
                "note": "Recording this Mac's microphone locally. Say meeting_record('stop') when the call ends."}
    if action == "stop":
        if not state:
            return {"ok": False, "error": "Nothing is recording."}
        pid = int(state["pid"])
        if _alive(pid):
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not _alive(pid):
                    break
                time.sleep(0.1)
        active.unlink(missing_ok=True)
        seconds = round(time.time() - state["started"])
        out = meeting_transcribe(state["audio"])
        out.update({"recorded_s": seconds, "title": state["title"]})
        return out
    return {"ok": False, "error": "action must be start, stop or status"}


# ── transcribe ──────────────────────────────────────────────────────


def _wav_level(path: Path) -> float | None:
    """RMS level (0..1) of a 16-bit WAV, or None for other formats."""
    if path.suffix.lower() != ".wav":
        return None
    try:
        import wave

        import numpy as np
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                return None
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype("float32") / 32768.0
        return float(np.sqrt(np.mean(pcm ** 2))) if pcm.size else 0.0
    except Exception:  # noqa: BLE001
        return None


def meeting_transcribe(path: str) -> dict[str, Any]:
    src = Path(path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"{src} not found"}
    level = _wav_level(src)
    if level is not None and level < 0.002:
        note = ("The recording is pure digital silence: macOS is blocking the microphone for "
                "Jaeger. Allow it in System Settings → Privacy & Security → Microphone."
                if level == 0.0 else
                "The recording is near-silent (nothing for Whisper to transcribe). "
                "Check that the Mac's input is the mic you are using.")
        return {"ok": True, "silent": True, "audio": str(src), "level": round(level, 5), "note": note}
    from jaeger_whisper_stt.offline import OfflineTranscriber
    started = time.time()
    result = OfflineTranscriber(_WHISPER_MODEL).transcribe(src)
    text = (result.text or "").strip()
    out = src.with_name(src.stem + "-transcript.md") if src.name != "audio.wav" else src.with_name("transcript.md")
    out.write_text(f"# Transcript: {src.name}\n\n{text}\n", encoding="utf-8")
    return {"ok": True, "transcript_path": str(out), "audio_s": round(result.audio_s, 1),
            "took_s": round(time.time() - started, 1), "model": _WHISPER_MODEL,
            "words": len(text.split()), "preview": text[:600],
            "next": "meeting_summary(transcript_path) writes the summary with a local model."}


# ── summary ─────────────────────────────────────────────────────────


def _local_model() -> str | None:
    want = os.environ.get("JAEGER_MEETING_SUMMARY_MODEL")
    try:
        with urllib.request.urlopen(f"{_OLLAMA}/api/tags", timeout=3) as r:
            have = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return None
    if want and want in have:
        return want
    for name in _SUMMARY_MODELS:
        if name in have:
            return name
    local = [n for n in have if "cloud" not in n and "embed" not in n]
    return local[0] if local else None


_PROMPT = ("Summarize this meeting transcript for the person who attended. Use exactly these "
           "headings: Summary (2-3 sentences), Decisions, Action items (owner: task, due date if "
           "said), Open questions. Use only what the transcript says; write 'None' for an empty "
           "section.\n\nTranscript:\n")


def meeting_summary(path: str) -> dict[str, Any]:
    src = Path(path).expanduser()
    if src.suffix.lower() in {".wav", ".m4a", ".mp3", ".mp4", ".aiff", ".mov"}:
        t = meeting_transcribe(str(src))
        if not t.get("ok"):
            return t
        src = Path(t["transcript_path"])
    if not src.exists():
        return {"ok": False, "error": f"{src} not found"}
    text = src.read_text(encoding="utf-8")[-60000:]
    model = _local_model()
    if not model:
        return {"ok": False, "error": "No local Ollama model is running, so the summary would have to "
                "leave the Mac. Start Ollama (ollama serve) and pull a model, e.g. ollama pull qwen3:4b."}
    body = json.dumps({"model": model, "stream": False, "think": False,
                       "messages": [{"role": "user", "content": _PROMPT + text}],
                       "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request(f"{_OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        summary = (json.load(r).get("message") or {}).get("content", "").strip()
    summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.S).strip()
    out = src.with_name("summary.md") if src.name == "transcript.md" else src.with_name(src.stem + "-summary.md")
    out.write_text(summary + "\n", encoding="utf-8")
    return {"ok": True, "summary_path": str(out), "model": model, "local": True,
            "took_s": round(time.time() - started, 1), "summary": summary}


# ── agent-facing wrappers ───────────────────────────────────────────


@register_tool_from_function(name="meeting_prep", side_effect="read")
def _t_meeting_prep(title: str = "", day: str = "today") -> dict:
    """Prep for a meeting: finds it in Calendar.app (the next one today, or by
    `title`), returns its time, join link and notes plus anything memory knows
    about it. Use before a call ("prep me for my 3 pm")."""
    return meeting_prep(title=title, day=day)


@register_tool_from_function(name="meeting_record", side_effect="local")
def _t_meeting_record(action: str = "status", title: str = "") -> dict:
    """Record a meeting the owner is in on this Mac: action='start' records
    the microphone to a local file, 'stop' ends it and transcribes it locally
    with Whisper, 'status' says whether it is recording. Jaeger cannot join a
    call as a bot; this captures what the Mac's mic hears."""
    return meeting_record(action=action, title=title)


@register_tool_from_function(name="meeting_transcribe", side_effect="local")
def _t_meeting_transcribe(path: str) -> dict:
    """Transcribe a meeting recording on this Mac with Whisper (any audio or
    video file: a Zoom/Meet local recording, Voice Memo, QuickTime file).
    Writes a transcript file next to it."""
    return meeting_transcribe(path)


@register_tool_from_function(name="meeting_summary", side_effect="local")
def _t_meeting_summary(path: str) -> dict:
    """Summarize a meeting transcript (or recording) with a LOCAL model:
    summary, decisions, action items with owners, open questions. Content
    stays on the Mac. Writes summary.md and returns it."""
    return meeting_summary(path)

