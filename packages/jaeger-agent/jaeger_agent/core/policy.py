"""Verified core wake, turn-completeness, closure, follow-up, and VAD policy.

Ported from VoiceLLM-Playground on 2026-09-02.  Model defaults remain here
for node portability; :class:`jaeger_agent.core.config.MultimodalConfig` supplies
runtime overrides in the packaged engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from difflib import SequenceMatcher
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# section: turn policy — VENDORED, do not import
#
# Lifted verbatim from `voice_halfduplex.py` by dependency closure:
# 47 definitions covering the wake roster, the environment gate, sentence
# completeness, closers, and the contextual follow-up window.
#
# This is a COPY on purpose. These apps are standalone — each one runs from
# its own file, so a change to the voice folder cannot silently alter what the
# multimodal app does. The cost is that a policy fix must be applied twice;
# the benefit is that neither app can break the other, and either can be moved
# or deleted without consulting the rest.
# ═══════════════════════════════════════════════════════════════════════════

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

DEFAULT_LLM = "e4b"

_BRACKETED_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")

_DANGLING = {
    # conjunctions / discourse glue
    "and", "but", "or", "so", "because", "although", "though", "while",
    "if", "unless", "since", "whether", "plus", "then",
    # prepositions
    "to", "of", "in", "on", "at", "for", "with", "from", "by", "about",
    "into", "over", "under", "between", "through", "like", "as",
    # articles / determiners
    "a", "an", "the", "this", "that", "these", "those", "my", "your", "our",
    "his", "her", "their", "its", "some", "any", "every",
    # auxiliaries and pronouns that cannot end a thought
    "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should", "may",
    "might", "must",
    # NOTE: object pronouns are deliberately ABSENT. "what time is it",
    # "that's it", "I told you" all end on one, and treating them as dangling
    # made the commonest question in the world look unfinished.
    "i",
}

_SHORT_COMPLETE = {
    "yes", "yeah", "yep", "yup", "no", "nope", "nah", "sure", "okay", "ok",
    "thanks", "thank you", "correct", "right", "exactly", "please", "stop",
    "go ahead", "continue", "never mind", "maybe", "perhaps", "done",
}

def looks_complete(text: str) -> bool:
    """Does this transcript read as a finished thought?

    Deliberately conservative: when unsure, say NO and wait. A needless extra
    second of listening is invisible; truncating someone mid-sentence is not.
    """
    t = _BRACKETED_RE.sub("", text or "").strip()
    if not t:
        return False
    if t[-1] in ".!?":
        return True
    words = re.sub(r"[^a-z0-9' ]+", " ", t.lower()).split()
    if not words:
        return False
    if " ".join(words) in _SHORT_COMPLETE:
        return True           # a whole answer, however brief
    if words[-1] in _DANGLING:
        return False          # plainly mid-clause
    # Two words is a real turn once the dangling test has run: "no thanks",
    # "that's it", "sounds good", "got it". The cases a 2-word minimum would
    # wrongly admit — "what about", "and then" — all end on a dangling word
    # and were already rejected above.
    return len(words) >= 2

def is_non_speech(text: str) -> bool:
    return not _BRACKETED_RE.sub("", text).strip(" .,!?-\"'")

_WAKE_PREFIXES = ("ok", "okay", "hey", "yo", "hi")

_ASSISTANT_NAMES = (
    # ours, plus how Whisper actually transcribes it
    "jaeger", "yeager", "yager", "jager", "jaguar", "yaeger",
    # the names people already have muscle memory for
    "google", "siri", "alexa", "cortana", "bixby",
    # generic / sci-fi, which visitors reach for unprompted
    "robot", "computer", "jarvis", "assistant", "agent",
    # current model names, said surprisingly often
    "gemini", "gemma", "claude", "chat", "gpt",
)

WAKE_PHRASES = tuple(f"{p} {n}" for p in _WAKE_PREFIXES for n in _ASSISTANT_NAMES)

_RESCUABLE_NAMES = tuple(
    n for n in _ASSISTANT_NAMES
    if n not in {"computer", "google", "chat", "agent", "assistant", "robot",
                 "gpt", "claude", "gemma", "gemini"})

WAKE_MATCH_THRESHOLD = 0.78

STRONG_NAME_THRESHOLD = 0.88

_GARBLED_WAKE_PREFIXES = {"a", "ah", "ay", "ha", "hay", "he", "hiya"}

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()

def _match_wake(text: str) -> tuple[str, str] | None:
    """Return (phrase_as_heard, remainder) or None.

    phrase_as_heard is what the user actually said — for a fuzzy hit that is the
    misheard form ("hey yeager"), which is the useful thing to show them.
    """
    norm = normalize(text)
    tokens = norm.split()
    for phrase in WAKE_PHRASES:
        parts = phrase.split()
        n = len(parts)
        for i in range(0, len(tokens) - n + 1):
            if tokens[i:i + n] == parts:
                return " ".join(tokens[i:i + n]), \
                    " ".join(tokens[i + n:]).strip()
    # Fuzzy pass: the NAME may be misheard, but the PREFIX must be a real
    # prefix word. Whole-phrase fuzz let "the computer" match "hey computer"
    # (ratio ~0.84), which turns ordinary TV dialogue into wake events — a
    # hazard that grows with every name added to the demo list.
    for phrase in WAKE_PHRASES:
        parts = phrase.split()
        n = len(parts)
        name = " ".join(parts[1:])
        for i in range(0, max(0, len(tokens) - n + 1)):
            if tokens[i] not in _WAKE_PREFIXES:
                continue
            cand = " ".join(tokens[i + 1:i + n])
            if cand != name and (cand.startswith(name) or name.startswith(cand)):
                # Edit-distance fuzz otherwise treats a longer ordinary word
                # as the shorter name: "sirius" scored 0.80 against "siri".
                continue
            if SequenceMatcher(None, cand, name).ratio() >= WAKE_MATCH_THRESHOLD:
                return " ".join(tokens[i:i + n]), " ".join(tokens[i + n:]).strip()

    # STRONG NAME, GARBLED PREFIX. The loop above discards a PERFECT name
    # match when the prefix was misheard: "hay jaeger" and "a jaeger" both
    # score 1.00 on the name. A small STT mangles the unstressed prefix far
    # more often than the stressed name, so demanding both survive loses real
    # wakes. Distinctive names only — see _RESCUABLE_NAMES.
    for rname in _RESCUABLE_NAMES:
        for i, tok in enumerate(tokens):
            if SequenceMatcher(None, tok, rname).ratio() >= STRONG_NAME_THRESHOLD:
                if i == 0:
                    continue          # bare leading name is usually the TV
                if tokens[i - 1] not in _GARBLED_WAKE_PREFIXES:
                    continue          # not a plausible damaged wake prefix
                return " ".join(tokens[max(0, i - 1):i + 1]), \
                    " ".join(tokens[i + 1:]).strip()
    return None

def committed_user_text(trigger_utterance: str, command: str) -> str:
    """Preserve spoken trigger text while keeping the LLM command separate.

    Inline wake phrases already live in ``trigger_utterance`` and must not be
    replaced by their stripped command. Wake-only and command utterances are
    committed separately by the caller. Only ``command`` goes to the LLM.
    """
    trigger = (trigger_utterance or "").strip()
    command = (command or "").strip()
    if not trigger:
        return command
    return trigger

SAMPLE_RATE = 16000

LLM_MODEL_PATH = LLMS[DEFAULT_LLM].path   # --llm overrides

STT_MODEL = "large-v3-turbo"

KOKORO_VOICE = "af_heart"

KOKORO_LANG = "a"

FOLLOWUP_WINDOW_S = 15.0        # soft default for a fresh exchange

FOLLOWUP_MAX_S = 45.0           # ceiling; past this, silence means gone

FOLLOWUP_QUESTION_BONUS_S = 12.0   # we asked something; give them time

FOLLOWUP_DEPTH_BONUS_S = 7.0       # per established turn, to a cap

def followup_window(turns: int = 0, agent_asked: bool = False) -> float:
    """How long to keep listening without the wake phrase."""
    # main() calls this after incrementing exchange_turns, so turn 1 is the
    # fresh exchange and must not receive a depth bonus yet.
    depth = min(3, max(0, turns - 1)) * FOLLOWUP_DEPTH_BONUS_S
    asked = FOLLOWUP_QUESTION_BONUS_S if agent_asked else 0.0
    return min(FOLLOWUP_WINDOW_S + depth + asked, FOLLOWUP_MAX_S)

def agent_asked_question(reply: str) -> bool:
    """Did our own reply end by asking something?

    Cheap and deliberately literal: a trailing question mark, or an opening
    interrogative. Getting this wrong only changes how patient we are.
    """
    r = (reply or "").strip()
    if r.endswith("?"):
        return True
    first = r.lower().split()[:1]
    return bool(first and first[0] in {
        "what", "which", "who", "when", "where", "why", "how",
        "do", "did", "are", "is", "would", "could", "should", "can"})

SAMPLE_RATE = 16000

FRAME_MS = 30

SILERO_ONNX = Path(__file__).resolve().parents[1] / "assets/silero/silero_vad_16k_op15.onnx"

SILERO_OPEN_P = 0.30         # high-precision admission: false wakes cost most

SILERO_CLOSE_P = 0.125       # once admitted, retain quiet syllables/consonants

SILENCE_HANGOVER_MS = 500     # FAMILY CONTRACT (2026-09-01): fast endpoint;
                              # HOLDING absorbs thinking pauses at the REPLY
                              # level instead of a slow endpoint taxing every
                              # turn 1.8 s. Probe-verified: 1 s gaps merged
                              # turns at 1800 ms and split correctly at 500.

MIN_SPEECH_MS = 300           # family parity

HARD_MAX_SPEECH_MS = 45000

SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Answer in 1–2 short sentences "
    "in plain conversational English. No markdown, no code blocks, no "
    "emojis, no lists. If you don't know, say so briefly."
)

_CLOSERS = (
    # Whisper can render the same farewell as one word, two words, or the
    # homophone "good buy". These remain exact committed-text variants.
    "bye", "goodbye", "good bye", "goodbuy", "good buy", "good by",
    "see you", "see ya", "later",
    "good night", "goodnight", "that is all", "that's all", "that will be all",
    "nothing else", "no thanks", "no thank you", "never mind", "nevermind",
    "forget it", "cancel that", "stop listening", "go to sleep",
    "we are done", "we're done", "i am done", "i'm done", "all done",
    "thanks that is it", "thanks that's it", "that is it", "that's it",
    "dismissed", "stand down", "shut up", "be quiet", "quiet",
)

def _normalise_close_text(text: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", value).strip()

_NORMALISED_CLOSERS = frozenset(_normalise_close_text(c) for c in _CLOSERS)

_CLOSE_PREFIXES = ("okay", "ok", "well", "alright", "cool", "thanks", "thank you")

_CLOSE_SUFFIXES = (
    "jaeger", "yeager", "everyone", "thanks", "thank you", "please",
    "talk tomorrow",
)

def _is_close_clause(clause: str) -> bool:
    """Match a farewell plus harmless conversational wrappers."""
    value = _normalise_close_text(clause)
    if not value:
        return False
    if value in _NORMALISED_CLOSERS:
        return True

    changed = True
    while changed and value:
        changed = False
        for prefix in sorted(_CLOSE_PREFIXES, key=len, reverse=True):
            if value.startswith(prefix + " "):
                value = value[len(prefix):].strip()
                changed = True
                break
        for suffix in sorted(_CLOSE_SUFFIXES, key=len, reverse=True):
            if value.endswith(" " + suffix):
                value = value[:-len(suffix)].strip()
                changed = True
                break
        if value in _NORMALISED_CLOSERS:
            return True
    return False

def closes_conversation(text: str) -> bool:
    """Did that utterance end the exchange?

    Matched on the WHOLE utterance, not as a substring: "bye" ends a
    conversation, "by the way" does not, and "thanks for that, now what about
    Tuesday" is gratitude mid-topic rather than a dismissal.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    # Inspect terminal-punctuation clauses as well as the whole utterance.
    # Live evidence: "Okay, thanks. Bye. Thank you." must close even though
    # normalization of the full utterance produces more than five words.
    clauses = [raw, *re.split(r"[.!?;]+", raw)]
    return any(_is_close_clause(clause) for clause in clauses)

