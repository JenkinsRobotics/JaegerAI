#!/usr/bin/env python3
"""Google-Home-style local voice assistant.

Pipeline: SEQUENTIAL   — each stage completes before the next starts
                         (transcribe -> think whole reply -> speak whole reply)
Audio:    HALF-DUPLEX  — the mic is PAUSED while the assistant speaks;
                         it cannot be interrupted mid-sentence
Wake:     "hey jaeger" + follow-up window
Benchmark twin: A0

Pipeline:
  mic ─► audio_queue ─► VAD worker thread ─► phrase_queue
                                               │
                                               ▼
        main loop (state machine) ──► wake check / 2-pass STT ──► LLM ──► TTS

Designed off PywisperCpp/pywhispercpp_examples/local_assistant/
continuous_lmstudio_command_listener.py with these additions:
  • mic.pause flag during TTS for self-speech rejection
  • short tone instead of spoken "Yes?" so the user isn't clipped
  • 15-second follow-up window after each reply (no wake word required)
  • LLM (llama.cpp + Gemma 4 26B-A4B) and TTS (Kokoro) wired in
  • auto-calibrated noise floor + non-speech filter (voice_gate.py)

Just hit Run.  Loads can take ~15–25s the first time.
"""


import collections
import queue
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import webrtcvad

from rich.console import Console

# ═══════════════════════════════════════════════════════════════════════════
# VENDORED CORE — this app is deliberately self-contained. Copy this ONE file
# into another project and it runs; no core/ package to carry along. The
# sections below are duplicated across the production apps BY DESIGN — they
# are the proven pieces (validated by jfk_regression.py and run_tests.sh).
# ═══════════════════════════════════════════════════════════════════════════

# ══ section: models.py ═══════════════════════════════════════════════════════════════════════
"""Which local LLMs the voice apps can use.

One registry so every app offers the same choices and reports the same names.
Swapping the LLM is the single biggest lever on time-to-first-token, so it is a
flag rather than an edit.

    python voice_sequential_halfduplex.py --llm e4b
"""


import argparse
from dataclasses import dataclass
from pathlib import Path

LMSTUDIO = Path.home() / ".lmstudio/models/lmstudio-community"


@dataclass(frozen=True)
class LLMChoice:
    key: str
    path: Path
    label: str
    note: str

    @property
    def present(self) -> bool:
        return self.path.exists()

    @property
    def size_gb(self) -> float:
        return round(self.path.stat().st_size / 1024**3, 2) if self.present else 0.0


LLMS: dict[str, LLMChoice] = {
    "e4b": LLMChoice(
        "e4b",
        LMSTUDIO / "gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf",
        "gemma-4-E4B-it Q4_K_M",
        "~5GB — fastest to load and to first token; the better default for "
        "conversational latency",
    ),
    "26b": LLMChoice(
        "26b",
        LMSTUDIO / "gemma-4-26B-A4B-it-QAT-GGUF/gemma-4-26B-A4B-it-QAT-Q4_0.gguf",
        "gemma-4-26B-A4B-it QAT Q4_0",
        "~13GB — stronger answers, slower first token",
    ),
}

# E4B by default: ~5GB vs ~13GB. With Base STT (~148MB), Kokoro, and on
# some days the 12GB omni stack resident, the 26B left no headroom on 32GB.
# Stronger answers are one flag away: --llm 26b
DEFAULT_LLM = "e4b"


def available() -> list[LLMChoice]:
    return [c for c in LLMS.values() if c.present]


def resolve(key: str | None) -> LLMChoice:
    choice = LLMS.get(key or DEFAULT_LLM)
    if choice is None:
        raise SystemExit(f"unknown --llm {key!r}; choose from {', '.join(LLMS)}")
    return choice


def add_argument(ap: argparse.ArgumentParser) -> None:
    """Attach --llm to an app's parser, listing what is actually on disk."""
    opts = ", ".join(
        f"{c.key} ({c.size_gb:.1f}GB)" if c.present else f"{c.key} (missing)"
        for c in LLMS.values())
    ap.add_argument("--llm", choices=list(LLMS), default=DEFAULT_LLM,
                    help=f"which local LLM to load — {opts}. Default {DEFAULT_LLM}.")


def parse_llm(description: str = "") -> LLMChoice:
    """Minimal CLI for apps that otherwise take no arguments."""
    ap = argparse.ArgumentParser(description=description)
    add_argument(ap)
    return resolve(ap.parse_args().llm)

# ══ section: hardware.py ═════════════════════════════════════════════════════════════════════
"""Hardware and runtime inventory, reported at startup and saved into every session.

The point is that a latency number is meaningless without the machine it was
measured on. This reports what is actually true rather than what the spec
template expects — on Apple Silicon there is no VRAM and no CUDA, and saying
"CUDA: none" is more useful than omitting the field.
"""


import platform
import shutil
import subprocess
from pathlib import Path


