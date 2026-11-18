"""On-device speech models for the realtime voice service.

Parakeet (NVIDIA parakeet-tdt-0.6b-v2 on MLX) transcribes each VAD segment in
about 0.1 s on an M1 Max; Phonon (Gradium's 31M English checkpoint served by
Ollama, Apache-2.0) starts streaming speech about 25 ms after a request.
Both run locally; nothing leaves the Mac.
"""

from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

import aiohttp
import numpy as np
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

PARAKEET_MODEL = os.environ.get("JAEGER_PARAKEET_MODEL", "mlx-community/parakeet-tdt-0.6b-v2")
PHONON_VOICE = os.environ.get("JAEGER_VOICE_TTS_VOICE", "default")
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")

# MLX is not thread-safe across models; one worker thread owns Parakeet.
_mlx = ThreadPoolExecutor(max_workers=1, thread_name_prefix="parakeet")
_model = None

# Parakeet has never heard the name; map its usual guesses back to it.
_NAME = re.compile(r"\b(?:Yeager|Yaeger|Jager|J[äa]ger|Yager|Jaegar|Jagger|Jigger|Jaker|Aater)\b", re.I)


def _load():
    global _model
    if _model is None:
        from parakeet_mlx import from_pretrained

        _model = from_pretrained(PARAKEET_MODEL)
    return _model


def _transcribe(pcm: bytes) -> str:
    import mlx.core as mx
    from parakeet_mlx.audio import get_logmel

    model = _load()
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size < model.preprocessor_config.hop_length * 4:
        return ""
    mel = get_logmel(mx.array(audio), model.preprocessor_config)
    text = model.generate(mel)[0].text.strip()
    return _NAME.sub("Jaeger", text)


async def warm_parakeet() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_mlx, _load)
    await loop.run_in_executor(_mlx, _transcribe, bytes(16000 * 2))


class ParakeetSTTService(SegmentedSTTService):
    """Segmented STT: Silero marks the segment, Parakeet transcribes it."""

    @property
    def wants_wav_segments(self) -> bool:
        return False

    @property
    def segment_sample_rate(self) -> int:
        return 16000

    def __init__(self, **kwargs):
        super().__init__(
            settings=STTSettings(model=PARAKEET_MODEL, language=Language.EN),
            trailing_silence_secs=0.2,
            **kwargs,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        try:
            await self.start_processing_metrics()
            text = await asyncio.get_running_loop().run_in_executor(_mlx, _transcribe, audio)
            await self.stop_processing_metrics()
            if text:
                yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), Language.EN)
        except Exception as exc:  # keep the call alive; the turn just has no text
            logger.exception("parakeet failed")
            yield ErrorFrame(error=f"Parakeet error: {exc}")


class PhononTTSService(TTSService):
    """Streams 24 kHz PCM from Ollama's /v1/audio/speech (Phonon)."""

    def __init__(self, *, voice: str = PHONON_VOICE, **kwargs):
        super().__init__(
            sample_rate=24000,
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model="phonon", voice=voice, language=None),
            **kwargs,
        )
        self._http: aiohttp.ClientSession | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return self._http

    async def cleanup(self):
        await super().cleanup()
        if self._http is not None:
            await self._http.close()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        body = {"model": "phonon", "input": text[:4000], "voice": self._settings.voice or "default",
                "response_format": "pcm", "keep_alive": "30m"}
        try:
            http = await self._session()
            async with http.post(f"{OLLAMA_URL}/v1/audio/speech", json=body) as resp:
                if resp.status != 200:
                    yield ErrorFrame(error=f"Phonon TTS {resp.status}: {(await resp.text())[:200]}")
                    return
                await self.start_tts_usage_metrics(text)
                carry = b""
                async for chunk in resp.content.iter_chunked(self.chunk_size):
                    data = carry + chunk
                    cut = len(data) - (len(data) % 2)
                    carry = data[cut:]
                    if cut:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(data[:cut], self.sample_rate, 1, context_id=context_id)
        except Exception as exc:
            logger.exception("phonon failed")
            yield ErrorFrame(error=f"Phonon TTS error: {exc}")


async def warm_phonon() -> None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as http:
            async with http.post(f"{OLLAMA_URL}/v1/audio/speech", json={
                "model": "phonon", "input": "Ready.", "voice": PHONON_VOICE,
                "response_format": "pcm", "keep_alive": "30m"}) as resp:
                await resp.read()
    except Exception as exc:
        logger.warning(f"phonon warm-up failed: {exc}")
