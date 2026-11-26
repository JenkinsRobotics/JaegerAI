"""jaeger-realtime: 24/7 voice presence, ambient speech gate, and barge-in."""

from .presence import AmbientSpeechGate, GateDecision, RealtimeVoiceSession
from .voice_loop import FullDuplexVoiceBridge

__all__ = ["AmbientSpeechGate", "FullDuplexVoiceBridge", "GateDecision", "RealtimeVoiceSession"]