def _sysctl(key: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def _torch_info() -> dict:
    try:
        import torch
    except ImportError:
        return {"torch": "not installed", "cuda": "n/a", "mps": "n/a"}
    return {
        "torch": torch.__version__,
        "cuda": torch.version.cuda or "none (no CUDA on this machine)",
        "cuda_available": torch.cuda.is_available(),
        "mps_available": bool(getattr(torch.backends, "mps", None)
                              and torch.backends.mps.is_available()),
    }


def hardware_describe(omni_model: Path | None = None, llm_model: Path | None = None,
             extra: dict | None = None) -> dict:
    """extra: {label: path} for any other model files the app loads."""
    mem_bytes = _sysctl("hw.memsize")
    info = {
        "os": f"{platform.system()} {platform.release()} ({platform.mac_ver()[0] or 'n/a'})",
        "arch": platform.machine(),
        "cpu": _sysctl("machdep.cpu.brand_string") or platform.processor(),
        "cpu_cores": _sysctl("hw.ncpu"),
        "ram_gb": round(int(mem_bytes) / 1024**3, 1) if mem_bytes.isdigit() else "unknown",
        "python": platform.python_version(),
    }
    info.update(_torch_info())

    # Apple Silicon has no discrete VRAM — the GPU shares system RAM. Reporting a
    # VRAM number here would be a fiction; the unified pool is the real limit.
    if info["arch"] == "arm64" and info["os"].startswith("Darwin"):
        info["gpu"] = f"{info['cpu']} integrated GPU (Metal)"
        info["vram"] = f"unified with system RAM ({info['ram_gb']} GB total)"
        info["inference_backend"] = "Metal (ggml/llama.cpp)"
    else:
        info["gpu"] = "unknown"
        info["vram"] = "unknown"
        info["inference_backend"] = "cpu/cuda (see torch fields)"

    info["models"] = {}
    named = [("minicpm_o_45", omni_model), ("legacy_llm", llm_model)]
    named += list((extra or {}).items())
    for label, path in named:
        if path is None:
            continue
        p = Path(path)
        info["models"][label] = {
            "path": str(p),
            "present": p.exists(),
            "size_gb": round(p.stat().st_size / 1024**3, 2) if p.exists() else None,
            "quantization": _quant_from_name(p.name),
            "precision": "int8" if "Q8" in p.name else
                         "int4" if "Q4" in p.name else
                         "fp16" if "F16" in p.name else "unknown",
        }

    info["disk_free_gb"] = round(shutil.disk_usage(Path.home()).free / 1024**3, 1)
    return info


def _quant_from_name(name: str) -> str:
    for tag in ("Q8_0", "Q6_K", "Q5_K_M", "Q5_K_S", "Q4_K_M", "Q4_K_S", "Q4_0", "F16", "BF16"):
        if tag in name:
            return tag
    return "unknown"


# Whisper models are fetched automatically by pywhispercpp on first use, so a
# missing one is a slow first run, not a failure. GGUF paths are hand-configured
# and nothing will fetch them — those are fatal.
SELF_DOWNLOADING = ("stt_fast", "stt_accurate")


def hardware_require(info: dict, allow_missing: tuple[str, ...] = SELF_DOWNLOADING) -> None:
    """Abort now if a model that nothing will fetch for us is missing.

    Without this the app loads Whisper, spends a couple of seconds, then dies in
    llama.cpp with a bare ValueError. But refusing to start over a model that
    downloads itself would block the very run that fixes it.
    """
    models_ = info.get("models", {})
    fatal = [(k, m["path"]) for k, m in models_.items()
             if not m["present"] and k not in allow_missing]
    later = [(k, Path(m["path"]).name) for k, m in models_.items()
             if not m["present"] and k in allow_missing]

    if later:
        names = ", ".join(f"{k} ({n})" for k, n in later)
        print(f"\n  note: {names} will be downloaded on first use "
              f"— the first run will be slower.\n")
    if not fatal:
        return
    lines = ["", "Cannot start — model file(s) not found:", ""]
    lines += [f"  {label:<14} {path}" for label, path in fatal]
    lines += ["", "Nothing will fetch these automatically. Fix the path at the "
              "top of this file, or download the model.", ""]
    raise SystemExit("\n".join(lines))


def hardware_render(info: dict) -> str:
    lines = [
        f"OS            {info['os']}  [{info['arch']}]",
        f"CPU           {info['cpu']}  ({info['cpu_cores']} cores)",
        f"RAM           {info['ram_gb']} GB",
        f"GPU           {info['gpu']}",
        f"VRAM          {info['vram']}",
        f"CUDA          {info.get('cuda', 'n/a')}",
        f"PyTorch       {info.get('torch', 'n/a')}  (mps={info.get('mps_available')})",
        f"Inference     {info['inference_backend']}",
        f"Disk free     {info['disk_free_gb']} GB",
    ]
    for label, m in info.get("models", {}).items():
        status = ("OK" if m["present"]
                  else "will download" if label in SELF_DOWNLOADING
                  else "MISSING")
        lines.append(
            f"{label:<13} {status}  {m['quantization']} / {m['precision']}"
            + (f"  {m['size_gb']} GB" if m["size_gb"] else ""))
    return "\n".join(lines)

# ══ section: voice_gate.py ═══════════════════════════════════════════════════════════════════
#!/usr/bin/env python3
"""Shared noise gating and wake-word logic for the voice demos.

voice_sequential_halfduplex.py and voice_sequential_fullduplex.py both need the same answer to one question:
is this segment someone talking to me, or is it the TV, music, or a keyboard?

Three cheap layers, in the order they should run. Anything a layer rejects never
reaches the expensive STT/LLM stages:

  1. speech_level()  - was it loud enough to be someone at the mic? You sit near
                       it; the TV does not. Distance is the cheapest signal there
                       is and it needs no model.
  2. is_non_speech() - did Whisper transcribe an event rather than words?
  3. find_wake()     - was the assistant actually addressed?

Nothing here imports the demos, so either file can use it standalone.
"""


import re
import time
from difflib import SequenceMatcher

import numpy as np


# -- level gating ------------------------------------------------------------
# Admission threshold = measured room floor * NOISE_MARGIN, never below
# MIN_SPEECH_RMS. 2x, not 3x: on a real desk mic normal speech measures only
# ~2-3x the room floor, and 3x rejected genuine speech at 0.06-0.08 rms against
# a 0.029 floor. Raise toward 3 only if a TV is getting through.
NOISE_MARGIN = 2.0
MIN_SPEECH_RMS = 0.012
# Hard ceiling. Without it a noisy calibration window (a fan spinning up, a hot
# XLR preamp, someone talking) multiplies into a threshold near 1.0 that no real
# speech can clear — and every turn is then dropped, silently. Normal speech
# sits around 0.03-0.3 RMS, so anything above this is a failed calibration.
MAX_SPEECH_RMS = 0.10
CALIBRATION_SECONDS = 1.5

# Whisper wraps non-speech events in brackets: [BLANK_AUDIO], (clicking),
# [typing sounds], *sighs*. If nothing survives stripping those, it wasn't speech.
_BRACKETED_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")


def is_non_speech(text: str) -> bool:
    return not _BRACKETED_RE.sub("", text).strip(" .,!?-\"'")


def speech_level(audio: np.ndarray, frame_samples: int) -> float:
    """Loudness of the loud part of a segment, ignoring its silence.

    Plain RMS over a whole segment is dragged down by pre-roll and hangover
    padding, so a short close-up word can score below long quiet noise. The 90th
    percentile frame tracks how loud the speaker actually was.
    """
    flat = np.asarray(audio, dtype=np.float32).reshape(-1)
    if flat.size == 0:
        return 0.0
    n_frames = flat.size // frame_samples
    if n_frames == 0:
        return float(np.sqrt(np.mean(np.square(flat))))
    frames = flat[: n_frames * frame_samples].reshape(n_frames, frame_samples)
    return float(np.percentile(np.sqrt(np.mean(np.square(frames), axis=1)), 90))


def calibrate_noise_floor(
    get_chunk,
    frame_samples: int,
    seconds: float = CALIBRATION_SECONDS,
    label: str = "gate",
) -> float:
    """Listen to the room for a moment and return the admission threshold.

    get_chunk() should return one audio chunk, or None if none is ready. Run this
    before the assistant starts responding, while the room is doing whatever it
    normally does — the TV can stay on, that is the point.
    """
    levels: list[float] = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = get_chunk()
        if chunk is None:
            continue
        levels.append(speech_level(chunk, frame_samples))

    # Median, not p90: a floor is the quiet part of the window. Using a high
    # percentile made a single cough during calibration deafen the whole app.
    floor = float(np.median(levels)) if levels else 0.0
    raw = max(floor * NOISE_MARGIN, MIN_SPEECH_RMS)
    threshold = min(raw, MAX_SPEECH_RMS)
    print(f"[{label}] room floor {floor:.4f} -> admit above {threshold:.4f}",
          flush=True)
    if raw > MAX_SPEECH_RMS:
        print(f"[{label}] WARNING: calibration wanted {raw:.4f}, capped to "
              f"{MAX_SPEECH_RMS:.4f}. The room was not quiet, or mic gain is "
              f"high. Run production/mic_check.py if speech is not detected.",
              flush=True)
    return threshold


# -- wake word ---------------------------------------------------------------
# Whisper often mishears "jaeger" — covering common phonetic transcriptions so
# any of yeager/yager/jager/jaeger triggers the wake. Every phrase is two words
# on purpose: a bare name matches far too much TV dialogue.
# Demo-friendly: lots of trigger names so new users can just say something
# natural. Every phrase stays TWO words (prefix + name) — a bare name matches
# far too much TV dialogue.
_WAKE_PREFIXES = ("ok", "okay", "hey")
_ASSISTANT_NAMES = ("jaeger", "yeager", "yager", "jager",
                    "robot", "google", "siri", "jarvis", "computer")
WAKE_PHRASES = tuple(f"{p} {n}" for p in _WAKE_PREFIXES for n in _ASSISTANT_NAMES)
# Raise toward 0.85 if the TV trips the wake; lower toward 0.72 if yours doesn't fire.
WAKE_MATCH_THRESHOLD = 0.78


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _match_wake(text: str) -> tuple[str, str] | None:
    """Return (phrase_as_heard, remainder) or None.

    phrase_as_heard is what the user actually said — for a fuzzy hit that is the
    misheard form ("hey yeager"), which is the useful thing to show them.
    """
    norm = normalize(text)
    for phrase in WAKE_PHRASES:
        idx = norm.find(phrase)
        if idx != -1:
            return phrase, norm[idx + len(phrase):].strip()
    # Fuzzy pass: the NAME may be misheard, but the PREFIX must be a real
    # prefix word. Whole-phrase fuzz let "the computer" match "hey computer"
    # (ratio ~0.84), which turns ordinary TV dialogue into wake events — a
    # hazard that grows with every name added to the demo list.
    tokens = norm.split()
    for phrase in WAKE_PHRASES:
        parts = phrase.split()
        n = len(parts)
        name = " ".join(parts[1:])
        for i in range(0, max(0, len(tokens) - n + 1)):
            if tokens[i] not in _WAKE_PREFIXES:
                continue
            cand = " ".join(tokens[i + 1:i + n])
            if SequenceMatcher(None, cand, name).ratio() >= WAKE_MATCH_THRESHOLD:
                return " ".join(tokens[i:i + n]), " ".join(tokens[i + n:]).strip()
    return None


def find_wake(text: str) -> tuple[bool, str]:
    """Return (matched, remainder_after_wake_phrase)."""
    hit = _match_wake(text)
    return (True, hit[1]) if hit else (False, "")


def find_wake_phrase(text: str) -> str | None:
    """Which wake phrase was heard, for display. None if no match."""
    hit = _match_wake(text)
    return hit[0] if hit else None

# ══ section: cui.py ══════════════════════════════════════════════════════════════════════════
"""Shared console UI for the voice apps.

One look across every app, and — more importantly — one place that guarantees
the thing you actually need while talking to a machine: **it always shows what
it is doing right now, and how long it has been doing it.**

A voice app that prints nothing between "you stopped talking" and "here is the
reply" is indistinguishable from one that did not hear you. The `Now` row and
its elapsed timer exist so that gap is never ambiguous.

Usage:

    ui = VoiceUI("Jaeger Voice Assistant", ["Wake", "Model", "Microphone"])
    with ui.live():
        ui.status("Model", "READY", "green")
        ui.phase("listening")
        ui.provisional("what time is")     # greyed, still being transcribed
        ui.said("User", "what time is it")
        ui.latency("First audio played", 812)
"""


import time
from contextlib import contextmanager

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class VoiceUI:
    def __init__(self, title: str, status_rows: list[str],
                 latency_rows: list[str] | None = None,
                 footer: str = "Ctrl-C to quit",
                 history: int = 8, file=None) -> None:
        """file: render here instead of sys.stdout. voice_omni.py redirects
        fd 1 to a log file to silence the engine, and passes the saved console."""
        self.title = title
        self.console = Console(file=file) if file is not None else Console()
        self._status = {k: ("—", "white") for k in status_rows}
        self._status_order = list(status_rows)
        self._latency_order = latency_rows or []
        self._latency = {k: None for k in self._latency_order}
        self.footer = footer
        self.history = history
        self._lines: list[tuple[str, str, str | None]] = []
        self._stable_preview = ""
        self._provisional = ""
        self._phase = "starting"
        self._phase_at = time.perf_counter()
        self._note = ""
        self._wake: tuple[str, float] | None = None
        self._live: Live | None = None

    # -- mutations ---------------------------------------------------------
    def status(self, key: str, value: str, style: str = "white") -> None:
        self._status[key] = (value, style)
        self._refresh()

    def phase(self, text: str) -> None:
        """What it is doing *now*. Resets the elapsed timer."""
        self._phase = text
        self._phase_at = time.perf_counter()
        self._refresh()

    def provisional(self, text: str) -> None:
        """Unstable transcript — shown greyed so it reads as not-yet-committed."""
        self._stable_preview = ""
        self._provisional = text
        self._refresh()

    def live_transcript(self, committed: list[str], pending: str) -> None:
        """Show a stable preview prefix without putting it in the final log."""
        self._stable_preview = " ".join(committed)
        self._provisional = pending
        self._refresh()

    def said(self, who: str, text: str, highlight: str | None = None) -> None:
        """highlight: substring rendered in yellow — used for the wake phrase so
        you can see it was detected rather than having to guess."""
        self._stable_preview = ""
        self._provisional = ""
        self._lines.append((who, text, highlight))
        self._refresh()

    def wake(self, phrase: str) -> None:
        """Flash that a wake phrase was recognised, and what it heard."""
        self._wake = (phrase, time.perf_counter())
        self._refresh()

    def latency(self, key: str, ms: float | None) -> None:
        self._latency[key] = ms
        self._refresh()

    def reset_latency(self) -> None:
        self._latency = {k: None for k in self._latency_order}
        self._refresh()

    def note(self, text: str) -> None:
        """One-line warning under the transcript (dropped audio, errors)."""
        self._note = text
        self._refresh()

    def clear(self) -> None:
        self._lines.clear()
        self._stable_preview = ""
        self._provisional = ""
        self._refresh()

    # -- rendering ---------------------------------------------------------
    def _render(self):
        # Fit the terminal or Live cannot redraw in place: a frame taller than
        # the screen gets PRINTED each refresh instead of updated, duplicating
        # the panel endlessly. Budget rows, shrink history, and drop the
        # latency panel before ever exceeding the height.
        height = max(self.console.size.height, 10)
        head_rows = len(self._status_order) + 1 + (1 if self._wake else 0) + 2
        live_overhead = (1 if self._stable_preview or self._provisional else 0) + 2
        footer_rows = 3
        note_rows = 3 if self._note else 0
        lat_rows = (len(self._latency_order) + 2) if self._latency_order else 0

        budget = height - head_rows - live_overhead - footer_rows - 3
        show_note = self._note and budget - note_rows >= 4
        if show_note:
            budget -= note_rows
        show_latency = bool(self._latency_order) and budget - lat_rows >= 3
        if show_latency:
            budget -= lat_rows
        hist = max(1, min(self.history, budget))
        return self._render_panels(hist, show_latency, show_note)

    def _render_panels(self, history_lines: int, show_latency: bool,
                       show_note: bool = True):
        head = Table.grid(padding=(0, 2))
        for k in self._status_order:
            v, style = self._status[k]
            head.add_row(k, Text(v, style=style))
        if self._wake:
            phrase, at = self._wake
            age = time.perf_counter() - at
            head.add_row("Wake", Text(f'✓ heard "{phrase}"',
                                      style="bold yellow" if age < 4 else "dim yellow"))
        held = time.perf_counter() - self._phase_at
        # Amber once a phase has run longer than feels instant, so a stall is
        # visible rather than looking like a frozen app.
        head.add_row("Now", Text(f"{self._phase}   {held:4.1f}s",
                                 style="bold yellow" if held > 1.5 else "bold green"))

        # Two zones, deliberately separate: LIVE holds only the ACTIVE window
        # (text still forming, may change); COMMITTED holds settled lines that
        # will never be revised. Mixing them made commits invisible and the
        # live window unclear about what was final.
        if self._stable_preview or self._provisional:
            live = Text()
            if self._stable_preview:
                live.append(self._stable_preview, style="dim cyan")
            if self._stable_preview and self._provisional:
                live.append(" ")
            if self._provisional:
                live.append(self._provisional + " ▌", style="italic")
            else:
                live.append(" ✓", style="dim green")
        else:
            live = Text("—  (listening)", style="dim")

        committed = Table.grid(padding=(0, 1))
        for who, what, hl in self._lines[-history_lines:]:
            dim = who.lower().startswith(("ignored", "noise", "dropped", "environment", "heard"))
            body = Text(what[:400], style="dim" if dim else "")
            if hl:
                body.highlight_words([hl], style="bold yellow on grey15")
            style = ("dim" if dim else
                     "bold magenta" if who == "User" else "bold green")
            committed.add_row(Text(f"{who}:", style=style), body)
        if not self._lines:
            committed.add_row(Text("—", style="dim"),
                              Text("nothing committed yet", style="dim"))

        # Messaging-app order: history (COMMITTED) on top, the active window
        # (LIVE) at the bottom like an input field.
        panels = [Panel(head, title=self.title, border_style="cyan"),
                  Panel(committed, title="COMMITTED", border_style="white"),
                  Panel(live, title="LIVE — forming now", border_style="yellow")]

        if self._latency_order and show_latency:
            lat = Table.grid(padding=(0, 2))
            for k in self._latency_order:
                v = self._latency.get(k)
                lat.add_row(k, Text(f"{v:>8.0f} ms" if v is not None else "       — "))
            panels.append(Panel(lat, title="LATENCY", border_style="white"))

        if self._note and show_note:
            panels.append(Panel(Text(self._note, style="yellow"), border_style="yellow"))
        panels.append(Panel(Text(self.footer, style="dim"), border_style="dim"))
        return Group(*panels)

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    @contextmanager
    def live(self, refresh_per_second: int = 8):
        """Enter the live display. The elapsed timer ticks on its own."""
        with Live(self._render(), console=self.console,
                  refresh_per_second=refresh_per_second,
                  vertical_overflow="crop") as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def tick(self) -> None:
        """Call periodically so the elapsed timer advances while idle."""
        self._refresh()

# ══ section: sentence_stability.py ═══════════════════════════════════════════════════════════
"""Commit-by-sentence-stability: the middle ground between the two pipelines.

The problem with the existing two:

  phrase_buffer  commits on a 3s silence timer. The sentence was finished long
                 before the timer was, so every turn carries that lag.
  hybrid         commits any 2 new words each pass (~1.2s). It fires mid-
                 sentence, and because Whisper *revises* earlier words as more
                 audio arrives, the word-cursor mis-aligns and text repeats.

Neither asks the only question that matters: **has this sentence stopped
changing?**

A rolling transcript is re-decoded every pass over a growing buffer. Early
sentences settle; the last one keeps churning as more audio arrives. So:

    pass 1   "The capital of France"
    pass 2   "The capital of France is Paris."          <- sentence 1 changed
    pass 3   "The capital of France is Paris. And the"  <- sentence 1 identical
                                                           AND a later sentence
                                                           started -> COMMIT it

A sentence is committed when either:

  * it has been byte-identical for STABLE_PASSES consecutive decodes, or
  * a later sentence has started — the speaker moved past it, and Whisper
    essentially never revises a sentence once that has happened.

The second rule is what removes the lag: no timer, no waiting for silence. The
first rule catches the final sentence of a turn, which has nothing after it.

Committing is strictly in order and each sentence exactly once, which is what
stops the repeats.
"""


import re
from dataclasses import dataclass, field

# Sentence ends. Kept deliberately simple — a full NLP splitter would be slower
# and no more correct on the short, spoken sentences this sees.
# A boundary is terminal punctuation (plus any closing quote/bracket) followed
# by whitespace. The match starts AT the punctuation so the sentence slice
# includes it — getting that off by one made every abbreviation check miss.
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?=\s)")
_ABBREV = re.compile(r"\b(mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|no|fig)\.$", re.I)

