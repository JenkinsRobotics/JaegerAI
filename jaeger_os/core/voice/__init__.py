"""Voice-mode helpers — coordination logic that lives ABOVE the audio
plugins (kokoro_tts / whisper_stt / avaudio_io) but isn't itself
hardware-bound."""

from .farewell import is_farewell
from .non_speech import is_non_speech_marker
from .reply_cleaner import clean_voice_reply

__all__ = [
    "is_farewell", "is_non_speech_marker", "clean_voice_reply",
]
