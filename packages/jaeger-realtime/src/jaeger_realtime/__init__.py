"""jaeger-realtime: 24/7 voice presence, ambient speech gate, and barge-in."""

from .presence import AmbientSpeechGate, GateDecision, RealtimeVoiceSession

__all__ = ["AmbientSpeechGate", "GateDecision", "RealtimeVoiceSession"]