STABLE_PASSES = 2          # identical decodes before a trailing sentence commits
MIN_COMMIT_CHARS = 2       # ignore stray punctuation fragments


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends, without breaking decimals or abbreviations."""
    text = " ".join(text.split())
    if not text:
        return []
    out: list[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        end = m.end()                     # inclusive of the punctuation
        piece = text[start:end].strip()
        if not piece:
            continue
        # "3.5" — digits either side of a lone period are not a boundary.
        if (m.group().startswith(".")
                and text[m.start() - 1:m.start()].isdigit()
                and text[end + 1:end + 2].isdigit()):
            continue
        if _ABBREV.search(piece):
            continue
        out.append(piece)
        start = end
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


@dataclass
class SentenceCommitter:
    """Feed it each rolling transcript; it yields sentences once, in order."""

    stable_passes: int = STABLE_PASSES
    committed: list[str] = field(default_factory=list)
    _seen: dict[int, tuple[str, int]] = field(default_factory=dict)  # idx -> (text, passes)

    def update(self, transcript: str, allow_tail_commit: bool = True) -> list[str]:
        """Returns sentences that just became final. Call once per decode.

        allow_tail_commit=False withholds STABILITY commits for the last
        sentence. Used when the decode window ends right at that sentence:
        Whisper hallucinates plausible completions at the window edge, and a
        pause makes the hallucination identical across passes — stable, wrong,
        and frozen. Superseded-rule commits are unaffected (a later sentence
        existing proves the tail is not at the edge).
        """
        sentences = split_sentences(transcript)
        ready: list[str] = []
        n_committed = len(self.committed)

        for idx, sentence in enumerate(sentences):
            if idx < n_committed:
                continue                      # already emitted, never revisit

            prev_text, prev_passes = self._seen.get(idx, ("", 0))
            passes = prev_passes + 1 if sentence == prev_text else 1
            self._seen[idx] = (sentence, passes)

            # A later sentence exists -> the speaker moved on -> this one is done.
            superseded = idx < len(sentences) - 1
            settled = passes >= self.stable_passes and (
                superseded or allow_tail_commit)
            if (superseded or settled) and len(sentence) >= MIN_COMMIT_CHARS:
                # Only commit contiguously: never skip a sentence that is still
                # churning, or the transcript would come out reordered.
                if idx == len(self.committed):
                    self.committed.append(sentence)
                    ready.append(sentence)
        return ready

    def force_oldest(self) -> list[str]:
        """Commit the oldest pending sentence regardless of stability.

        For pressure relief only: when unstable audio (applause, crowd noise)
        stops anything from stabilising and the buffer keeps growing, the
        oldest sentence has been re-decoded for many passes — it is as
        confirmed as it will ever get. Committing it one sentence at a time
        preserves order; the old alternative was a 40s cap dump that discarded
        whole clauses (found by jfk_regression --diff on the full speech).
        """
        idx = len(self.committed)
        if idx in self._seen:
            text = self._seen[idx][0]
            if len(text) >= MIN_COMMIT_CHARS:
                self.committed.append(text)
                return [text]
        return []

    def flush(self) -> list[str]:
        """End of turn — emit whatever is left, stable or not."""
        ready = []
        for idx in sorted(self._seen):
            if idx == len(self.committed):
                text = self._seen[idx][0]
                if len(text) >= MIN_COMMIT_CHARS:
                    self.committed.append(text)
                    ready.append(text)
        return ready

    def pending(self, transcript: str) -> str:
        """The uncommitted tail — what to show as provisional."""
        sentences = split_sentences(transcript)
        return " ".join(sentences[len(self.committed):])

    def reset(self) -> None:
        self.committed.clear()
        self._seen.clear()


def _demo() -> None:
    """Runnable check: python sentence_stability.py"""
    assert split_sentences("The value is 3.5 and that is all.") == \
        ["The value is 3.5 and that is all."], "decimals must not split"
    assert split_sentences("Ask Dr. Smith about it. Then leave.") == \
        ["Ask Dr. Smith about it.", "Then leave."], split_sentences(
            "Ask Dr. Smith about it. Then leave.")
    assert split_sentences("") == []

    # The real scenario: a rolling transcript over a growing buffer.
    c = SentenceCommitter(stable_passes=2)
    assert c.update("The capital of France") == [], "unstable tail must not commit"
    assert c.update("The capital of France is Paris.") == [], "changed — not yet"
    # A later sentence began, so sentence 1 is final even though only one pass
    # has confirmed it. This is what removes phrase_buffer's 3s of lag.
    out = c.update("The capital of France is Paris. And the")
    assert out == ["The capital of France is Paris."], out
    # The churning tail stays uncommitted...
    assert c.update("The capital of France is Paris. And the largest") == []
    # ...until it settles across two identical passes.
    t = "The capital of France is Paris. And the largest city is also Paris."
    assert c.update(t) == []
    assert c.update(t) == ["And the largest city is also Paris."]

    # Nothing is ever emitted twice — the failure the hybrid pipeline has.
    for _ in range(5):
        assert c.update(t) == []
    assert len(c.committed) == 2

    # Out-of-order protection: a stable sentence 2 must wait for sentence 1.
    c2 = SentenceCommitter(stable_passes=1)
    c2.update("aaa. bbb.")
    assert c2.committed == ["aaa.", "bbb."], c2.committed

    # flush() releases a final sentence that never settled.
    c3 = SentenceCommitter(stable_passes=3)
    c3.update("Only one thing here.")
    assert c3.committed == []
    assert c3.flush() == ["Only one thing here."]

    c4 = SentenceCommitter()
    c4.update("Done. Still going")
    assert c4.pending("Done. Still going") == "Still going"
    print("sentence_stability: all checks passed")

# ══ section: streaming_stt.py ════════════════════════════════════════════════════════════════
"""Incremental Whisper transcription with sentence-stability commits.

