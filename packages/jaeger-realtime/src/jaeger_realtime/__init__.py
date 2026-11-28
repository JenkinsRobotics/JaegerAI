"""jaeger-realtime: 24/7 voice presence, ambient speech gate, and barge-in."""

from .presence import AmbientSpeechGate, GateDecision, RealtimeVoiceSession
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
    "FirstCommaChunker",
    "FullDuplexVoiceBridge",
    "GateDecision",
    "PreparedSpeech",
    "RealtimeVoiceSession",
    "TurnEndDecision",
    "TurnEndJudge",
    "extract_visual_and_speech",
    "to_speech_text",
]