class SileroVad:
    """Small recurrent neural VAD with probability hysteresis.

    Opening and continuation deliberately use different thresholds. A high
    opening bar keeps claps, typing and room noise out; the lower continuation
    bar keeps quiet syllables inside a turn once speech is established.
    """

    def __init__(self, model: Path | str = SILERO_ONNX,
                 open_p: float = SILERO_OPEN_P,
                 close_p: float = SILERO_CLOSE_P) -> None:
        model = Path(model).expanduser()
        if not model.exists():
            raise FileNotFoundError(
                f"missing Silero VAD model: {model}\n"
                "Expected the local 16 kHz ONNX model; refusing to fall back "
                "to WebRTC because that reintroduces known false speech."
            )
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model), sess_options=options,
            providers=["CPUExecutionProvider"])
        self.open_p = float(open_p)
        self.close_p = float(close_p)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self.last_p = 0.0

    def probability(self, frame: np.ndarray) -> float:
        """Return speech probability for one 16 kHz frame.

        The exported model consumes 512 samples. The microphone deliberately
        remains on its proven 30 ms/480-sample cadence, so only the detector
        copy is padded; captured audio is never changed or dropped.
        """
        values = np.asarray(frame, dtype=np.float32).reshape(-1)
        detector = np.zeros(512, dtype=np.float32)
        detector[:min(len(values), 512)] = values[:512]
        probability, self._state = self.session.run(
            None,
            {"input": detector[None, :], "state": self._state,
             "sr": np.array(SAMPLE_RATE, dtype=np.int64)},
        )
        self.last_p = float(probability[0, 0])
        return self.last_p