This is the engine validated by the JFK regression harness — 99.3% coverage /
0.7% duplication on 150s of clean speech, 98.0% / 2.2% on the full 17.8-minute
speech including applause, ~2 points behind a whole-file offline decode of the
same model. A flat audio buffer is re-decoded on a cadence, sentences commit
the moment they stop changing, and committed audio is TRIMMED out of the buffer
using Whisper's own segment timestamps. The `untrimmed` ledger tracks committed
words whose audio is still buffered, which makes re-heard-audio vs
genuinely-repeated-speech an exact distinction rather than a heuristic.

Why trim instead of slide: the committer tracks sentences by index in the
transcript. A sliding window shifts every index when audio falls off the front,
which silently drops pending sentences during long speech. Trimming keeps the
buffer a few seconds long no matter how long the speaker goes on, and each
decode stays cheap.

Consumers:
  * always_listening_sentence_pipeline.py — the demo this was proven in
  * core/preview.py                       — live display preview (fast model)
  * core/streaming/workers.py ASRWorker   — incremental ACCURATE transcription,
    so end-of-turn only decodes the tail instead of the whole turn

Thread-safety: feed() may be called from an audio thread while decode_pass()
runs on a worker. The buffer is locked; the model call itself is not (only one
caller may decode at a time).
"""


import re
import threading
from difflib import SequenceMatcher

import numpy as np


SAMPLE_RATE = 16000
T_UNITS = 0.01                    # whisper timestamps are centiseconds
# Whisper stretches the final segment's t1 to the window end and hallucinates
# completions there. Anything within this margin of the edge is not trusted:
# trims stop short of it, and the trailing sentence cannot stability-commit
# while it is edge-hot (jfk_regression --diff found both failure modes).
EDGE_GUARD_S = 1.0


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class IncrementalTranscriber:
    """feed() audio, decode_pass() on a cadence, flush() at end of turn."""

    def __init__(self, model, language: str = "en", stable_passes: int = 2,
                 sample_rate: int = SAMPLE_RATE, min_seconds: float = 1.0,
                 pad_ms: int = 250, max_seconds: float = 40.0,
                 soft_cap_seconds: float = 25.0) -> None:
        self.model = model
        self.language = language
        self.stable_passes = stable_passes
        self.sample_rate = sample_rate
        self.min_samples = int(sample_rate * min_seconds)
        self.max_samples = int(sample_rate * max_seconds)
        self.soft_cap_s = soft_cap_seconds
        self.pad = np.zeros(int(sample_rate * pad_ms / 1000), dtype=np.float32)

        self._lock = threading.Lock()
        self._buf = np.zeros(0, dtype=np.float32)
        self._since_decode = 0
        self.committer = SentenceCommitter(stable_passes=stable_passes)
        self.all_committed: list[str] = []    # across trims, whole turn
        self.pending = ""
        # THE LEDGER: committed words whose audio is still in the buffer. Their
        # audio sits at the buffer head in order, so re-decodes re-hear exactly
        # these words. Stripping against this ledger — and nothing else — makes
        # "same audio re-heard" vs "speaker genuinely repeated it" an exact
        # distinction: a genuine repeat's first copy is already trimmed away.
        self.untrimmed: list[str] = []
        self._last_raw = ""              # final-flush punctuation reconciliation
        self.decodes = 0
        self.debug: list[dict] | None = None  # set to [] to record trim/strip decisions

    # -- audio in ------------------------------------------------------------
    def feed(self, frame: np.ndarray) -> None:
        f = np.asarray(frame, dtype=np.float32).reshape(-1)
        with self._lock:
            self._buf = np.concatenate([self._buf, f])
            self._since_decode += f.size

    @property
    def buffer_seconds(self) -> float:
        with self._lock:
            return self._buf.size / self.sample_rate

    @property
    def undecoded_seconds(self) -> float:
        with self._lock:
            return self._since_decode / self.sample_rate

    def over_cap(self) -> bool:
        return self.buffer_seconds > self.max_samples / self.sample_rate

    # -- text out ------------------------------------------------------------
    def turn_text(self) -> str:
        return " ".join(self.all_committed)

    def display_text(self) -> str:
        """Committed + churning tail — what a live preview should show."""
        settled = self.turn_text()
        if settled and self.pending:
            return f"{settled} {self.pending}"
        return settled or self.pending

    # -- decode / commit / trim -----------------------------------------------
    @staticmethod
    def _tok_eq(a: str, b: str) -> bool:
        return a == b or (len(a) > 3 and a[:4] == b[:4])

    def _strip_untrimmed(self, text: str, *, include_tracked: bool = False
                         ) -> tuple[str, int, bool]:
        """Drop the re-heard committed words from the transcript head.

        Returns (kept_text, n_ledger_words_matched, aligned). aligned=False
        means the head could not be reconciled with the ledger at all — the
        caller must not run commit decisions on that transcript, or ledger
        words would re-commit as "new" sentences.
        """
        if not self.untrimmed:
            return text, 0, True
        # Words still tracked by this committer must remain in its transcript
        # so sentence indexes do not shift.  This matters when a sentence
        # commits but Whisper exposes no safe segment boundary and _trim()
        # cuts zero audio.  Only strip older ledger residue left by a previous
        # trim/reset; the current committer already de-duplicates its own
        # committed prefix by index.
        tracked = (0 if include_tracked else
                   len(compact(" ".join(self.committer.committed)).split()))
        strip_count = max(0, len(self.untrimmed) - tracked)
        if strip_count == 0:
            return text, 0, True
        limit = strip_count if include_tracked else min(60, strip_count)
        clean_token = lambda token: re.sub(r"[^a-z0-9]+", "", token.lower())
        want = [clean_token(w) for w in self.untrimmed[:limit]]
        head = compact(text).split()
        low = [clean_token(t) for t in head]
        if not low:
            return text, 0, True
        i = j = 0
        misses = 0
        hits = 0
        budget = max(2, len(want) // 3)
        while i < len(want) and j < len(low):
            if self._tok_eq(want[i], low[j]):
                hits += 1
                i += 1; j += 1
                continue
            misses += 1
            if misses > budget:
                break
            if i + 1 < len(want) and self._tok_eq(want[i + 1], low[j]):
                i += 2; j += 1
            elif j + 1 < len(low) and self._tok_eq(want[i], low[j + 1]):
                i += 1; j += 2
            else:
                i += 1; j += 1
        consumed = i
        aligned = hits >= max(1, int(consumed * 0.5)) and consumed >= min(
            len(want), 2)
        if not aligned:
            return text, 0, False
        return " ".join(head[j:]), consumed, True

    def decode_pass(self, abort_cb=None) -> list[str]:
        """One rolling decode. Returns sentences that just became final."""
        with self._lock:
            if self._buf.size < self.min_samples:
                return []
            snapshot = self._buf.copy()
            self._since_decode = 0
        if snapshot.size > self.soft_cap_s * self.sample_rate:
            # Stalled: nothing has committed for this long. The drain is the
            # stall handler, so it must run BEFORE the alignment gate below —
            # gating first meant an unaligned decode returned early, the drain
            # never fired, and commits froze permanently (run 9: 78.7%).
            return self._drain_old(snapshot, abort_cb)
        audio = np.concatenate([snapshot, self.pad])
        kwargs = {"language": self.language}
        if abort_cb is not None:
            kwargs["abort_callback"] = abort_cb
        segs = self.model.transcribe(audio, **kwargs)
        raw = compact(" ".join(s.text for s in segs))
        self._last_raw = raw
        text, _, aligned = self._strip_untrimmed(raw)
        self.decodes += 1
        if not aligned:
            # The ledger words are in this audio but the decode re-phrased them
            # beyond reconciliation. Committing now would duplicate them; wait
            # for a cleaner decode (the drain resolves true stalls).
            return []
        if not text:
            return []

        edge = snapshot.size - int(EDGE_GUARD_S * self.sample_rate)
        tail_hot = bool(segs) and int(segs[-1].t1 * T_UNITS * self.sample_rate) >= edge
        newly = self.committer.update(text, allow_tail_commit=not tail_hot)
        self.all_committed.extend(newly)
        for sentence in newly:
            self.untrimmed.extend(sentence.split())
        if newly:
            self._trim(segs, snapshot.size)
        self.pending = self.committer.pending(text)
        return newly

    def _drain_old(self, snapshot, abort_cb=None) -> list[str]:
        span = snapshot[: int(self.soft_cap_s * self.sample_rate)]
        kwargs = {"language": self.language}
        if abort_cb is not None:
            kwargs["abort_callback"] = abort_cb
        segs = self.model.transcribe(np.concatenate([span, self.pad]), **kwargs)
        guard = span.size - int(EDGE_GUARD_S * self.sample_rate)
        keep = []
        cut = 0
        for sg in segs:
            t1 = int(sg.t1 * T_UNITS * self.sample_rate)
            if t1 >= guard:
                break
            piece = compact(sg.text)
            if piece:
                keep.append(piece)
            cut = t1
        edge_words: list[str] = []
        if cut <= 0 or not keep:
            # Dense no-pause speech (podcasts) can decode the whole span as ONE
            # segment whose t1 sits past the guard — then no cut point exists,
            # the drain returns empty forever, commits freeze, and the 40s cap
            # fires with sentences still pending (seen live). Cut at the guard
            # and keep all the text; the few words describing the ~1s of audio
            # left behind go on the ledger so the next decode strips them
            # instead of re-committing them.
            keep = [compact(sg.text) for sg in segs if compact(sg.text)]
            if not keep:
                return []
            cut = guard
            # ponytail: positional — last 4 words ~ 1s of speech; the ledger's
            # skip/sub-tolerant walk absorbs the slack either way
            edge_words = compact(" ".join(keep)).split()[-4:]
        raw = compact(" ".join(keep))
        text, consumed, aligned = self._strip_untrimmed(raw)
        if not aligned and self.untrimmed:
            # The ledger words' audio sits at the buffer FRONT, inside the span
            # being cut — it is gone either way. If the re-decode cannot be
            # aligned word-for-word, drop their re-decode POSITIONALLY instead:
            # roughly the first len(ledger) words of the span correspond to that
            # audio, whatever the model renamed them to. Leaving the ledger
            # populated after the cut froze every later commit (coverage fell
            # to 78.7% in jfk_regression run 9).
            head = raw.split()
            text = " ".join(head[min(len(self.untrimmed), len(head)):])
        with self._lock:
            self._buf = self._buf[cut:]
        # Whatever the alignment said, the cut removed the front of the buffer,
        # which is where every ledger word's audio lived. The ledger is settled
        # — except a guard-cut, whose edge words' audio stays behind.
        self.untrimmed = edge_words
        if text:
            self.all_committed.append(text)
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)
        return [text] if text else []

    def _trim(self, segs, snapshot_size: int) -> None:
        """Cut committed audio at the last segment that verifiably lies inside
        the committed text. feed() only appends, so the snapshot's front is
        still the buffer's front and the cut index stays valid under concurrency.

        Consumption is by WORD COUNT, not verification. A per-segment fuzzy
        verification was tried and made 30% of trims cut nothing under ordinary
        re-phrasing drift — committed audio then piled up un-trimmed and the
        drain re-committed whole passages (17% duplication in jfk_regression).
        The failure the verification guarded against (cutting past the committed
        text on an inflated final t1) is already prevented by the edge guard,
        and boundary fuzz is handled by the untrimmed-words ledger.
        """
        # Everything this window has committed is re-hearable until cut, so it
        # ALL goes on the ledger first; the cut then consumes from the front.
        committed_words = compact(" ".join(self.committer.committed)).split()
        n_total = len(self.untrimmed)
        acc = 0
        cut = 0
        edge = snapshot_size - int(EDGE_GUARD_S * self.sample_rate)
        for sg in segs:
            words = compact(sg.text).lower().split()
            if not words or acc + len(words) > n_total:
                break
            t1_samples = int(sg.t1 * T_UNITS * self.sample_rate)
            if t1_samples >= edge:
                break                    # t1 inflated to the window end — do not
                                         # cut audio we may not have heard yet
            acc += len(words)
            cut = t1_samples
        if self.debug is not None:
            self.debug.append({
                "ev": "trim", "committed": " ".join(committed_words)[-70:],
                "cut_s": round(cut / self.sample_rate, 2),
                "ledger_left": " ".join(self.untrimmed[acc:acc + 8]),
                "segs": [compact(sg.text)[:40] for sg in segs][:6]})
        if cut <= 0:
            return
        cut = min(cut, snapshot_size)
        with self._lock:
            self._buf = self._buf[cut:]
        self.untrimmed = self.untrimmed[acc:]
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)

    def flush(self, abort_cb=None) -> list[str]:
        """End of turn: decode whatever remains, then release the tail.

        The edge guard does not apply here — the speaker has stopped, the
        buffer ends in real trailing silence, and committer.flush() releases
        the tail regardless.

        A buffer past the soft cap drains only its front span per pass, so
        flushing after ONE pass would drop everything behind the span. Drain
        until the buffer is under the cap, then decode the remainder.
        """
        newly: list[str] = []
        while self.buffer_seconds > self.soft_cap_s:
            got = self.decode_pass(abort_cb=abort_cb)
            newly += got
            if not got:
                break                       # no progress — do not spin
        final_newly = self.decode_pass(abort_cb=abort_cb)
        newly += final_newly
        # A complete endpoint decode may remove the punctuation present in its
        # previews. Sentence indexes then collapse, so reconcile by the words
        # whose audio is still buffered and keep the authoritative final tail.
        if final_newly:
            left = self.committer.flush()
        else:
            final_tail, _, aligned = self._strip_untrimmed(
                self._last_raw, include_tracked=True)
            left = ([compact(final_tail)] if aligned and compact(final_tail)
                    else self.committer.flush())
        self.all_committed.extend(left)
        self.pending = ""
        return newly + left

    def finalize_cached(self, *, decode_produced_commits: bool = False
                        ) -> list[str]:
        """Finalize a probable-end decode without re-decoding added silence.

        Valid only when endpointing confirms no voiced packet followed the
        speculative snapshot. If no usable snapshot exists, use normal flush.
        """
        if not self._last_raw:
            return self.flush()
        if decode_produced_commits:
            left = self.committer.flush()
        else:
            final_tail, _, aligned = self._strip_untrimmed(
                self._last_raw, include_tracked=True)
            left = ([compact(final_tail)] if aligned and compact(final_tail)
                    else self.committer.flush())
        self.all_committed.extend(left)
        self.pending = ""
        return left

    def hard_flush(self) -> list[str]:
        """Cap backstop: speech that never finishes a sentence. Never silent."""
        left = self.committer.flush()
        self.all_committed.extend(left)
        self.reset_audio()
        return left

    def reset_audio(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
            self._since_decode = 0
        self.committer = SentenceCommitter(stable_passes=self.stable_passes)
        self.pending = ""
        self.untrimmed = []
        self._last_raw = ""

    def reset(self) -> None:
        """New turn: clear everything including the committed text."""
        self.reset_audio()
        self.all_committed = []
        self.decodes = 0

# ══ section: preview.py ══════════════════════════════════════════════════════════════════════
"""Live transcript preview while the user is still speaking.

