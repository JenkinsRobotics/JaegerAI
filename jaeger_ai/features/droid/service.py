"""Droid mode service: Jaeger's body on the Mac Studio.

Always resident and idle (microphone closed) until woken. Waking opens one
voice-processed audio engine on the Mac's own microphone and speakers and
joins the realtime voice service (:8794) exactly as a browser would: Silero +
Smart Turn decide when Matthew is done, Parakeet transcribes, Phonon speaks.
Every utterance is a normal Gateway turn on the home chat, so what is said to
the droid is in the chat afterwards, with the same memory, tools, Autonomy
and approvals. Approvals are asked out loud and answered by voice.

Control (owner-only unix socket ``~/.jaeger/run/droid/control.sock``)::

    GET  /status              state for the menu bar, WebUI and Stream Deck
    POST /wake /sleep /toggle wake or put the droid to standby
    POST /mute /stop          microphone mute toggle; stop talking now
    POST /say  {"text"}       speak a line (proactive messages)
    POST /hear {"text"}       treat text as heard speech (diagnostics)

Runs in the realtime voice venv under the Jaeger Droid host app, which holds
the macOS microphone and camera permissions.
"""
from __future__ import annotations

import asyncio
import fractions
import json
import logging
import os
import re
import socket
import time
import uuid
from pathlib import Path

import numpy as np
from aiohttp import ClientSession, ClientTimeout, web

from collections import deque

from . import coreaudio, persona, vision
from .audio import BLOCK, RATE, DuplexAudio

log = logging.getLogger("jaeger.droid")
STATE = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")
RUN = STATE / "run" / "droid"
CONFIG = STATE / "droid.json"
VOICE_URL = os.environ.get("JAEGER_VOICE_URL", "http://127.0.0.1:8794")
DEFAULTS = {"speaker": "Mac Studio Speakers", "microphone": "Insta360 Link 2", "camera": "Insta360 Link 2",
            "engine": "local", "session_id": "agent-native:jaeger", "name": "Matthew", "max_spoken_chars": 700,
            "presence_greet_after_s": 600, "narrate_tools": True}
BIN = STATE / "droid" / "bin"
CUA = Path.home() / ".local/bin/cua-driver"
_SENTENCE = re.compile(r"[.!?](?:[\"')\]]*)(?:\s|$)|\n")


def config() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


class MicTrack:
    """aiortc audio track fed by the voice-processed microphone."""

    def __new__(cls):
        from aiortc import MediaStreamTrack

        class _Track(MediaStreamTrack):
            kind = "audio"

            def __init__(self):
                super().__init__()
                self.queue: asyncio.Queue = asyncio.Queue(maxsize=50)
                self.pts = 0

            async def recv(self):
                import av

                block = await self.queue.get()
                frame = av.AudioFrame.from_ndarray(block.reshape(1, -1), format="s16", layout="mono")
                frame.sample_rate = RATE
                frame.pts = self.pts
                frame.time_base = fractions.Fraction(1, RATE)
                self.pts += block.size
                return frame

        return _Track()


