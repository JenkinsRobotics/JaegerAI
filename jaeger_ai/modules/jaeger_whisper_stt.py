"""The ears — how JaegerAI uses the STT module.

    slot: stt                jaeger-whisper-stt fills it today
    consumes  /sense/mic/pcm
    produces  /sense/stt/transcript, /sense/stt/speech_start,
              /sys/gate/decision

OPTIONAL. A JaegerAI with no ears still types; ``available()`` is what a
surface asks before offering to listen.

NO COMMAND VERBS, and that asymmetry is real rather than an omission.
TTS is something you tell to speak; STT is something that tells YOU.
The module consumes mic frames JaegerAI's audio driver publishes and
emits transcripts — an application subscribes to it, it does not drive
it. The only thing to command here is the microphone, and that belongs
to JaegerAI's AudioIONode, not to this engine.
"""

from __future__ import annotations

from jaeger_os import topics

from jaeger_ai.modules import installed

SLOT = "stt"

#: The exact import package integrated by this module file.
PACKAGE = "jaeger_whisper_stt"

#: Topics a surface watches to follow the listening path.
WATCH = (
    topics.SENSE_STT_SPEECH_START,  # someone started talking — barge-in cue
    topics.SENSE_STT_TRANSCRIPT,    # what was heard
)


def available() -> bool:
    return installed(PACKAGE)


__all__ = ["SLOT", "PACKAGE", "WATCH", "available"]