The turn-based apps transcribe once, at end of turn, so there is nothing on
screen while you talk — which reads as "it didn't hear me" and makes people stop
and restart. This runs a *second, cheap* decode over the in-progress buffer every
second and shows what it has so far, using the sentence-stability rule from the
always-listening pipelines: a sentence is settled once a later one has started,
or once it has been identical across consecutive decodes.

Two rules make this safe to bolt onto any app:

  * **It never feeds the LLM.** Preview text is display only. The turn is still
    transcribed properly at the end by the accurate model, and *that* is what
    reaches the model. Preview text may still be revised; acting on it would
    need a correction path that does not exist.
  * **It uses a small model** (base.en by default) on a separate thread, so it
    cannot slow the real pipeline. If it falls behind it drops a decode rather
    than queueing.

    preview = PreviewTranscriber(fast_model, on_update=ui_callback)
    preview.start()
    preview.feed(frame)      # every mic frame, while in speech
    preview.reset()          # at end of turn
"""


import threading
import time


CAPTURE_RATE = 16000


class PreviewTranscriber(threading.Thread):
    """Thin thread around core.streaming_stt.IncrementalTranscriber.

    The engine is the JFK-validated one: committed audio is trimmed out of the
    buffer via segment timestamps, so long turns never slide the window and
    never drop or misalign sentences — and each decode stays cheap because the
    buffer holds only the unfinished tail.
    """

    def __init__(self, model, on_update, every_s: float = 1.0,
                 min_seconds: float = 0.9, language: str = "en",
                 stable_passes: int = 2, max_seconds: float = 30.0) -> None:
        """on_update(committed: list[str], pending: str) — called from this thread."""
        super().__init__(daemon=True, name="PreviewTranscriber")
        self.engine = IncrementalTranscriber(
            model, language=language, stable_passes=stable_passes,
            sample_rate=CAPTURE_RATE, min_seconds=min_seconds,
            max_seconds=max_seconds)
        self.on_update = on_update
        self.every_s = every_s
        self._stop_event = threading.Event()
        self._decode_lock = threading.Lock()
        self.model_lock = threading.Lock()

    @property
    def decodes(self) -> int:
        return self.engine.decodes

    @property
    def committer(self):          # kept for existing tests/callers
        return self.engine.committer

    # -- called from the audio/VAD thread; must be cheap ------------------
    def feed(self, frame: np.ndarray) -> None:
        self.engine.feed(frame)

    def reset(self) -> None:
        """End of turn. The accurate transcript takes over from here."""
        with self._decode_lock:
            self.engine.reset()

    def finalize(self) -> str:
        """Flush the live engine once and return its exactly-once turn text."""
        with self._decode_lock, self.model_lock:
            self.engine.flush()
            text = self.engine.turn_text()
            self.engine.reset()
            return text

    def stop(self) -> None:
        self._stop_event.set()

    # -- worker ------------------------------------------------------------
    def run(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.every_s)
            if self.engine.undecoded_seconds < 0.3:
                continue
            try:
                with self._decode_lock, self.model_lock:
                    if self.engine.over_cap():
                        self.engine.hard_flush()
                    self.engine.decode_pass()
            except Exception:
                continue          # a failed preview must never disturb the app
            try:
                self.on_update(list(self.engine.all_committed),
                               self.engine.pending)
            except Exception:
                pass


def live_updater(ui):
    """Show the fast model's stable prefix and churning tail in LIVE.

    "Stable" is model-relative: the accurate final pass may revise it, so this
    callback deliberately never appends to COMMITTED or the session JSONL.
    """
    def update(committed: list[str], pending: str) -> None:
        # These are stable according to the FAST preview model, but the
        # accurate model may still revise them. Keep both zones in LIVE; only
        # the accurate end-of-turn transcript enters COMMITTED/session JSONL.
        if hasattr(ui, "live_transcript"):
            ui.live_transcript(committed, pending)
        else:                           # compatibility with tiny test UIs
            ui.provisional(render(committed, pending))
    return update


def render(committed: list[str], pending: str) -> str:
    """One line for a status display: settled text plus the churning tail."""
    settled = " ".join(committed)
    if settled and pending:
        return f"{settled} {pending}"
    return settled or pending

# ══ section: session_log.py ══════════════════════════════════════════════════════════════════
"""Shared append-only session log: everything HEARD, tagged by what became of it.

    context       sent to the LLM (real, addressed speech)
    noise         heard clearly, but not addressed to the agent (no wake phrase)
    environment   non-speech sound — clapping, clinking, typing
    gate_dropped  below the level gate (never transcribed; level recorded)
    stt_empty     admitted audio produced no transcript (seconds recorded)
    turn_sent     omni only — a turn's audio went to the model (no transcript
                  exists, so seconds are logged instead of text)
    reply         what the assistant said back