class Droid:
    def __init__(self):
        from jaeger_ai.core.gateway.client import GatewayTurnClient

        self.gateway = GatewayTurnClient(caller="cli")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.audio: DuplexAudio | None = None
        self.pc = self.dc = self.track = None
        self.tasks: list[asyncio.Task] = []
        self.ready = asyncio.Event()
        self.lock = asyncio.Lock()
        self.cfg = config()
        self.previous_output = 0
        self.request_id: str | None = None
        self.skip_rid: str | None = None
        self.pending_approval: dict | None = None
        self.bot_speaking = False
        self.heard_at = 0.0
        self.eyes: vision.Eyes | None = None
        self.transcript: deque = deque(maxlen=60)
        self.narrated = {"at": 0.0, "count": 0}
        self.screen_cache = (0.0, b"")
        self.status = {"state": "off", "awake": False, "muted": False, "engine": self.cfg["engine"],
                       "heard": "", "said": "", "latency_ms": None, "error": None,
                       "speaker": self.cfg["speaker"], "microphone": self.cfg["microphone"],
                       "voice_processing": None, "pending_approval": None, "since": time.time(),
                       "camera": "off", "faces": 0, "present": False, "action": None}
        self.write()

    # status ------------------------------------------------------------
    def set(self, **fields):
        self.status.update(fields, updated=time.time())
        self.write()

    def write(self):
        RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = RUN / "status.tmp"
        tmp.write_text(json.dumps(self.status))
        tmp.replace(RUN / "status.json")

    # wake / sleep --------------------------------------------------------
    async def wake(self, ears: bool = True):
        async with self.lock:
            if self.status["awake"]:
                return
            self.cfg = config()
            mic = permission("microphone")
            if ears and mic != "authorized":
                self.set(state="error", error=(
                    "Microphone permission needed: click Allow on the 'Jaeger Droid' prompt on the Mac, "
                    "or turn it on in System Settings > Privacy & Security > Microphone"
                    if mic in ("notDetermined", "unknown") else
                    "Microphone access is off for Jaeger Droid: System Settings > Privacy & Security > Microphone"))
                # No monitor is assumed: say it out loud with the system voice.
                _system_say("I can't hear yet. Please allow microphone access for Jaeger Droid on the Mac.",
                            self.cfg["speaker"])
                return
            self.set(state="waking", awake=True, error=None, engine=self.cfg["engine"], since=time.time())
            try:
                await asyncio.to_thread(_stop_old_conversation)
                self._route_speaker()
                self.loop = asyncio.get_running_loop()
                self.track = MicTrack()
                self.audio = DuplexAudio(self._mic, listen=ears)
                await asyncio.to_thread(self.audio.start)
                self.set(voice_processing=self.audio.voice_processing, ears=ears)
                self.audio.chime("wake")
                await self._connect()
                await asyncio.wait_for(self.ready.wait(), 30)
                self.say(persona.greeting(self.cfg["name"]))
                self.set(state="listening")
                self._open_eyes()
                asyncio.create_task(asyncio.to_thread(_ensure_cua_driver))
            except Exception as exc:
                log.exception("wake failed")
                await self._teardown()
                self.set(state="error", awake=False, error=f"Could not wake: {exc}")

    async def sleep(self, farewell: bool = True):
        async with self.lock:
            if not self.status["awake"]:
                return
            self.set(state="sleeping")
            if farewell and self.dc is not None and self.ready.is_set():
                self.say(persona.farewell())
                deadline = time.monotonic() + 8
                started = False
                while time.monotonic() < deadline:
                    started = started or self.bot_speaking
                    if started and not self.bot_speaking:
                        break
                    await asyncio.sleep(0.1)
            if self.audio:
                self.audio.chime("sleep")
                await asyncio.sleep(0.6)
            await self._teardown()
            self.set(state="off", awake=False, heard="", latency_ms=None, pending_approval=None, since=time.time())

    async def toggle(self):
        await (self.sleep() if self.status["awake"] else self.wake())

    def _open_eyes(self):
        if permission("camera") != "authorized":
            self.set(camera="needs permission")
            return
        loop = asyncio.get_running_loop()
        self.eyes = vision.Eyes(
            self.cfg["camera"],
            on_presence=lambda away, faces: loop.call_soon_threadsafe(self._presence, away, faces),
            report=lambda **f: loop.call_soon_threadsafe(lambda: self.set(**f)))
        self.eyes.start()

        def ready_head():
            vision.warm()
            time.sleep(1.5)  # the gimbal leaves its privacy pose once streaming starts
            self.eyes and self.eyes.head.point(0, 0)

        asyncio.create_task(asyncio.to_thread(ready_head))

    def _presence(self, away: float, faces: int):
        """Someone came into view: welcome them back after a real absence."""
        if (not self.status["awake"] or self.bot_speaking or self.request_id or self.pending_approval
                or away < float(self.cfg.get("presence_greet_after_s") or 600)):
            return
        self.say(f"Ah, welcome back, {self.cfg['name']}." if faces == 1 else "Hello there, everyone.")

    async def _teardown(self):
        if self.eyes:
            eyes, self.eyes = self.eyes, None

            def close():
                eyes.head.point(0, -85)  # privacy pose: the camera looks down while asleep
                time.sleep(1.0)
                eyes.stop()

            await asyncio.to_thread(close)
        for task in self.tasks:
            task.cancel()
        self.tasks = []
        self.ready.clear()
        pc, self.pc, self.dc = self.pc, None, None
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                pass
        if self.audio:
            await asyncio.to_thread(self.audio.stop)
            self.audio = None
        self.bot_speaking = False
        self.pending_approval = None
        self._restore_speaker()

    def _route_speaker(self):
        wanted = coreaudio.find(self.cfg["speaker"])
        current = coreaudio.default_device(True)
        if wanted and wanted != current:
            self.previous_output = current
            coreaudio.set_default_device(wanted)
        self.set(speaker=coreaudio.device_name(wanted or current))

    def _restore_speaker(self):
        if self.previous_output:
            coreaudio.set_default_device(self.previous_output)
            self.previous_output = 0

    # media -------------------------------------------------------------
    def _mic(self, block: np.ndarray):
        loop, track = self.loop, self.track
        if loop is None or track is None:
            return

        def put():
            if track.queue.full():
                track.queue.get_nowait()
            track.queue.put_nowait(block)

        loop.call_soon_threadsafe(put)

    async def _connect(self):
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        pc = self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        pc.addTrack(self.track)
        dc = self.dc = pc.createDataChannel("jaeger", ordered=True)

        @pc.on("track")
        def _track(track):
            if track.kind == "audio":
                self.tasks.append(asyncio.create_task(self._pump(track)))

        @pc.on("connectionstatechange")
        async def _state():
            if pc.connectionState in ("failed", "closed") and self.status["awake"] and self.pc is pc:
                self.set(state="error", error="Lost the voice service connection")
                asyncio.create_task(self._reconnect())

        @dc.on("open")
        def _open():
            self.tasks.append(asyncio.create_task(self._ping(dc)))

        @dc.on("message")
        def _message(raw):
            if isinstance(raw, str):
                try:
                    message = json.loads(raw)
                except ValueError:
                    return
                if isinstance(message, dict) and isinstance(message.get("t"), str):
                    self._service(message)

        await pc.setLocalDescription(await pc.createOffer())
        body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
                "request_data": {"engine": self.cfg["engine"], "history": [], "client": "droid"}}
        async with ClientSession(timeout=ClientTimeout(total=20)) as http:
            async with http.post(VOICE_URL + "/offer", json=body) as response:
                if response.status != 200:
                    raise RuntimeError(f"voice service answered HTTP {response.status}")
                answer = await response.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

    async def _reconnect(self):
        await asyncio.sleep(2)
        if not self.status["awake"] or (self.pc and self.pc.connectionState == "connected"):
            return
        try:
            self.ready.clear()
            old, self.pc = self.pc, None
            if old:
                await old.close()
            self.track = MicTrack()
            await self._connect()
            await asyncio.wait_for(self.ready.wait(), 30)
            self.set(state="listening", error=None)
        except Exception as exc:
            self.set(state="error", error=f"Voice service unavailable: {exc}")

    async def _ping(self, dc):
        while dc.readyState == "open":
            dc.send(f"ping: {int(time.time() * 1000)}")
            await asyncio.sleep(1)

    async def _pump(self, track):
        """Speech from the voice service to the speakers (exact-zero filler dropped)."""
        batch: list[np.ndarray] = []
        while True:
            frame = await track.recv()
            data = frame.to_ndarray()
            channels = len(frame.layout.channels)
            if data.dtype == np.int16:
                data = data.astype(np.float32) / 32768.0
            data = data.reshape(-1, channels).mean(axis=1) if data.shape[0] == 1 else data.mean(axis=0)
            if frame.sample_rate != RATE:
                n = int(round(data.size * RATE / frame.sample_rate))
                data = np.interp(np.linspace(0, data.size - 1, n), np.arange(data.size), data)
            if not np.any(data):
                if batch:
                    self.audio and self.audio.play(np.concatenate(batch).astype(np.float32))
                    batch = []
                continue
            batch.append(data)
            if sum(b.size for b in batch) >= BLOCK * 3:
                self.audio and self.audio.play(np.concatenate(batch).astype(np.float32))
                batch = []

    # voice service events ----------------------------------------------
    def _service(self, m: dict):
        kind = m.get("t")
        if kind == "ready":
            self.ready.set()
        elif kind == "user-speaking":
            if self.bot_speaking:
                self._barge_in()
            self.set(state="hearing")
        elif kind == "user-partial":
            self.set(heard=str(m.get("text") or ""))
        elif kind == "user-final":
            text = str(m.get("text") or "").strip()
            self.heard_at = time.time()
            if text:
                self.set(heard=text)
                asyncio.create_task(self.on_heard(text))
            else:
                self.set(state="listening")
        elif kind == "interrupted":
            self.audio and self.audio.flush()
        elif kind == "bot-speaking":
            self.bot_speaking = bool(m.get("on"))
            if self.bot_speaking:
                fields = {"state": "speaking"}
                if self.heard_at:
                    fields["latency_ms"] = round((time.time() - self.heard_at) * 1000)
                    self.heard_at = 0.0
                self.set(**fields)
            elif self.status["state"] == "speaking":
                self.set(state="thinking" if self.request_id else "listening")
        elif kind == "tool":  # Gemini Live hands real work to full Jaeger
            asyncio.create_task(self._tool(str(m.get("id")), str(m.get("request") or "")))
        elif kind == "transcript":
            asyncio.create_task(asyncio.to_thread(self._save_transcript, m))
        elif kind == "error":
            self.set(error=str(m.get("message") or "voice service error"))

    def _barge_in(self):
        self.audio and self.audio.flush()
        self.skip_rid = self.request_id
        self._send({"t": "stop"})

    def _send(self, message: dict):
        if self.dc is not None and self.dc.readyState == "open":
            self.dc.send(json.dumps({"type": "jaeger", **message}))

    def note(self, role: str, text: str):
        """Recent conversation for the live Droid view (assistant chunks join)."""
        now = time.time()
        if role == "assistant" and self.transcript and self.transcript[-1]["role"] == "assistant" \
                and now - self.transcript[-1]["at"] < 12:
            self.transcript[-1]["text"] = (self.transcript[-1]["text"] + " " + text)[-1200:]
            self.transcript[-1]["at"] = now
        else:
            self.transcript.append({"role": role, "text": text[-1200:], "at": now})

    def say(self, text: str):
        text = persona.speakable(text)
        if text:
            self._send({"t": "speak", "text": text[:2000]})
            self.set(said=text[-400:])
            self.note("assistant", text)

    def stop_talking(self):
        self._barge_in()
        self.set(state="listening")

    # turns -------------------------------------------------------------
    async def on_heard(self, text: str):
        self.note("user", text)
        if self.pending_approval:
            choice = persona.decision(text)
            if choice is None:
                self.say("Forgive me, I need a clear answer. Shall I proceed? Yes or no?")
                return
            approval, self.pending_approval = self.pending_approval, None
            self.set(pending_approval=None)
            options = approval.get("options") or ["once", "deny"]
            if choice == "always" and "always" not in options:
                choice = "once"
            try:
                await asyncio.to_thread(self.gateway.resolve_approval, approval["approval_id"], choice)
                self.say("Very good. Proceeding." if choice != "deny" else "Understood. I won't do that.")
            except Exception as exc:
                self.say("I'm afraid I couldn't record your answer. Please check the chat.")
                log.warning("approval resolve failed: %s", exc)
            return
        action = persona.command(text)
        if action == "sleep":
            await self.sleep()
            return
        if action == "stop":
            self.stop_talking()
            return
        move = persona.head_move(text)
        if move:
            await self.move_head(*move)
            return
        sight = persona.visual(text)
        if sight:
            asyncio.create_task(self.see(text, around=sight == "around"))
            return
        rid = self.request_id
        if rid:
            try:
                await asyncio.to_thread(self.gateway.steer, self.cfg["session_id"], rid, text)
                return
            except Exception:
                pass
        asyncio.create_task(self.turn(text))

    async def move_head(self, pan: float, tilt: float, absolute: bool = False):
        if not self.eyes:
            self.say("My camera is off, so I can't turn my head just now.")
            return
        label = persona.move_phrase(pan, tilt, absolute)
        self.say(label)
        head = self.eyes.head
        ok = await asyncio.to_thread(head.point if absolute else head.nudge, pan, tilt)
        if not ok:
            self.say("I'm afraid my neck isn't responding.")

    async def see(self, question: str, around: bool = False):
        """Answer a question about the room from the local camera and vision model only."""
        if not self.eyes:
            self.say("My eyes are closed: I need camera permission for Jaeger Droid, or the camera is busy.")
            return
        self.set(state="thinking", action="looking around" if around else "looking")
        if around:
            self.say("Let me have a look around.")
        elif not await asyncio.to_thread(vision.is_warm):
            self.say("One moment, my eyes are still focusing.")
        started = time.time()
        try:
            answer = await asyncio.to_thread(self.eyes.look_around if around else self.eyes.look, question)
        except Exception as exc:
            log.warning("vision failed: %s", exc)
            answer = "I'm afraid my vision system isn't answering right now."
        self.set(action=None, vision_ms=round((time.time() - started) * 1000))
        self.say(answer)
        if self.status["state"] == "thinking":
            self.set(state="listening")

        def save():
            for role, text in (("user", question), ("assistant", answer)):
                self._save_transcript({"role": role, "text": text, "engine": "droid-vision"})

        await asyncio.to_thread(save)

    def _narrate(self, data: dict):
        if not self.cfg.get("narrate_tools", True):
            return
        line = persona.narrate(str(data.get("tool") or data.get("name") or ""), data.get("args") or data.get("input") or {})
        now = time.time()
        if line and now - self.narrated["at"] > 6 and self.narrated["count"] < 5:
            self.narrated.update(at=now, count=self.narrated["count"] + 1)
            self.set(action=line)
            self.say(line)

    async def turn(self, text: str, *, full: bool = False) -> str:
        rid = uuid.uuid4().hex
        self.request_id, self.skip_rid = rid, None
        self.narrated = {"at": 0.0, "count": 0}
        self.set(state="thinking", error=None)
        spoken = {"pending": "", "chars": 0, "any": False, "capped": False}
        loop = asyncio.get_running_loop()
        cap = int(self.cfg.get("max_spoken_chars") or 700)

        def speak(chunk: str):
            if self.skip_rid == rid or spoken["capped"] or not chunk.strip():
                return
            if spoken["chars"] + len(chunk) > cap and spoken["any"]:
                spoken["capped"] = True
                self.say("The rest is in the chat.")
                return
            spoken["chars"] += len(chunk)
            spoken["any"] = True
            self.say(chunk)

        def on_event(name, data):
            loop.call_soon_threadsafe(handle, name, data)

        def handle(name, data):
            if name == "turn.delta" and not full:
                spoken["pending"] += str(data.get("delta") or "")
                while match := _SENTENCE.search(spoken["pending"]):
                    speak(spoken["pending"][:match.end()])
                    spoken["pending"] = spoken["pending"][match.end():]
                if len(spoken["pending"]) > 300:
                    cut = spoken["pending"].rfind(" ", 0, 300)
                    cut = cut if cut > 0 else 300
                    speak(spoken["pending"][:cut])
                    spoken["pending"] = spoken["pending"][cut:]
            elif name == "tool.started" and not full and self.skip_rid != rid:
                self._narrate(data)
            elif name == "approval.request" and data.get("approval_id"):
                self.pending_approval = data
                prompt = str(data.get("title") or data.get("prompt") or "take an action")
                self.set(pending_approval=prompt)
                self.say(f"I need your permission. {prompt} Shall I proceed?")

        try:
            result = await asyncio.to_thread(
                self.gateway.stream_turn, self.cfg["session_id"], persona.frame(text), on_event=on_event,
                request_id=rid, timeout_s=900, fast_lane=not full, display_text=text)
            if full:
                return result.text if result.ok else f"Jaeger could not finish: {result.error or result.status}"
            if result.ok:
                speak(spoken["pending"])
                if not spoken["any"] and result.text:
                    speak(result.text)
            elif self.skip_rid != rid and result.status != "cancelled":
                self.say("I'm terribly sorry, that didn't work. The details are in the chat.")
                self.set(error=result.error or result.status)
            return result.text
        except Exception as exc:
            log.warning("turn failed: %s", exc)
            if not full:
                self.say("I'm afraid I can't reach my thinking core right now.")
            self.set(error=str(exc))
            return ""
        finally:
            if self.request_id == rid:
                self.request_id = None
                self.set(action=None)
                if self.status["state"] == "thinking":
                    self.set(state="listening")

    async def _tool(self, call_id: str, request: str):
        text = await self.turn(request, full=True)
        self._send({"t": "tool-result", "id": call_id, "text": text[:6000]})

    def _save_transcript(self, m: dict):
        try:
            from urllib.parse import quote
            self.gateway._call("POST", f"/v1/sessions/{quote(self.cfg['session_id'], safe='')}/voice-transcript",
                               {"role": m.get("role"), "text": m.get("text"), "engine": m.get("engine") or "gemini",
                                "interrupted": bool(m.get("interrupted"))})
        except Exception as exc:
            log.warning("transcript not saved: %s", exc)


