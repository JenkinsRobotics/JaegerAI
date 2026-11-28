"""jaeger-realtime: 24/7 voice presence, ambient speech gate, echo filter, and barge-in."""

from .presence import (
    AmbientSpeechGate,
    EchoCheckResult,
    GateDecision,
    LLMSpeechGate,
    RealtimeVoiceSession,
    SelfSpeechFilter,
    is_farewell,
    is_hallucination,
    strip_gate_tags,
)
from .speech_prep import (
    FirstCommaChunker,
    PreparedSpeech,
    TurnEndDecision,
    TurnEndJudge,
    extract_visual_and_speech,
    to_speech_text,
)
from .voice_loop import FullDuplexVoiceBridge

__all__ = [
    "AmbientSpeechGate",
    "EchoCheckResult",
    "FirstCommaChunker",
    "FullDuplexVoiceBridge",
    "GateDecision",
    "LLMSpeechGate",
    "PreparedSpeech",
    "RealtimeVoiceSession",
    "SelfSpeechFilter",
    "TurnEndDecision",
    "TurnEndJudge",
    "extract_visual_and_speech",
    "is_farewell",
    "is_hallucination",
    "strip_gate_tags",
    "to_speech_text",
]