One jsonl file per day, shared by every app (each line carries the app name),
so a whole day's audio environment can be audited or grouped by kind.
Nothing heard is ever silently discarded.
"""


import datetime
import json
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"


def session_log(app: str):
    """Returns (path, log). log(kind, text="", **extra) appends one line."""
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"voice_{datetime.date.today().isoformat()}.jsonl"
    fh = open(path, "a", buffering=1)
    write_lock = threading.Lock()

    def log(kind: str, text: str = "", **extra) -> None:
        line = json.dumps({"t": time.time(), "app": app, "kind": kind,
                           "text": text, **extra}, ensure_ascii=False) + "\n"
        with write_lock:
            fh.write(line)
    return path, log




# ── config ─────────────────────────────────────────────────────────────
LLM_MODEL_PATH = LLMS[DEFAULT_LLM].path   # --llm overrides

# Two-pass STT: fast model runs every phrase to detect wake words. Accurate
# model only re-transcribes when wake matches or we're in follow-up mode,
# so we don't pay its cost on background noise.
STT_FAST = "base.en"
STT_ACCURATE = STT_FAST

KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"

# Wake phrases and fuzzy matching live in voice_gate.py so voice_sequential_fullduplex.py gates
# identically. Tune WAKE_MATCH_THRESHOLD there.
FOLLOWUP_WINDOW_S = 15.0      # listen this long after a reply, no wake needed

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000   # 480 samples
VAD_AGGRESSIVENESS = 3       # 3 = most aggressive; 2 lets too much room noise through

PRE_ROLL_MS = 240             # capture speech onset
POST_PADDING_MS = 250         # capture trailing word — fixes "what time is it" → "time is in"
SILENCE_HANGOVER_MS = 700     # full silence needed MID-sentence (hesitation)
# Once the live preview has SETTLED at least one sentence, the very next
# micro-gap (one unvoiced 30ms frame — nearly every word boundary has one)
# commits the turn. Requiring a longer pause here starved the trigger on
# broadcast audio and let turns ride all the way to the 45s ceiling even
# though completed sentences were sitting in the window.     # match the working command listener
MIN_SPEECH_MS = 400
# Soft cap: past this the turn splits at the next natural pause. The HARD cap
# fires only after this many seconds with ZERO quiet frames (continuous TV /
# music) and force-SPLITS the turn — all audio on both sides is still
# transcribed and processed; only the seam may land mid-word. It bounds how
# much audio a single accurate-STT decode has to chew, never discards any.
MAX_SPEECH_MS = 30000
HARD_MAX_SPEECH_MS = 45000

SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Answer in 1–2 short sentences "
    "in plain conversational English. No markdown, no code blocks, no "
    "emojis, no lists. If you don't know, say so briefly."
)

# Cap rolling chat history so prompt size (and latency) stays bounded.
MAX_HISTORY_TURNS = 8


# ── short chime so the user knows we're listening ──────────────────────
def make_beep(freq: float = 880.0, duration_ms: int = 110,
              sr: int = 24000, amp: float = 0.25) -> np.ndarray:
    n = int(sr * duration_ms / 1000)
    t = np.arange(n) / sr
    # short fade-in/out to avoid clicks
    env = np.minimum(np.minimum(t / 0.01, 1.0), (duration_ms / 1000 - t) / 0.01).clip(0, 1)
    return (amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


BEEP = make_beep()
DOUBLE_BEEP = np.concatenate([
    make_beep(freq=660, duration_ms=80),
    np.zeros(int(24000 * 0.05), dtype=np.float32),
    make_beep(freq=880, duration_ms=80),
])


# ── audio capture ──────────────────────────────────────────────────────
class MicStream:
    """sounddevice InputStream → frame queue, with a pause flag for TTS."""

    def __init__(self) -> None:
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        self.paused = False
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=FRAME_SAMPLES, callback=self._cb,
        )

    def _cb(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        if self.paused or frames != FRAME_SAMPLES:
            return
        self.q.put(indata.copy())

    def __enter__(self) -> "MicStream":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()

    def drain(self) -> None:
        with self.q.mutex:
            self.q.queue.clear()


# ── VAD worker thread ──────────────────────────────────────────────────
class VadWorker(threading.Thread):
    """Reads audio blocks, runs VAD, accumulates phrases, fast-transcribes,
    then pushes (audio_float32, fast_transcript) onto phrase_queue.
    """

    def __init__(self, mic: MicStream, fast_model,
                 phrase_queue: queue.Queue, stop_event: threading.Event) -> None:
        super().__init__(daemon=True)
        self.mic = mic
        self.fast_model = fast_model
        self.stt_lock = threading.Lock()
        self.phrase_queue = phrase_queue
        self.stop_event = stop_event
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

        self.silence_blocks_to_end = max(1, SILENCE_HANGOVER_MS // FRAME_MS)
        self.min_speech_blocks = max(1, MIN_SPEECH_MS // FRAME_MS)
        self.max_speech_blocks = max(self.min_speech_blocks, MAX_SPEECH_MS // FRAME_MS)
        self.hard_max_blocks = max(self.max_speech_blocks,
                                   HARD_MAX_SPEECH_MS // FRAME_MS)
        self.truncated = False        # set when the hard ceiling actually cut you
        self.pre_roll_blocks = max(0, PRE_ROLL_MS // FRAME_MS)
        self.post_pad_samples = int(SAMPLE_RATE * POST_PADDING_MS / 1000)

        # Seeded by calibrate_noise_floor(); then ADAPTIVE — a slow EMA over
        # frames the VAD calls non-speech tracks the room as it changes (HVAC
        # cycling, TV volume, time of day), clamped to the same floor/ceiling
        # as calibration so it can never run away.
        self.noise_threshold = 0.0
        self._room_ema: float | None = None
        # Optional live preview — display only, never sent to the LLM.
        self.preview = None
        self.on_drop = None       # callback(seconds, level, threshold)
        self.on_environment = None  # callback(marker_text) — clapping, typing…
        self.on_untranscribed = None  # callback(seconds, reason)

        # Exposed so the main loop can avoid expiring the follow-up window
        # while the user is still mid-sentence.
        self.in_speech = False

    def _is_speech(self, chunk: np.ndarray) -> bool:
        pcm = (chunk[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        return self.vad.is_speech(pcm, SAMPLE_RATE)

    def _finalize(self, chunks: list[np.ndarray], fast_text: str = "") -> None:
        audio = np.concatenate(chunks, axis=0).astype(np.float32).reshape(-1)
        audio = np.concatenate([audio, np.zeros(self.post_pad_samples, dtype=np.float32)])

        # Level gate before STT: across-the-room audio never costs us a
        # transcription, which is what keeps the assistant responsive in noise.
        level = speech_level(audio, FRAME_SAMPLES)
        if level < self.noise_threshold:
            if self.on_drop is not None:
                self.on_drop(len(audio) / SAMPLE_RATE, level, self.noise_threshold)
            return

        text = fast_text.strip()
        stt_error = ""
        if not text:
            try:
                with self.stt_lock:
                    segments = self.fast_model.transcribe(audio, language="en")
                text = " ".join(s.text for s in segments).strip()
            except Exception as exc:
                print(f"[stt-fast] {exc}", file=sys.stderr)
                stt_error = f"{type(exc).__name__}: {exc}"
        if not text:
            if self.on_untranscribed is not None:
                self.on_untranscribed(len(audio) / SAMPLE_RATE,
                                      stt_error or "empty transcript")
            return
        if is_non_speech(text):
            # Environmental sound — clapping, clinking, typing. Whisper renders
            # these as bracketed markers. Its own category: heard and logged,
            # never sent toward the LLM, never silently discarded.
            if self.on_environment is not None:
                self.on_environment(text)
            return
        self.phrase_queue.put((audio, text))

    def run(self) -> None:
        pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_blocks)
        speech: list[np.ndarray] = []
        speech_blocks = 0
        silent_blocks = 0
        in_speech = False

        while not self.stop_event.is_set():
            try:
                chunk = self.mic.q.get(timeout=0.3)
            except queue.Empty:
                continue

            is_speech = self._is_speech(chunk)

            if is_speech:
                if not in_speech:
                    speech = list(pre_roll)
                    speech_blocks = len(speech)
                    silent_blocks = 0
                    in_speech = True
                    if self.preview is not None and speech:
                        self.preview.feed(np.concatenate(speech)[:, 0])
                speech.append(chunk)
                speech_blocks += 1
                silent_blocks = 0
                if self.preview is not None:
                    self.preview.feed(chunk[:, 0])
            elif in_speech:
                speech.append(chunk)
                silent_blocks += 1
                if self.preview is not None:
                    self.preview.feed(chunk[:, 0])
            else:
                pre_roll.append(chunk)
                # Adapt to the room on non-speech frames only.
                lvl = float(np.sqrt(np.mean(np.square(chunk[:, 0]))))
                self._room_ema = (lvl if self._room_ema is None
                                  else 0.995 * self._room_ema + 0.005 * lvl)
                self.noise_threshold = min(
                    max(self._room_ema * NOISE_MARGIN, MIN_SPEECH_RMS),
                    MAX_SPEECH_RMS)

            # Publish speech state once we've seen enough sustained voice
            # to be confident this isn't a noise blip.
            self.in_speech = in_speech and speech_blocks >= self.min_speech_blocks

            # End of turn is decided by *silence*, never by a stopwatch. Past
            # the soft cap we still wait for the next pause (a single quiet
            # frame is enough) so a long sentence is split between words rather
            # than through one. Only the hard ceiling cuts unconditionally.
            over_soft = speech_blocks >= self.max_speech_blocks
            at_hard = speech_blocks >= self.hard_max_blocks
            # Sentence-aware endpointing: a settled sentence + a breath ends
            # the turn; only a MID-sentence pause needs the full hangover.
            sentence_ready = (
                self.preview is not None
                and bool(self.preview.engine.all_committed))
            phrase_done = in_speech and speech_blocks >= self.min_speech_blocks and (
                silent_blocks >= self.silence_blocks_to_end
                or (sentence_ready and silent_blocks >= 1)
                or (over_soft and silent_blocks >= 1)
                or at_hard
            )
            if at_hard:
                self.truncated = True
            if phrase_done:
                preview_text = self.preview.finalize() if self.preview is not None else ""
                self._finalize(speech, preview_text)
                speech = []
                speech_blocks = 0
                silent_blocks = 0
                in_speech = False
                self.in_speech = False
                pre_roll.clear()


# ── LLM ────────────────────────────────────────────────────────────────
def load_llm():
    from llama_cpp import Llama
    print(f"[llm] loading {LLM_MODEL_PATH.name}...", flush=True)
    t0 = time.perf_counter()
    llm = Llama(
        model_path=str(LLM_MODEL_PATH),
        n_ctx=4096, n_gpu_layers=-1, flash_attn=True, offload_kqv=True,
        verbose=False,
    )
    print(f"[llm] loaded in {time.perf_counter()-t0:.1f}s, warming up...", flush=True)
    llm.create_chat_completion(
        messages=[{"role": "user", "content": "hi"}], max_tokens=1, temperature=0.0,
    )
    print("[llm] ready", flush=True)
    return llm


def trim_history(history: list[dict], max_turns: int = MAX_HISTORY_TURNS) -> list[dict]:
    # history[0] is system; the rest is user/assistant pairs appended by think().
    # Slicing from the tail in pairs keeps the boundary on a user message.
    if len(history) <= 1 + max_turns * 2:
        return history
    return history[:1] + history[-max_turns * 2:]


def think(llm, history: list[dict], user_text: str) -> str:
    history.append({"role": "user", "content": user_text})
    out = llm.create_chat_completion(
        messages=history, max_tokens=200, temperature=0.7, top_p=0.95,
    )
    reply = out["choices"][0]["message"]["content"].strip()
    history.append({"role": "assistant", "content": reply})
    return clean_for_tts(reply)


def clean_for_tts(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"^[\-\*\d\.\)]+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


# ── TTS ────────────────────────────────────────────────────────────────
def load_tts():
    from kokoro import KPipeline
    print("[tts] loading Kokoro...", flush=True)
    t0 = time.perf_counter()
    pipe = KPipeline(lang_code=KOKORO_LANG)
    list(pipe("Ready.", voice=KOKORO_VOICE))     # warm-up
    print(f"[tts] ready ({time.perf_counter()-t0:.1f}s)", flush=True)
    return pipe


def drain_phrase_queue(q: queue.Queue) -> None:
    """Discard phrases the VAD finalized while we were speaking — otherwise the
    follow-up window would treat stale buffered speech as a fresh command."""
    with q.mutex:
        q.queue.clear()


def play_audio_with_mic_paused(mic: MicStream, audio: np.ndarray, sr: int = 24000) -> None:
    """Play to speakers; mic capture is suppressed so we don't transcribe ourselves."""
    mic.paused = True
    try:
        sd.play(audio, samplerate=sr)
        sd.wait()
        time.sleep(0.12)              # let the speaker drain
    finally:
        mic.drain()
        mic.paused = False


