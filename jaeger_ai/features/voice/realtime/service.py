"""Jaeger realtime voice service (Pipecat over WebRTC).

Runs as its own process (``~/.jaeger/voice-venv``, launchd
``com.jenkinsrobotics.jaeger-voice``) on 127.0.0.1:8794; the WebUI proxies
signalling at ``/api/jaeger/rtc/*`` so only signed-in clients reach it. Media
then flows peer to peer (on the tailnet for the iPhone).

Two engines:

* ``local``: mic -> Silero VAD -> Parakeet STT -> Smart Turn v3 -> the browser.
  The browser runs the turn through the normal Jaeger gateway session (same
  history, tools, autonomy) and streams the reply's sentences back as
  ``speak`` messages; Phonon speaks them. Speaking over Jaeger interrupts it.
* ``gemini``: Gemini Live (AI Studio key in ``~/.jaeger/secrets.env``) does
  speech to speech. Its one tool, ``ask_jaeger``, hands real work to the same
  gateway session through the browser; transcripts go back to the chat.

Camera and screen are not sent anywhere by this service.

Data channel messages (JSON, ``t`` is the type):
  service -> client: ready, user-speaking, user-partial, user-final, interrupted,
                     bot-speaking, bot-text, transcript, tool, error
  client -> service: speak {text}, stop, tool-result {id, text}
  (client messages also carry ``type: "jaeger"``; Pipecat requires a ``type``)
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiohttp import web
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.workers.runner import WorkerRunner

from local_models import ParakeetSTTService, PhononTTSService, warm_parakeet, warm_phonon

HOST = os.environ.get("JAEGER_VOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("JAEGER_VOICE_PORT", "8794"))
SECRETS = Path.home() / ".jaeger" / "secrets.env"
VAD_STOP = 0.2
GEMINI_MODEL = os.environ.get("JAEGER_GEMINI_LIVE_MODEL", "models/gemini-3.8-live")
GEMINI_VOICE = os.environ.get("JAEGER_GEMINI_LIVE_VOICE", "Aoede")
TOOL_TIMEOUT = 240.0
# "Hey Jaeger," followed by a breath is not a finished request: hold such a
# fragment briefly so the rest of the sentence joins it.
HOLD_SECS = 1.2
_FRAGMENT = re.compile(r"^(?:(?:hey|hi|okay|ok|so|um|uh|and)[ ,]+)?(?:jaeger)?[ ,.!?]*$|^[^ ]+(?: [^ ]+)?,$", re.I)

_ready = {"local": False}
_sessions: dict[str, dict] = {}


def gemini_key() -> str:
    """The AI Studio key, read from secrets.env each call (never logged)."""
    try:
        for line in SECRETS.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return os.environ.get("GEMINI_API_KEY", "")


def _msg(t: str, **kw) -> OutputTransportMessageUrgentFrame:
    return OutputTransportMessageUrgentFrame(message={"t": t, "at": time.time(), **kw})


class LocalBridge(FrameProcessor):
    """Captions, turn ends and barge-in to the client; its sentences to TTS."""

    def __init__(self):
        super().__init__()
        self._words: list[str] = []
        self._speech_end = 0.0
        self._final_at = 0.0
        self._speak_at = 0.0
        self._bot = False
        self._hold: asyncio.Task | None = None

    async def _finalize(self):
        text = " ".join(w for w in self._words if w).strip()
        self._words = []
        if text:
            self._final_at = time.time()
            await self.push_frame(_msg("user-final", text=text, speechEnd=self._speech_end,
                                       turnMs=round((self._final_at - self._speech_end) * 1000)))

    async def _finalize_later(self):
        await asyncio.sleep(HOLD_SECS)
        self._hold = None
        await self._finalize()

    def _cancel_hold(self):
        if self._hold is not None:
            self._hold.cancel()
            self._hold = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame):
            await self._client(frame.message)
            return
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                self._speech_end = time.time() - VAD_STOP
            elif isinstance(frame, UserStartedSpeakingFrame):
                self._cancel_hold()
                await self.push_frame(_msg("user-speaking", bot=self._bot))
            elif isinstance(frame, TranscriptionFrame):
                self._words.append(frame.text.strip())
                await self.push_frame(_msg("user-partial", text=" ".join(self._words)))
            elif isinstance(frame, UserStoppedSpeakingFrame):
                text = " ".join(w for w in self._words if w).strip()
                self._cancel_hold()
                if text and _FRAGMENT.match(text):
                    self._hold = asyncio.create_task(self._finalize_later())
                else:
                    await self._finalize()
            elif isinstance(frame, InterruptionFrame) and self._bot:
                await self.push_frame(_msg("interrupted"))
        else:
            if isinstance(frame, BotStartedSpeakingFrame):
                self._bot = True
                extra = {}
                if self._speak_at:
                    extra = {"ttsMs": round((time.time() - self._speak_at) * 1000)}
                    self._speak_at = 0.0
                await self.push_frame(_msg("bot-speaking", on=True, **extra))
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._bot = False
                await self.push_frame(_msg("bot-speaking", on=False))
        await self.push_frame(frame, direction)

    async def _client(self, message):
        if not isinstance(message, dict):
            return
        kind = message.get("t")
        if kind == "speak":
            text = str(message.get("text") or "").strip()
            if text:
                if not self._bot and not self._speak_at:
                    self._speak_at = time.time()
                await self.push_frame(TTSSpeakFrame(text[:2000]))
        elif kind == "stop":
            self._speak_at = 0.0
            await self.broadcast_interruption()


class GeminiBridge(FrameProcessor):
    """Captions and speaking state for Gemini Live; resolves ask_jaeger."""

    def __init__(self, pending: dict[str, asyncio.Future]):
        super().__init__()
        self._pending = pending
        self._bot_text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame):
            m = frame.message if isinstance(frame.message, dict) else {}
            if m.get("t") == "tool-result":
                fut = self._pending.pop(str(m.get("id")), None)
                if fut and not fut.done():
                    fut.set_result(str(m.get("text") or ""))
            elif m.get("t") == "stop":
                await self.broadcast_interruption()
        elif direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, TranscriptionFrame):
                await self.push_frame(_msg("user-partial", text=frame.text))
            elif isinstance(frame, TTSTextFrame):
                self._bot_text = re.sub(r"\s+", " ", f"{self._bot_text} {frame.text}").strip()
                await self.push_frame(_msg("bot-text", text=self._bot_text))
            elif isinstance(frame, (UserStartedSpeakingFrame, VADUserStartedSpeakingFrame, InterruptionFrame)):
                # Local Silero drives the orb only; Gemini decides the turn itself.
                self._bot_text = ""
                await self.push_frame(_msg("user-speaking"))
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                await self.push_frame(_msg("user-stopped", stopMs=round(VAD_STOP * 1000)))
        else:
            if isinstance(frame, BotStartedSpeakingFrame):
                await self.push_frame(_msg("bot-speaking", on=True))
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._bot_text = ""
                await self.push_frame(_msg("bot-speaking", on=False))
        await self.push_frame(frame, direction)


def _local_pipeline(transport):
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(confidence=0.5, start_secs=0.15, stop_secs=VAD_STOP)))
    return Pipeline([transport.input(), vad, ParakeetSTTService(), UserTurnProcessor(),
                     LocalBridge(), PhononTTSService(), transport.output()])


GEMINI_SYSTEM = (
    "You are Jaeger, the user's personal AI assistant, in a live voice conversation. "
    "Keep replies short and natural; never read out markdown. For anything that needs the "
    "user's files, apps, accounts, calendar, email, the web, memory, code, or any action on "
    "their computer, call ask_jaeger with a clear, complete request and tell the user you're "
    "on it; when the result comes back, summarize it briefly. Do not invent results."
)


def _gemini_pipeline(transport, request_data: dict, pending: dict, send):
    from pipecat.adapters.llm.schemas.direct_function import tool_options
    from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
    from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams

    # Synchronous (BLOCKING on Gemini 3.8 Live): Gemini waits for Jaeger and then speaks
    # the answer. As NON_BLOCKING it voiced only its filler and dropped the result.
    # Interrupting cancels the wait; the Jaeger turn still finishes in the chat.
    @tool_options(cancel_on_interruption=True)
    async def ask_jaeger(params):
        call_id = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        pending[call_id] = fut
        send({"t": "tool", "id": call_id, "request": str(params.arguments.get("request") or "")})
        try:
            text = await asyncio.wait_for(fut, TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            pending.pop(call_id, None)
            text = "Jaeger is still working on it; the result will appear in the chat."
        await params.result_callback({"result": text[:6000]})

    tool = FunctionSchema(
        name="ask_jaeger",
        description=("Hand a request to Jaeger, the user's full assistant, which has their tools, "
                     "files, apps, accounts, memory and the web, and return its answer."),
        properties={"request": {"type": "string", "description": "The complete request, in plain words."}},
        required=["request"],
        handler=ask_jaeger,
    )
    history = []
    for row in (request_data.get("history") or [])[-12:]:
        role = row.get("role") if isinstance(row, dict) else None
        text = str((row or {}).get("content") or "")[:1500]
        if role in ("user", "assistant") and text.strip():
            history.append({"role": role, "content": text})
    llm = GeminiLiveLLMService(
        api_key=gemini_key(),
        settings=GeminiLiveLLMService.Settings(model=GEMINI_MODEL, system_instruction=GEMINI_SYSTEM,
                                               voice=GEMINI_VOICE,
                                               # Turns come from local Silero + Smart Turn (same as the
                                               # Jaeger engine), so barge-in and follow-ups are reliable.
                                               vad=GeminiVADParams(disabled=True)),
        tools=ToolsSchema(standard_tools=[tool]),
        # Silent until the user speaks, like ChatGPT voice mode; the seed is history only.
        inference_on_context_initialization=False,
    )
    context = LLMContext(messages=history)
    user_agg, assistant_agg = LLMContextAggregatorPair(context)

    @user_agg.event_handler("on_user_turn_message_added")
    async def _user_said(_agg, message):
        if (message.content or "").strip():
            send({"t": "user-partial", "text": message.content})
            send({"t": "transcript", "role": "user", "text": message.content})

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _bot_said(_agg, message):
        if (message.content or "").strip():
            send({"t": "transcript", "role": "assistant", "text": message.content,
                  "interrupted": bool(getattr(message, "interrupted", False))})

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(confidence=0.5, start_secs=0.15, stop_secs=VAD_STOP)))
    return Pipeline([transport.input(), vad, user_agg, llm, GeminiBridge(pending), transport.output(),
                     assistant_agg])


async def _run_session(connection: SmallWebRTCConnection, request_data: dict):
    engine = "gemini" if request_data.get("engine") == "gemini" else "local"
    transport = SmallWebRTCTransport(connection, TransportParams(
        audio_in_enabled=True, audio_out_enabled=True,
        audio_in_sample_rate=16000, audio_out_sample_rate=24000))
    pending: dict[str, asyncio.Future] = {}

    def send(message: dict):
        connection.send_app_message({"at": time.time(), **message})

    try:
        if engine == "gemini":
            if not gemini_key():
                send({"t": "error", "message": "Gemini Live needs GEMINI_API_KEY in ~/.jaeger/secrets.env"})
                return
            pipeline = _gemini_pipeline(transport, request_data, pending, send)
        else:
            pipeline = _local_pipeline(transport)
    except Exception as exc:
        logger.exception("pipeline build failed")
        send({"t": "error", "message": f"Voice engine failed to start: {type(exc).__name__}"})
        return
    worker = PipelineWorker(pipeline, params=PipelineParams(
        audio_in_sample_rate=16000, audio_out_sample_rate=24000, enable_metrics=True))
    runner = WorkerRunner(handle_sigint=False)
    _sessions[connection.pc_id] = {"engine": engine, "started": time.time()}

    @transport.event_handler("on_client_connected")
    async def _connected(_t, _c):
        if engine == "gemini":
            # Gemini Live takes no audio until it has its first context.
            from pipecat.frames.frames import LLMRunFrame
            await worker.queue_frames([LLMRunFrame()])
        send({"t": "ready", "engine": engine})

    @transport.event_handler("on_client_disconnected")
    async def _gone(_t, _c):
        for fut in pending.values():
            if not fut.done():
                fut.cancel()
        await worker.cancel()

    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        _sessions.pop(connection.pc_id, None)
        logger.info(f"voice session {connection.pc_id} ({engine}) ended")


handler = SmallWebRTCRequestHandler()


async def offer(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict) or not body.get("sdp"):
        return web.json_response({"error": "sdp required"}, status=400)
    req = SmallWebRTCRequest(sdp=body["sdp"], type=body.get("type", "offer"), pc_id=body.get("pc_id"),
                             restart_pc=body.get("restart_pc"), request_data=body.get("request_data") or {})
    data = req.request_data if isinstance(req.request_data, dict) else {}

    async def started(connection: SmallWebRTCConnection):
        asyncio.create_task(_run_session(connection, data))

    answer = await handler.handle_web_request(request=req, webrtc_connection_callback=started)
    return web.json_response(answer)


async def ice(request: web.Request) -> web.Response:
    body = await request.json()
    cands = [IceCandidate(candidate=c.get("candidate", ""), sdp_mid=c.get("sdp_mid") or c.get("sdpMid") or "0",
                          sdp_mline_index=int(c.get("sdp_mline_index", c.get("sdpMLineIndex", 0)) or 0))
             for c in body.get("candidates") or [] if c.get("candidate")]
    await handler.handle_patch_request(SmallWebRTCPatchRequest(pc_id=body.get("pc_id"), candidates=cands))
    return web.json_response({"ok": True})


async def status(_request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "engines": {
            "local": {"ready": _ready["local"], "stt": "parakeet-tdt-0.6b-v2", "tts": "phonon",
                      "turns": "silero+smart-turn-v3"},
            "gemini": {"ready": bool(gemini_key()), "model": GEMINI_MODEL.split("/")[-1],
                       "needs": None if gemini_key() else "GEMINI_API_KEY"},
        },
        "sessions": len(_sessions),
    })


async def _warm(_app):
    async def go():
        try:
            await warm_parakeet()
            await warm_phonon()
            SileroVADAnalyzer()
            _ready["local"] = True
            logger.info("local voice models warm")
        except Exception:
            logger.exception("warm-up failed")
    asyncio.create_task(go())


def main():
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_post("/offer", offer)
    app.router.add_post("/ice", ice)
    app.router.add_get("/status", status)
    app.on_startup.append(_warm)
    web.run_app(app, host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