def _ensure_cua_driver():
    """Computer use and the live screen view go through CuaDriver (its own permissions)."""
    import subprocess
    if not CUA.exists():
        return
    status = subprocess.run([str(CUA), "status"], capture_output=True, text=True, timeout=10)
    if "not running" in (status.stdout + status.stderr):
        subprocess.run(["/usr/bin/open", "-n", "-g", "-a", "CuaDriver", "--args", "serve"], capture_output=True)


def screen_jpeg(width: int = 1280) -> bytes | None:
    """The main display, via CuaDriver's screenshot (works on a virtual display too)."""
    import subprocess

    import cv2
    out = RUN / "screen.png"
    try:
        _ensure_cua_driver()
        subprocess.run([str(CUA), "call", "get_desktop_state", json.dumps({"screenshot_out_file": str(out)})],
                       capture_output=True, timeout=10)
        img = cv2.imread(str(out))
        out.unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes() if ok else None


def display_info() -> dict:
    """Online displays and whether each is a real monitor or a virtual one."""
    try:
        import Quartz
        err, ids, count = Quartz.CGGetOnlineDisplayList(16, None, None)
        rows = []
        for d in ids[:count]:
            vendor = Quartz.CGDisplayVendorNumber(d)
            rows.append({"id": int(d), "width": int(Quartz.CGDisplayPixelsWide(d)),
                         "height": int(Quartz.CGDisplayPixelsHigh(d)), "main": bool(Quartz.CGDisplayIsMain(d)),
                         "virtual": vendor in (0x756E6B6E, 0) or Quartz.CGDisplayModelNumber(d) == 0x76697274})
        return {"displays": rows, "headless": bool(rows) and all(r["virtual"] for r in rows)}
    except Exception as exc:
        return {"displays": [], "error": str(exc)}