def turn_started_in_followup(started_at: float, deadline: float) -> bool:
    """Eligibility is fixed when speech starts; room audio cannot extend it."""
    return deadline > 0.0 and 0.0 < started_at <= deadline

# ═══════════════════════════════════════════════════════════════════════════
# end vendored section
# ═══════════════════════════════════════════════════════════════════════════

MMPROJ = (Path.home() / ".lmstudio/models/lmstudio-community"
          / "gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf")
TTS_RATE = 24000


__all__ = [
    "LLMChoice",
    "looks_complete",
    "is_non_speech",
    "normalize",
    "_match_wake",
    "committed_user_text",
    "followup_window",
    "agent_asked_question",
    "_normalise_close_text",
    "_is_close_clause",
    "closes_conversation",
    "SileroVad",
    "turn_started_in_followup",
    "LMSTUDIO",
    "DEFAULT_LLM",
    "_BRACKETED_RE",
    "_DANGLING",
    "_SHORT_COMPLETE",
    "_WAKE_PREFIXES",
    "_ASSISTANT_NAMES",
    "WAKE_PHRASES",
    "_RESCUABLE_NAMES",
    "WAKE_MATCH_THRESHOLD",
    "STRONG_NAME_THRESHOLD",
    "_GARBLED_WAKE_PREFIXES",
    "SAMPLE_RATE",
    "LLM_MODEL_PATH",
    "STT_MODEL",
    "KOKORO_VOICE",
    "KOKORO_LANG",
    "FOLLOWUP_WINDOW_S",
    "FOLLOWUP_MAX_S",
    "FOLLOWUP_QUESTION_BONUS_S",
    "FOLLOWUP_DEPTH_BONUS_S",
    "FRAME_MS",
    "SILERO_ONNX",
    "SILERO_OPEN_P",
    "SILERO_CLOSE_P",
    "SILENCE_HANGOVER_MS",
    "MIN_SPEECH_MS",
    "HARD_MAX_SPEECH_MS",
    "SYSTEM_PROMPT",
    "_CLOSERS",
    "_NORMALISED_CLOSERS",
    "_CLOSE_PREFIXES",
    "_CLOSE_SUFFIXES",
    "MMPROJ",
    "TTS_RATE",
]