def speak(pipe, mic: MicStream, text: str, sr: int = 24000) -> None:
    """Stream Kokoro chunks: play chunk N while chunk N+1 is still generating.
    Mic stays paused across the whole stream so we never re-capture our own voice.
    """
    if not text:
        return
    mic.paused = True
    started = False
    try:
        for r in pipe(text, voice=KOKORO_VOICE):
            if r.audio is None:
                continue
            chunk = np.asarray(r.audio, dtype=np.float32)
            if started:
                sd.wait()  # block until previous chunk finishes
            sd.play(chunk, samplerate=sr)
            started = True
        if started:
            sd.wait()
            time.sleep(0.12)              # let the speaker drain
    finally:
        mic.drain()
        mic.paused = False


# ── main loop ──────────────────────────────────────────────────────────
def warm_stt(model, label: str) -> None:
    """Prime pywhispercpp once so the first real phrase avoids setup latency."""
    warm_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
    print(f"[{label}] warming up...", flush=True)
    t0 = time.perf_counter()
    try:
        list(model.transcribe(warm_audio, language="en"))
    except Exception as exc:
        # Some Whisper builds dislike pure silence. Startup should continue;
        # the model is still loaded and ready for normal speech.
        print(f"[{label}] warm-up skipped: {exc}", file=sys.stderr, flush=True)
    else:
        print(f"[{label}] primed ({time.perf_counter()-t0:.1f}s)", flush=True)


