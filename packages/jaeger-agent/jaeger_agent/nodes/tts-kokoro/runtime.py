"""Kokoro TTS node. Yields native 24 kHz float chunks; playback stays in the audio node.

Node of the agent brain. Config source of truth stays core/policy.py;
the manifest documents it."""
from __future__ import annotations

import numpy as np

try:  # packaged engine
    from jaeger_agent.core.policy import KOKORO_LANG, KOKORO_VOICE
except ImportError:  # portable node folder loaded by the playground
    from policy import KOKORO_LANG, KOKORO_VOICE


class MouthKokoro:
    def __init__(self) -> None:
        self.tts = None
        self.voice = KOKORO_VOICE

    def load(self, say=print, *, voice: str = KOKORO_VOICE,
             language: str = KOKORO_LANG) -> None:
        from importlib.util import find_spec

        # Misaki otherwise invokes spaCy's downloader during boot; its
        # SystemExit can kill a host's boot thread without reporting failure.
        if language in {"a", "b"} and find_spec("en_core_web_sm") is None:
            raise RuntimeError(
                "Kokoro English requires en_core_web_sm. Reinstall "
                "jaeger-agent[multimodal] to include the speech language model."
            )
        from kokoro import KPipeline
        say("loading Kokoro…")
        self.voice = voice
        try:
            self.tts = KPipeline(lang_code=language, repo_id="hexgrad/Kokoro-82M")
        except SystemExit as exc:
            raise RuntimeError("Kokoro language assets could not be initialized") from exc
        list(self.tts("ready", voice=self.voice))

    def synth(self, text: str):
        for r in self.tts(text, voice=self.voice):
            if r.audio is not None:
                yield np.asarray(r.audio, dtype=np.float32)


def build():
    return MouthKokoro()