def _system_say(text: str, device: str = ""):
    import subprocess
    args = ["/usr/bin/say"] + (["-a", device] if device else []) + [text]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def permission(kind: str) -> str:
    """The host app's macOS permission for ``microphone`` / ``camera``."""
    try:
        return str(json.loads((RUN / "permissions.json").read_text()).get(kind) or "unknown")
    except (OSError, ValueError):
        return "unknown"


def _stop_old_conversation():
    """The older Stream Deck voice chat shares the microphone; switch it off."""
    path = STATE / "run" / "conversation" / "control.sock"
    if not path.exists():
        return
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(5)
            s.connect(str(path))
            s.sendall(b"status\n")
            status = json.loads(s.makefile("rb").readline(65536) or b"{}")
        if status.get("mode", "off") != "off":
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(10)
                s.connect(str(path))
                s.sendall(b"off\n")
                s.makefile("rb").readline(65536)
    except (OSError, ValueError):
        pass


def app(droid: Droid) -> web.Application:
    routes = web.RouteTableDef()

    @routes.get("/status")
    async def status(_r):
        return web.json_response(droid.status)

    def action(fn):
        async def handler(request):
            body = {}
            if request.can_read_body:
                try:
                    body = await request.json()
                except ValueError:
                    body = {}
            result = fn(body if isinstance(body, dict) else {})
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
            return web.json_response(droid.status)
        return handler

    def mute(_b):
        if droid.audio:
            droid.audio.muted = not droid.audio.muted
            droid.set(muted=droid.audio.muted)

    @routes.get("/transcript")
    async def transcript(_r):
        return web.json_response({"lines": list(droid.transcript), "status": droid.status})

    @routes.get("/camera.jpg")
    async def camera(_r):
        img = droid.eyes.jpeg(width=960, max_age=5) if droid.eyes else None
        if not img:
            return web.json_response({"error": "camera off"}, status=404)
        return web.Response(body=img, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @routes.get("/screen.jpg")
    async def screen(_r):
        at, img = droid.screen_cache
        if time.time() - at > 0.8 or not img:
            img = await asyncio.to_thread(screen_jpeg) or b""
            droid.screen_cache = (time.time(), img)
        if not img:
            return web.json_response({"error": "screen unavailable"}, status=404)
        return web.Response(body=img, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @routes.get("/display")
    async def display(_r):
        return web.json_response(await asyncio.to_thread(display_info))

    routes.post("/look")(action(lambda b: droid.see(str(b.get("question") or "What do you see?"),
                                                    around=bool(b.get("around"))) if droid.status["awake"] else None))
    routes.post("/wake")(action(lambda b: droid.wake(ears=b.get("ears") is not False)))
    routes.post("/sleep")(action(lambda b: droid.sleep()))
    routes.post("/toggle")(action(lambda b: droid.toggle()))
    routes.post("/mute")(action(mute))
    routes.post("/stop")(action(lambda b: droid.stop_talking()))
    routes.post("/say")(action(lambda b: droid.say(str(b.get("text") or ""))))
    routes.post("/hear")(action(lambda b: droid.on_heard(str(b.get("text") or "")) if droid.status["awake"] else None))
    application = web.Application()
    application.add_routes(routes)
    return application


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUN.chmod(0o700)
    droid = Droid()
    runner = web.AppRunner(app(droid))
    await runner.setup()
    sock = RUN / "control.sock"
    sock.unlink(missing_ok=True)
    await web.UnixSite(runner, str(sock)).start()
    sock.chmod(0o600)
    log.info("droid standing by on %s", sock)
    keeper = None
    if (BIN / "droid-display").exists():
        import subprocess
        keeper = subprocess.Popen([str(BIN / "droid-display")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stop = asyncio.Event()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    if config().get("wake_on_start"):
        asyncio.create_task(droid.wake())
    await stop.wait()
    await droid.sleep(farewell=False)
    await runner.cleanup()
    sock.unlink(missing_ok=True)
    if keeper:
        keeper.terminate()
    droid.set(state="off", awake=False)


if __name__ == "__main__":
    asyncio.run(main())
