"""Verified core layers: wake matcher, TurnAnnotator, HOLDING, guards, [context:] line.

Extracted 2026-09-02 from the VoiceLLM canonical implementation.
Keep in sync by re-extraction; behavior must stay byte-equivalent."""
from __future__ import annotations

import datetime
import re
from difflib import SequenceMatcher

import numpy as np

from .policy import agent_asked_question, looks_complete, normalize

# ═══════════════════════════════════════════════════════════════════════════
# section: verified family layers — VENDORED from Voice LLm production
# 01–04 (2026-09-01 state: every live fix and the external review included).
# A COPY on purpose; re-vendor to update.
# ═══════════════════════════════════════════════════════════════════════════

WAKE_NAME_THRESHOLD = 0.78
WAKE_PREFIXES = ("ok", "okay", "hey", "yo", "hi")
WAKE_NAMES = ("whisper", "jaeger", "assistant", "computer", "google",
              "siri", "alexa", "jarvis", "gemini", "claude",
              "yeager", "yager", "jager", "yaeger", "wisper")


def match_wake(text: str) -> tuple[str, str] | None:
    """Return the wake phrase as heard and the command after it."""
    words = normalize(text).split()
    for index in range(len(words) - 1):
        prefix, name = words[index:index + 2]
        if prefix not in WAKE_PREFIXES:
            continue
        best_name_score = max(
            SequenceMatcher(None, name, expected).ratio()
            for expected in WAKE_NAMES
        )
        if name in WAKE_NAMES or best_name_score >= WAKE_NAME_THRESHOLD:
            return " ".join(words[index:index + 2]), \
                " ".join(words[index + 2:]).strip()
    # bare-name address (first or last word) wakes without a prefix
    for i in ((0, len(words) - 1) if words else ()):
        if words[i] in WAKE_NAMES:
            rest = words[1:] if i == 0 else words[:-1]
            return words[i], " ".join(rest).strip()
    return None