def _try_get(q: queue.Queue):
    try:
        return q.get(timeout=0.1)
    except queue.Empty:
        return None


def _stt_path(name: str) -> Path:
    """Where pywhispercpp caches its ggml models, for the hardware report."""
    return (Path.home() / "Library/Application Support/pywhispercpp/models"
            / f"ggml-{name}.bin")

def _session_log():
    return session_log(Path(__file__).stem)


def main() -> int:
    global LLM_MODEL_PATH
    llm_choice = parse_llm(__doc__.splitlines()[0] if __doc__ else "")
    LLM_MODEL_PATH = llm_choice.path

    # Same hardware report the benchmark prints: confirms the app is alive and
    # tells you what it is actually running before any model loads.
    console = Console()
    console.rule("[bold]Hardware")
    hw = hardware_describe(
        llm_model=LLM_MODEL_PATH,
        extra={"stt_fast": _stt_path(STT_FAST), "stt_accurate": _stt_path(STT_ACCURATE)})
    console.print(hardware_render(hw))
    console.print()
    hardware_require(hw)      # stop here rather than dying inside llama.cpp


    from pywhispercpp.model import Model as STTModel

    print(f"[stt-fast] loading {STT_FAST}...", flush=True)
    t0 = time.perf_counter()
    fast_stt = STTModel(
        STT_FAST, print_realtime=False, print_progress=False,
        single_segment=False, no_context=True,
        context_params={"use_gpu": True, "flash_attn": True},
    )
    print(f"[stt-fast] ready ({time.perf_counter()-t0:.1f}s)", flush=True)
    warm_stt(fast_stt, "stt-fast")

    # Fast and final passes are serialized, so one Base context serves both.
    # Loading medium + full Turbo used ~3 GB of duplicate encoder residency.
    accurate_stt = fast_stt
    print("[stt-accurate] reusing warmed Base Metal context", flush=True)
    shared_stt_lock = threading.Lock()

    def transcribe_accurate(audio: np.ndarray) -> str:
        with shared_stt_lock:
            segments = accurate_stt.transcribe(audio, language="en")
        return " ".join(s.text for s in segments).strip()

    llm = load_llm()
    tts = load_tts()
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    phrase_queue: queue.Queue[tuple[np.ndarray, str]] = queue.Queue()
    stop_event = threading.Event()

    ui = VoiceUI("Jaeger Voice  ·  SEQUENTIAL · HALF-DUPLEX  [A0]",
                 ["Wake phrase", "Mode", "Model", "Microphone", "Gate"],
                 ["Speech detected", "End-of-turn", "Reply ready", "Spoken"],
                 footer=f"say: {', '.join(WAKE_PHRASES[:3])} …   ·   Ctrl-C to quit")
    log_path, log_event = _session_log()
    ui.status("Wake phrase", "hey jaeger", "cyan")
    ui.status("Mode", "WAKE — say the wake phrase", "yellow")
    ui.status("Model", f"{STT_ACCURATE} + {llm_choice.label} + kokoro", "green")
    ui.status("Microphone", "ACTIVE", "green")

    state = "WAKE"           # "WAKE" or "FOLLOWUP"
    followup_deadline = 0.0

    with ui.live(), MicStream() as mic:
        # Measure the room before the worker starts consuming the queue. Leave
        # the TV on for this — the point is to learn what "background" sounds
        # like here, so anything at that level never reaches STT.
        print("[gate] calibrating room noise, stay quiet...", flush=True)
        threshold = calibrate_noise_floor(
            lambda: _try_get(mic.q), FRAME_SAMPLES, label="gate"
        )
        mic.drain()

        worker = VadWorker(mic, fast_stt, phrase_queue, stop_event)
        worker.stt_lock = shared_stt_lock
        # Live preview while you talk, on the fast model. Display only — the
        # accurate pass at end-of-turn is what actually reaches the LLM.
        worker.on_environment = lambda t: (
            ui.said("Environment", t),
            log_event("environment", t))
        worker.on_drop = lambda secs, lvl, thr: (
            ui.note(f"gate dropped {secs:.1f}s (level {lvl:.3f} < {thr:.3f}) "
                    f"— gate adapts; --threshold overrides"),
            log_event("gate_dropped", seconds=round(secs, 1),
                      level=round(lvl, 4), threshold=round(thr, 4)))
        worker.on_untranscribed = lambda secs, reason: (
            ui.note(f"STT returned no text for {secs:.2f}s ({reason})"),
            log_event("stt_empty", seconds=round(secs, 2), reason=reason))
        worker.preview = PreviewTranscriber(
            fast_stt, on_update=live_updater(ui))
        worker.preview.model_lock = worker.stt_lock
        worker.preview.start()
        worker.noise_threshold = threshold
        worker.start()
        try:
            while True:
                # Follow-up timeout?  Don't expire while the user is still
                # mid-sentence — wait for them to finish, then we'll see the
                # phrase on the queue and treat it as a follow-up command.
                # Begin speaking inside the window and it holds for as long as
                # you keep going — the deadline is about when you *start*, not
                # when you finish. worker.in_speech keeps it open mid-sentence.
                if state == "FOLLOWUP" and worker.in_speech:
                    followup_deadline = max(followup_deadline,
                                            time.time() + FOLLOWUP_WINDOW_S)
                if (
                    state == "FOLLOWUP"
                    and time.time() > followup_deadline
                    and not worker.in_speech
                ):
                    ui.status("Mode", "WAKE — say the wake phrase", "yellow"); ui.phase("waiting for wake phrase")
                    state = "WAKE"

                try:
                    audio, fast_text = phrase_queue.get(timeout=0.3)
                except queue.Empty:
                    ui.status("Gate",
                              f"{worker.noise_threshold:.3f} (adaptive)", "green")
                    ui.tick()
                    continue
                ui.reset_latency()
                ui.latency("Speech detected", 0)
                ui.latency("End-of-turn", 0)

                ui.provisional(fast_text); ui.phase("transcribing…")
                if worker.truncated:
                    worker.truncated = False
                    ui.note(f"{HARD_MAX_SPEECH_MS/1000:.0f}s with no pause — "
                            f"turn SPLIT here and processing continues; "
                            f"nothing was dropped (the seam may fall mid-word)")

                # Decide whether to act
                heard_wake = None
                if state == "FOLLOWUP":
                    # In follow-up window any utterance counts as a command.
                    command = transcribe_accurate(audio).strip() or fast_text
                    ui.phase("thinking…")
                else:
                    matched, remainder = find_wake(fast_text)
                    heard_wake = find_wake_phrase(fast_text) if matched else None
                    if heard_wake:
                        ui.wake(heard_wake)
                        ui.phase("wake heard — listening for your command")
                    if not matched:
                        # Heard clearly — just not addressed to the agent. The
                        # wake phrase + follow-up window ARE the noise/context
                        # discriminator, so this is a decision, not a loss:
                        # show it dim, log it as noise, and say why.
                        stub = fast_text if len(fast_text) <= 90 else \
                            fast_text[:90] + "…"
                        ui.said("Ignored (no wake)", stub)
                        ui.provisional("")
                        ui.phase("heard, not addressed to me — say the wake phrase")
                        log_event("noise", fast_text)
                        continue

                    # Re-transcribe the same audio with the accurate model
                    accurate_text = transcribe_accurate(audio)
                    a_matched, a_remainder = find_wake(accurate_text)
                    if a_matched and (a_remainder or not remainder):
                        remainder = a_remainder
                        ui.provisional(accurate_text)

                    if remainder:
                        command = remainder
                    else:
                        # Wake-only utterance: chime, then wait for the command.
                        play_audio_with_mic_paused(mic, BEEP)
                        drain_phrase_queue(phrase_queue)
                        try:
                            cmd_audio, cmd_fast = phrase_queue.get(timeout=6.0)
                        except queue.Empty:
                            ui.note("no command heard — back to wake"); ui.phase("waiting for wake phrase")
                            continue
                        ui.provisional(cmd_fast)
                        command = transcribe_accurate(cmd_audio).strip() or cmd_fast

                if not command:
                    continue

                # Think
                ui.said("User", command,
                        highlight=heard_wake if state == "WAKE" else None)
                log_event("context", command, followup=state == "FOLLOWUP")
                ui.phase("thinking…")
                t0 = time.perf_counter()
                reply = think(llm, history, command)
                history = trim_history(history)
                ui.said("Assistant", reply); ui.latency("Reply ready", (time.perf_counter()-t0)*1000); ui.phase("speaking…")

                # Speak (mic paused inside)
                spoke_t = time.perf_counter()
                speak(tts, mic, reply)
                ui.latency("Spoken", (time.perf_counter() - spoke_t) * 1000)
                drain_phrase_queue(phrase_queue)

                # Open follow-up window
                play_audio_with_mic_paused(mic, DOUBLE_BEEP)
                drain_phrase_queue(phrase_queue)
                state = "FOLLOWUP"
                followup_deadline = time.time() + FOLLOWUP_WINDOW_S
                ui.status("Mode", f"FOLLOW-UP — {FOLLOWUP_WINDOW_S:.0f}s, no wake phrase needed", "green"); ui.phase("listening")

        except KeyboardInterrupt:
            pass
            return 0
        finally:
            stop_event.set()
            worker.join(timeout=2)
            if worker.preview is not None:
                worker.preview.stop()
                worker.preview.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