class TurnAnnotator:
    """Per-turn context: speaker cluster, completeness, derived signals."""

    def __init__(self, max_speakers: int = 4, new_speaker_dist: float = 1.0):
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        self.max_speakers = max_speakers
        # distance 1.0 ≈ the speaker boundary in _fp_distance units — THE
        # tuning point (v1's cosine 0.985 could never fire: measured
        # 0.990–0.998 between different live voices, 2026-08-31 log)
        self.new_speaker_dist = new_speaker_dist

    @staticmethod
    def fingerprint(audio: np.ndarray) -> np.ndarray:
        """v2 acoustic fingerprint — REPLACE ME with a trained speaker head.

        v1 scored cosine similarity over six bounded all-positive features
        and measured 0.990–0.998 between two clearly different live voices
        (122 Hz vs 219 Hz medians, 2026-08-31 log): vectors sharing
        near-constant components cosine to ~1.0 no matter who talks. v2
        keeps only gain-invariant features (AGC erases level cues) in an
        interpretable space scored by weighted distance, pitch first:
        [log2 pitch, zcr, centroid kHz, rolloff kHz, pitch spread oct].
        """
        x = np.asarray(audio, dtype=np.float32).reshape(-1)
        frames = x[: len(x) // 480 * 480].reshape(-1, 480)
        rms = np.sqrt((frames ** 2).mean(axis=1))
        voiced = frames[rms > max(0.01, np.percentile(rms, 60))]
        if len(voiced) < 4:
            voiced = frames
        zcrs, cents, rolls, pitches = [], [], [], []
        for fr in voiced[:100]:
            zcrs.append(float(np.mean(np.abs(np.diff(np.sign(fr))) > 0)))
            spec = np.abs(np.fft.rfft(fr * np.hanning(len(fr))))
            freqs = np.fft.rfftfreq(len(fr), 1 / 16000)
            cents.append(float((spec * freqs).sum() / max(spec.sum(), 1e-9)))
            cum = np.cumsum(spec)
            rolls.append(float(freqs[int(np.searchsorted(cum, 0.85 * cum[-1]))]))
            ac = np.correlate(fr, fr, "full")[len(fr) - 1:]
            lo, hi = 16000 // 400, 16000 // 70          # 70–400 Hz pitch band
            if hi > lo:
                pitches.append(float(16000 / (lo + int(np.argmax(ac[lo:hi])))))
        p = np.asarray(pitches if pitches else [150.0], dtype=np.float32)
        p_med = float(np.median(p))
        p_spread_oct = float(np.log2(max(np.percentile(p, 90), 1.0)
                                     / max(np.percentile(p, 10), 1.0)))
        # prosody intermediates ride along — computed anyway, free to keep
        TurnAnnotator._last_prosody = {
            "pitch_hz": round(p_med, 1),
            "pitch_range_hz": round(float(np.ptp(p)), 1),
            "energy_db": round(20 * float(np.log10(
                np.sqrt((x ** 2).mean()) + 1e-9)), 1),
        }
        return np.asarray([np.log2(max(p_med, 1.0)), float(np.mean(zcrs)),
                           float(np.mean(cents)) / 1000.0,
                           float(np.mean(rolls)) / 1000.0,
                           p_spread_oct], dtype=np.float32)

    # per-axis scale = expected within-speaker spread across turns; weights
    # put pitch first (the one axis the live data proved discriminative)
    _FP_SCALE = np.asarray([0.25, 0.08, 0.40, 0.80, 0.30], dtype=np.float32)
    _FP_W = np.asarray([3.0, 1.0, 1.0, 0.5, 0.5], dtype=np.float32)

    @classmethod
    def _fp_distance(cls, a: np.ndarray, b: np.ndarray) -> float:
        z = (a - b) / cls._FP_SCALE
        return float(np.sqrt(float((cls._FP_W * z * z).sum())
                     / float(cls._FP_W.sum())))

    def speaker(self, audio: np.ndarray) -> tuple[int, float]:
        """-> (speaker index starting at 1, confidence 0..1).

        conf is 1/(1+d): 1.0 on a perfect match, 0.5 AT the new-speaker
        boundary — honest, unlike v1's cosine which pinned every turn ≥0.99.
        """
        v = self.fingerprint(audio)
        self._last_fp = v
        if not self.centroids:
            self.centroids.append(v)
            self.counts.append(1)
            return 1, 1.0
        dists = [self._fp_distance(v, c) for c in self.centroids]
        best = int(np.argmin(dists))
        d = dists[best]
        if d <= self.new_speaker_dist or len(self.centroids) >= self.max_speakers:
            n = self.counts[best]
            self.centroids[best] = (self.centroids[best] * n + v) / (n + 1)
            self.counts[best] += 1
            return best + 1, round(1.0 / (1.0 + d), 3)
        self.centroids.append(v)
        self.counts.append(1)
        return len(self.centroids), 1.0

    _DISFLUENCIES = re.compile(
        r"\b(um+|uh+|erm+|hmm+|like|you know|i mean|sort of|kind of)\b", re.I)
    _STUTTER = re.compile(r"\b(\w+)( \1\b)+", re.I)

    def annotate(self, turn, text: str, prev_end_at: float | None) -> dict:
        spk, conf = self.speaker(turn.audio)
        complete = looks_complete(text)
        prosody = getattr(TurnAnnotator, "_last_prosody", {})
        x = np.asarray(turn.audio, dtype=np.float32).reshape(-1)
        clip_pct = round(100 * float(np.mean(np.abs(x) > 0.985)), 2)
        # SNR: speech level vs the quietest decile of the turn's own frames
        fr = x[: len(x) // 480 * 480].reshape(-1, 480)
        rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
        snr_db = round(20 * float(np.log10(
            np.percentile(rms, 80) / max(np.percentile(rms, 10), 1e-6))), 1)
        wake = match_wake(text)
        # per-speaker session ledger — free running aggregates
        led = self.__dict__.setdefault("_ledger", {})
        rec = led.setdefault(spk, {"turns": 0, "speech_ms": 0, "words": 0})
        rec["turns"] += 1
        rec["speech_ms"] += turn.speech_ms
        rec["words"] += len(text.split())
        total_ms = sum(r["speech_ms"] for r in led.values()) or 1
        return {
            "text": text,
            "speaker": spk,
            "speaker_conf": round(conf, 3),
            "complete": complete,
            "holding": not complete,       # the do-not-respond-yet signal
            "question": text.rstrip().endswith("?")
                        or bool(agent_asked_question(text)),
            "t_start": round(turn.started_at, 2),
            "speech_ms": turn.speech_ms,
            "pause_before_ms": (round((turn.started_at - prev_end_at) * 1000)
                                if prev_end_at else None),
            "wpm": round(len(text.split()) / max(turn.speech_ms / 60000.0, 1e-6)),
            # ── zero-cost context tier 2 ──
            "iso_time": datetime.datetime.now().isoformat(timespec="seconds"),
            "prosody": prosody,
            "disfluencies": len(self._DISFLUENCIES.findall(text)),
            "stutter": bool(self._STUTTER.search(text)),
            "addressed": wake[0] if wake else None,
            "latched": (prev_end_at is not None
                        and (turn.started_at - prev_end_at) < 0.15),
            "audio_health": {"clipping_pct": clip_pct, "snr_db": snr_db},
            "voiceprint": [round(float(a), 3)
                           for a in getattr(self, "_last_fp", [])],
            "session": {str(k): {**v, "talk_share": round(
                v["speech_ms"] / total_ms, 2)} for k, v in led.items()},
        }

HOLD_MAX_S = 8.0         # an incomplete turn holds the floor this long for a
                         # continuation; abandoned thoughts still flush after

_STOCK_HALLUCINATIONS = {"thank you", "thanks", "thank you for watching",
                         "thanks for watching", "you", "bye", "okay",
                         "thank you bye", "good luck"}


_SELF_VOICE = {"fp": None, "until": 0.0}
SELF_ECHO_DIST = 0.8          # tighter than the speaker boundary (1.0)
SELF_ECHO_WINDOW_S = 2.5      # echo residue only exists near playback


def is_own_voice_echo(voiceprint, now: float) -> bool:
    """Live 2026-09-01: jaeger's own reply leaked through the AEC and was
    transcribed as user turns — the phantom turns sat at 192–241 Hz
    (Kokoro) while every real speaker sat at 102–183 Hz. We SYNTHESIZE the
    reply audio, so we can fingerprint our own voice exactly: reject turns
    near playback whose voiceprint matches it. Ceiling stated honestly: a
    human whose voice sits within 0.8 of Kokoro's fingerprint would be
    suppressed for 2.5 s after each reply."""
    # `now` must be the turn's START time, not judgment time: the first
    # reply of a session leaks hardest (cold AEC) and its echo turn STARTED
    # inside the window but was JUDGED ~4 s later — after capture, the
    # conversation-padded endpoint, and the decode — once the window had
    # expired (live 2026-09-01: "S3 · 204Hz · 800wpm" ghost of reply #1).
    if _SELF_VOICE["fp"] is None or not voiceprint:
        return False
    if now >= _SELF_VOICE["until"]:
        return False
    return TurnAnnotator._fp_distance(
        np.asarray(voiceprint, dtype=np.float32),
        _SELF_VOICE["fp"]) < SELF_ECHO_DIST


def is_echo_garble(text: str, wpm) -> bool:
    """Physically implausible speech density = decode of AEC residue.
    Live 2026-09-01: ghost turns logged 667/800/1053 wpm while real fast
    speech topped out ~455. Residue is spectrally distorted, so the
    self-voice fingerprint alone cannot catch it — density can. Short
    utterances are exempt: wpm inflates on 2–4 word bursts."""
    return (wpm or 0) > 550 and len(text.split()) >= 5


def is_stock_hallucination(text: str, wpm) -> bool:
    """Whisper's silence artifact: near-silent or echo-residue audio decodes
    to stock outro phrases. Live 2026-09-01 (quasi): an open-mic follow-up
    window turned that into a feedback loop — hallucinated "Thank you." ->
    "You're welcome" -> reply tail -> thanks again, for a whole screen.
    The structured layer already measures the tell: those turns logged
    29–56 wpm; a real spoken thank-you is ~150. Drop stock phrases only
    when speech density says the audio could not have carried them."""
    t = re.sub(r"[^a-z ]+", "", text.lower()).strip()
    return t in _STOCK_HALLUCINATIONS and (wpm or 0) < 80

CONTEXT_PROMPT_ADDON = (
    " Each user message may begin with one bracketed [context: …] line "
    "describing how it was spoken — speaker, confidence, question, pace, "
    "prosody, disfluencies. Use it to judge tone and intent; never mention "
    "it or read it aloud."
)

STRUCTURED_CONTEXT = True

def context_line(turns: list, boundary: str) -> str:
    """The structured addon, as ONE cheap bracketed line for the LLM."""
    t = turns[-1]
    bits = [f"speaker=S{t['speaker']}", f"conf={t['speaker_conf']:.0%}",
            f"boundary={boundary}"]
    prosody = t.get("prosody") or {}
    if isinstance(prosody, dict) and prosody.get("pitch_hz") is not None:
        bits.append(f"pitch_hz={prosody['pitch_hz']}")
    if any(turn.get("holding") for turn in turns):
        bits.append("holding=yes")
    if t.get("wake"):
        bits.append(f"wake={t['wake']}")
    if t.get("question"):
        bits.append("question=yes")
    if t.get("wpm"):
        bits.append(f"wpm={t['wpm']}")
    if prosody:
        bits.append(f"prosody={prosody}")
    if t.get("disfluencies"):
        bits.append(f"disfluencies={t['disfluencies']}")
    if t.get("latched"):
        bits.append("latched=yes")
    if t.get("pause_before_ms") is not None:
        bits.append(f"pause_before_ms={t['pause_before_ms']}")
    return "[context: " + " ".join(bits) + "]"

def llm_user_text(text: str, turns: list, boundary: str) -> str:
    if STRUCTURED_CONTEXT and turns:
        return context_line(turns, boundary) + "\n" + text
    return text


__all__ = [
    "match_wake",
    "TurnAnnotator",
    "is_own_voice_echo",
    "is_echo_garble",
    "is_stock_hallucination",
    "context_line",
    "llm_user_text",
    "WAKE_NAME_THRESHOLD",
    "WAKE_PREFIXES",
    "WAKE_NAMES",
    "HOLD_MAX_S",
    "_STOCK_HALLUCINATIONS",
    "_SELF_VOICE",
    "SELF_ECHO_DIST",
    "SELF_ECHO_WINDOW_S",
    "CONTEXT_PROMPT_ADDON",
    "STRUCTURED_CONTEXT",
]
