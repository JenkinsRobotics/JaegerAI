"""Headless core multimodal orchestrator backed by an injected AgentRuntime.

The audio, turn-taking, and vision transport are the verified VoiceLLM
framework.  The brain substitution is intentional: JaegerAgent's runtime owns
tools, skills, prompts, and conversation memory.  The optional ``llm-gemma``
node remains available only as the playground's non-agentic baseline.
"""
from __future__ import annotations

import difflib
import importlib.util
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .config import MultimodalConfig
from .contracts import AgentRuntime, normalize_turn_result
from .node import resolve_runtime_factory

from . import context as ctx
from .context import (
    CONTEXT_PROMPT_ADDON,
    HOLD_MAX_S,
    SELF_ECHO_WINDOW_S,
    TurnAnnotator,
    _SELF_VOICE,
    is_echo_garble,
    is_own_voice_echo,
    is_stock_hallucination,
    llm_user_text,
)
from .events import Event, _TurnShim
from .outputs import DYNAMIC_OUTPUT_PROMPT, OutputMode, decide_output, multimodal_output_scope
from .policy import (
    FRAME_MS,
    MIN_SPEECH_MS,
    SAMPLE_RATE,
    SILENCE_HANGOVER_MS,
    SILERO_CLOSE_P,
    SILERO_OPEN_P,
    SYSTEM_PROMPT,
    TTS_RATE,
    SileroVad,
    _match_wake,
    agent_asked_question,
    closes_conversation,
    committed_user_text,
    followup_window,
    is_non_speech,
    turn_started_in_followup,
)

HERE = Path(__file__).resolve().parent.parent




def _load_node(relative_path: str, name: str) -> Any:
    """Load a portable hyphen-named node folder without renaming it."""
    path = HERE / relative_path
    qualified = f"jaeger_agent.nodes.{name}"
    existing = sys.modules.get(qualified)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load multimodal node at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


dxr = _load_node("nodes/audio-duplex-io/runtime.py", "audio_duplex_io")
strm = _load_node("nodes/stt-streaming/runtime.py", "stt_streaming")
stt_mod = _load_node("nodes/stt-whisper/runtime.py", "stt_whisper")
vis_mod = _load_node("nodes/vision-mmproj/runtime.py", "vision_mmproj")
llm_mod = _load_node("nodes/llm-gemma/runtime.py", "llm_gemma")
tts_mod = _load_node("nodes/tts-kokoro/runtime.py", "tts_kokoro")

AudioIO = dxr.AudioIO
BargeMonitor = dxr.BargeMonitor
_agc_gain = dxr._agc_gain
DriftAnchor = strm.DriftAnchor
IncrementalTranscriber = strm.IncrementalTranscriber
StreamAnnotator = strm.StreamAnnotator
StreamGovernor = strm.StreamGovernor
UtteranceAggregator = strm.UtteranceAggregator
sentence_turn = strm.sentence_turn


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in reversed(content):
            if isinstance(block, Mapping) and block.get("type") == "text":
                return str(block.get("text") or "")
    return str(content)


class AgentRuntimeBrain:
    """Present an AgentRuntime through the playground node interface.

    ``remember`` is intentionally empty: the runtime's per-session agent owns
    the transcript.  Keeping the old eight-exchange log as well would submit
    every prior turn twice.
    """

    def __init__(self, runtime: AgentRuntime, session_key: str) -> None:
        self.runtime = runtime
        self._base_session_key = session_key
        self._generation = 0
        self.llm = None

    @property
    def session_key(self) -> str:
        suffix = f":{self._generation}" if self._generation else ""
        return f"{self._base_session_key}{suffix}"

    @property
    def history(self) -> list:
        return []

    def load(
        self,
        chat_handler=None,
        say=print,
        *,
        system_prompt: str = "",
        **_kwargs: Any,
    ) -> None:
        configure = getattr(self.runtime, "configure_vision", None)
        if chat_handler is not None and callable(configure):
            configure(chat_handler)
        say("using injected AgentRuntime (runtime-owned conversation memory)")
        warmup = getattr(self.runtime, "warmup", None)
        if callable(warmup):
            say("warming AgentRuntime brain…")
            warmup(session_key=self.session_key, system_prompt=system_prompt)

    def answer(self, content: Any, system: str) -> str:
        multimodal = getattr(self.runtime, "run_multimodal_turn", None)
        if callable(multimodal):
            value = multimodal(
                content,
                text=_plain_text(content),
                system_prompt=system,
                session_key=self.session_key,
            )
        elif isinstance(content, str):
            value = self.runtime.run_turn(content, session_key=self.session_key)
        else:
            raise RuntimeError(
                "the injected AgentRuntime does not accept image content; "
                "implement run_multimodal_turn() or disable vision"
            )
        result = normalize_turn_result(value)
        if result.error:
            raise RuntimeError(result.error)
        return result.text.strip()

    def remember(self, _user_text: str, _reply: str) -> None:
        """No-op: AgentRuntime is the sole conversation-memory owner."""

    def clear(self) -> None:
        clear = getattr(self.runtime, "clear_session", None)
        if callable(clear):
            clear(self.session_key)
        self._generation += 1

    def close(self) -> None:
        self.runtime.close()

class GemmaMultimodal:
    """The engine. Feed it audio, text and images; it emits Events.

    It owns no thread and no window. `push_audio` is called with whatever
    frames the caller has — a microphone callback, a WAV replay, a Qt worker —
    and every decision comes back through `on_event`. The only blocking call
    is playback, which is intrinsic to half duplex: the mic is closed for
    exactly as long as the speaker is busy.
    """

    FRAME = SAMPLE_RATE * FRAME_MS // 1000
    # 2.5s, not 1.5: the endpoint hangover alone is 1.8s, so a turn built
    # from playback echo ARRIVES ~1.8s after playback ends — the old grace
    # expired 0.3s too early and the agent answered its own reply in a loop.
    SELF_ECHO_GRACE_S = 2.5
    MAX_TOKENS = 160

    def __init__(
        self,
        on_event=None,
        want_vision: bool = False,
        extra_prompt: str = "",
        play: bool = True,
        half_duplex: bool = True,
        audio_mode: str | None = None,
        output_mode: OutputMode | None = None,
        *,
        runtime: AgentRuntime | None = None,
        runtime_factory: str | Any | None = None,
        runtime_config: Mapping[str, Any] | None = None,
        config: MultimodalConfig | Mapping[str, Any] | None = None,
        use_offline_fallback: bool = False,
    ) -> None:
        output_was_explicit = output_mode is not None
        if isinstance(config, Mapping):
            output_was_explicit = output_was_explicit or "output_mode" in config
        elif isinstance(config, MultimodalConfig):
            output_was_explicit = output_was_explicit or (
                "output_mode" in config.model_fields_set
            )
        self.config = (
            config
            if isinstance(config, MultimodalConfig)
            else MultimodalConfig.model_validate(config or {})
        )
        if output_mode is not None:
            if output_mode not in {"dynamic", "speech", "text", "mirror"}:
                raise ValueError("output_mode must be dynamic|speech|text|mirror")
            self.config = self.config.model_copy(update={"output_mode": output_mode})
        chatbot_requested = bool(
            runtime_config is not None
            and runtime_config.get("tools_enabled") is False
        )
        if not output_was_explicit and (use_offline_fallback or chatbot_requested):
            # Both lanes intentionally reproduce the imported Gemma baseline.
            # They cannot select an output tool, so dynamic would silently
            # turn the historical spoken assistant into a text-only one.
            self.config = self.config.model_copy(update={"output_mode": "speech"})
        audio_mode = audio_mode or self.config.audio_mode
        self.on_event = on_event or (lambda ev: None)
        # Half is the DEFAULT and the name of the file, because it is the mode
        # that needs no echo canceller. Setting this False leaves the mic open
        # so you can interrupt, and leans on the self-echo guard below — which
        # catches the runaway loop but not a voice talking OVER the agent.
        self.half_duplex = half_duplex
        self.want_vision = want_vision
        self.extra_prompt = extra_prompt.strip()
        self.play = play
        self.llm = self.tts = self.stt = None
        # the agent is COMPOSED of nodes — each capability its own folder
        self.node_stt = stt_mod.build()
        self.node_vision = vis_mod.build()
        if runtime is not None and use_offline_fallback:
            raise ValueError("runtime and use_offline_fallback are mutually exclusive")
        if use_offline_fallback:
            self.node_llm = llm_mod.build()
        else:
            if runtime is None:
                factory = resolve_runtime_factory(
                    runtime_factory or "jaeger_agent.core.runtime:create_runtime"
                )
                agent_config = dict(runtime_config or {})
                provider = str(agent_config.get("provider") or "llama_cpp").lower()
                if provider in {"llama_cpp", "llama-cpp", "local", "local-llama"}:
                    agent_config.setdefault(
                        "model_path", self.config.fallback_llm_model_path
                    )
                runtime = factory(config=agent_config)
            self.node_llm = AgentRuntimeBrain(runtime, self.config.session_key)
        self.node_tts = tts_mod.build()
        self.vision_ready = False

        self._vad = None
        self._frames: list[np.ndarray] = []
        self._in_speech = False
        self._voiced = self._silent = 0
        self._started = 0.0
        self._hang = max(1, SILENCE_HANGOVER_MS // FRAME_MS)
        self._minb = max(1, MIN_SPEECH_MS // FRAME_MS)

        self.speaking = threading.Event()
        self._pending_image: str | None = None
        self._last_spoken = ""
        self._last_spoken_at = 0.0
        self._followup_deadline = 0.0
        self._turns = 0
        self._closing = False
        self._paused = threading.Event()
        self._force_listen_evt = threading.Event()
        self._index = 0
        self._residue = np.zeros(0, dtype=np.float32)
        #: caller-registered: empty the input queue feeding push_audio.
        #: The original MicStream drains ITS queue on pause and on resume;
        #: this engine does not own the queue, so the owner hands us the drain.
        self.drain_input = lambda: None
        # ONE STT lock: live preview and final decode share the node's lock.
        self._stt_lock = self.node_stt._lock
        # ── audio pipeline: one of the four verified input modes ──
        assert audio_mode in ("plain", "structured", "quasi", "full"), audio_mode
        self.audio_mode = audio_mode
        self.annotator = TurnAnnotator() if audio_mode != "plain" else None
        self._prev_end = {"t": None}
        self._hold = {"text": "", "deadline": 0.0, "turns": []}
        self._agc = {"peak": 0.0, "noise": 0.02}
        self._io = None
        self._ear_stop = threading.Event()
        self._ear_thread = None
        self._preview_stop = threading.Event()
        self._preview_thread = None
        self._seng = self._sgov = self._sanchor = self._sann = None
        self._agg = UtteranceAggregator() if audio_mode == "full" else None
        self._label_q: list = []
        # one brain: typed, spoken, and held turns all respond through this
        # lock, so a typed message during duplex speech serializes instead
        # of racing the LLM
        self._respond_lock = threading.Lock()
        self._mode_lock = threading.Lock()
        self._pending_agentic_mode: bool | None = None

        self._preview_decoded = 0             # frames already previewed

    # -- events ------------------------------------------------------------
    def _emit(self, kind: str, text: str = "", data=None) -> None:
        self.on_event(Event(kind, text, data))

    # -- startup -----------------------------------------------------------
    def load(self) -> None:
        """Load perception/speech nodes and connect vision to the brain."""
        t0 = time.perf_counter()
        handler = self.node_vision.load(
            self.want_vision,
            self._say,
            model_path=self.config.vision_mmproj_path,
        )
        self.vision_ready = self.node_vision.ready
        # Warm the exact tool schema used for real turns. External TTS tools
        # stay hidden because final speech belongs to this engine's own node.
        with multimodal_output_scope():
            self.node_llm.load(
                handler,
                self._say,
                model_path=self.config.fallback_llm_model_path,
                system_prompt=self._system_prompt(),
            )
        self.llm = getattr(self.node_llm, "llm", None)
        self.node_tts.load(
            self._say,
            voice=self.config.kokoro_voice,
            language=self.config.kokoro_language,
        )
        self.tts = self.node_tts.tts
        self.node_stt.load(self._say, model_name=self.config.stt_model)
        self.stt = self.node_stt.model
        self._vad = SileroVad(self.config.silero_model_path)

        if self.audio_mode in ("quasi", "full"):
            if dxr.pyaec is None:
                raise RuntimeError(
                    "pyaec is required for quasi/full audio_mode; "
                    "install jaeger-agent[multimodal-duplex]")
            self._say(f"opening 48 kHz AEC duplex device ({self.audio_mode} audio_mode)…")
            self._io = AudioIO().__enter__()
            if self.audio_mode == "full":
                self._sann = StreamAnnotator()
                self._seng = IncrementalTranscriber(self.stt)

                def _on_commit(a):
                    self._sann.label(a)
                    self._label_q.append({**(self._sann.last or {}),
                                          "_fp": self._sann.last_fp})
                self._seng.on_commit_audio = _on_commit
                self._sgov = StreamGovernor()
                self._sanchor = DriftAnchor()
            self._ear_thread = threading.Thread(
                target=(self._ear_loop_full if self.audio_mode == "full"
                        else self._ear_loop_quasi), daemon=True)
            self._ear_thread.start()
        self._emit("session", "Audio", self.audio_mode)

        # Each node owns exactly one warmup inside ``load``. In particular the
        # AgentRuntime adapter warms directly, so no synthetic turn enters its
        # transcript. Do not repeat STT/TTS inference here.
        self._say(f"primed in {(time.perf_counter() - t0) * 1000:.0f} ms")
        self._preview_thread = threading.Thread(
            target=self._preview_loop,
            daemon=True,
            name="multimodal-live-preview",
        )
        self._preview_thread.start()
        self._emit("status", "ready")
        self._emit("state", "listening")

    # -- live preview -------------------------------------------------------
    def _preview_loop(self) -> None:
        """Decode the FORMING turn every second, like the CLI's LIVE panel.

        Silence between "you started talking" and "here is what you said" is
        where a voice app feels deaf — the console UI solved it by re-decoding
        the accumulating audio once a second and showing the churn. Same model
        as the final pass, behind one lock, and nothing shown here is ever
        committed: the endpoint flush is still the only writer of record.
        """
        while not self._preview_stop.wait(1.0):
            try:
                self._preview_pass()
            except Exception:
                pass                  # a failed preview must never disturb it

    def _preview_pass(self) -> None:
        if not self._in_speech or self.speaking.is_set() or self.stt is None:
            return
        frames = list(self._frames)                    # snapshot, no lock
        if len(frames) - self._preview_decoded < 16:   # <0.5s of new audio
            return
        self._preview_decoded = len(frames)
        audio = np.concatenate(frames[-500:])          # cap the window at 15s
        with self._stt_lock:
            if not self._in_speech:                    # turn ended while queued
                return
            text = " ".join(x.text for x in
                            self.stt.transcribe(audio, language="en")).strip()
        if text and self._in_speech:
            self._emit("live", text + " \u258c")

    def _say(self, msg: str) -> None:
        print(f"[gemma-multimodal] {msg}", flush=True)
        self._emit("status", msg)

    # -- input 1: text -----------------------------------------------------
    def send_text(self, text: str) -> None:
        """Typed input skips the wake gate: typing IS addressing it.

        FULL DUPLEX APPLIES TO EVERY INPUT: with duplex audio pipeline this can arrive
        while the agent is speaking. A typed message is an explicit
        interruption, so it follows the same floor policy as voice —
        dxr.BARGE_MODE stop cuts playback and answers; continue lets the agent
        finish, then answers (the respond lock serializes the brain)."""
        text = text.strip()
        if not text or self._closing:
            return
        if self.speaking.is_set() and dxr.BARGE_MODE == "stop":
            self.force_listen()
        self._emit("user", text)
        if closes_conversation(text):
            self._dismiss()
            return
        self._respond(text, input_modality="text")

    # -- input 2: vision ---------------------------------------------------
    def attach_image(self, data_uri: str) -> None:
        """Hold one image for the next turn, whether typed or spoken."""
        if not data_uri:
            return
        # Only announce the TRANSITION. A live camera calls this once a
        # second, and a status line that repeats every second is a status
        # line nobody reads.
        first = self._pending_image is None
        self._pending_image = data_uri
        if first:
            self._emit("status", "image attached to your next message")

    # -- input 3: audio ----------------------------------------------------
    def push_audio(self, frame: np.ndarray) -> None:
        """One frame in. Endpointing, then the five stages on a full turn."""
        if self._closing or self._paused.is_set():
            return
        if self.half_duplex and self.speaking.is_set():
            return                    # half duplex: the mic is closed
        # Accept ANY block size and re-chunk internally. Requiring exactly one
        # frame length made this a silent no-op for every caller whose audio
        # device disagreed — sounddevice hands out whatever blocksize it was
        # opened with, and a mismatch dropped every frame without a word. An
        # engine that ignores its only input must say so or handle it; this
        # handles it.
        if self.audio_mode in ("quasi", "full"):
            return                    # duplex audio pipeline own their AEC device
        self._tick_hold()
        block = np.asarray(frame, dtype=np.float32).reshape(-1)
        if block.size == 0:
            return
        rms = float(np.sqrt(np.mean(block ** 2)))
        self._agc["peak"] = max(rms, self._agc["peak"] * 0.998)
        self._agc["noise"] = min(max(rms, 1e-4),
                                 self._agc["noise"] * 1.0005)
        block = block * _agc_gain(self._agc["peak"], self._agc["noise"])
        self._residue = np.concatenate([self._residue, block])
        while self._residue.size >= self.FRAME:
            piece, self._residue = (self._residue[:self.FRAME],
                                    self._residue[self.FRAME:])
            self._push_frame(piece)

    def _push_frame(self, frame: np.ndarray) -> None:
        p = self._vad.probability(frame)
        bar = SILERO_CLOSE_P if self._in_speech else SILERO_OPEN_P
        if p >= bar:
            if not self._in_speech:
                self._in_speech = True
                self._voiced = self._silent = 0
                self._frames = []
                self._started = time.time()
                self._emit("state", "hearing you")
                self._emit("latency", "Speech detected", 0.0)
            self._frames.append(frame)
            self._voiced += 1
            self._silent = 0
            return
        if not self._in_speech:
            return
        self._frames.append(frame)
        self._silent += 1
        if not (self._voiced >= self._minb and self._silent >= self._hang):
            return
        audio = np.concatenate(self._frames)
        self._in_speech = False
        self._frames = []
        self._voiced = self._silent = 0
        self._on_turn(audio)

    # -- the five stages ---------------------------------------------------
    def _on_turn(self, audio: np.ndarray) -> None:
        t_end = time.perf_counter()
        self._emit("latency", "Speech detected",
                   (time.time() - self._started) * 1000)
        self._emit("latency", "End-of-turn", float(SILENCE_HANGOVER_MS))
        self._emit("state", "transcribing")

        self._preview_decoded = 0
        heard = self.node_stt.transcribe(audio)
        if not heard:
            self._emit("state", "listening")
            return
        self._emit("live", heard)

        annot = None
        if self.annotator is not None:
            shim = _TurnShim(audio, self._started,
                             int(len(audio) / SAMPLE_RATE * 1000))
            annot = self.annotator.annotate(shim, heard, self._prev_end["t"])
            self._prev_end["t"] = time.time()
            for bad, kind, note in (
                    (is_stock_hallucination(heard, annot.get("wpm")),
                     "environment", "silence artifact — dropped"),
                    (is_echo_garble(heard, annot.get("wpm")),
                     "self", "echo garble — dropped"),
                    (is_own_voice_echo(annot.get("voiceprint"),
                                       self._started),
                     "self", "own voice — dropped")):
                if bad:
                    self._emit(kind, heard)
                    self._emit("state", note)
                    self._emit("live", "")
                    return

        # The ordered fingerprint stack above is authoritative. Keep the
        # playground's text-similarity check as a final backstop for plain
        # mode and replay/shared-device callers.
        if self._is_self_echo(heard):
            self._emit("self", heard)
            self._emit("state", "heard itself — discarded")
            return

        if is_non_speech(heard):            # stage 2: environment
            self._emit("environment", heard)
            self._emit("state", "environment — ignored")
            self._emit("live", "")
            return

        in_window = turn_started_in_followup(self._started,
                                               self._followup_deadline)
        hit = _match_wake(heard)            # stage 4: addressed to us?
        if hit is None and not in_window:
            self._emit("overheard", heard)
            self._emit("state", "overheard — not addressed")
            self._emit("live", "")
            return

        if (annot is not None and hit is None and in_window
                and annot.get("holding")):
            self._hold["text"] = (self._hold["text"] + " " + heard).strip()
            self._hold["deadline"] = time.time() + HOLD_MAX_S
            self._hold["turns"].append(annot)
            self._emit("state", "HOLDING — you seem mid-thought")
            self._emit("live", self._hold["text"])
            return

        command = hit[1] if hit is not None else heard
        if hit is not None:
            self._turns = 0
            self._emit("session", "Wake", f"\u2713 heard {hit[0]!r}")
            if annot is not None:
                annot["wake"] = hit[0]
        self._followup_deadline = 0.0
        if not command:                       # wake phrase and nothing else
            self._emit("live", "")
            self._emit("status", f"{hit[0]} — listening…")
            self._followup_deadline = time.time() + followup_window(turns=1)
            return

        turns = self._hold["turns"] + ([annot] if annot else [])
        if self._hold["text"]:
            command = (self._hold["text"] + " " + command).strip()
            self._hold = {"text": "", "deadline": 0.0, "turns": []}
        self._emit("user", committed_user_text(heard, command))
        self._emit("live", "")
        if closes_conversation(command):    # conversation is a state
            self._dismiss()
            return
        self._respond(command, t_end, turns=turns)

    def _respond(
        self,
        command: str,
        t_end: float | None = None,
        turns: list | None = None,
        *,
        input_modality: str = "speech",
    ) -> None:
        t_end = time.perf_counter() if t_end is None else t_end
        with self._respond_lock:
            self._respond_locked(command, t_end, turns, input_modality=input_modality)

    def _respond_locked(
        self,
        command: str,
        t_end: float,
        turns: list | None,
        *,
        input_modality: str = "speech",
    ) -> None:
        self._force_listen_evt.clear()
        with self._mode_lock:
            enabled, self._pending_agentic_mode = self._pending_agentic_mode, None
        if enabled is not None:
            runtime = getattr(self.node_llm, "runtime", None)
            runtime.agentic_tools = enabled
            self.config = self.config.model_copy(
                update={"output_mode": "dynamic" if enabled else "speech"}
            )
        self._emit("state", "thinking")
        image, self._pending_image = self._pending_image, None
        user_text = command
        if self.audio_mode != "plain" and turns and ctx.STRUCTURED_CONTEXT:
            user_text = llm_user_text(command, turns, "turn")
        if self.config.output_mode == "dynamic":
            modality = "text" if input_modality == "text" else "speech"
            user_text = f"[input: {modality}]\n{user_text}"
        # the exact payload the agent receives — context line and all — so
        # the GUI can show what was SUBMITTED, not just what was heard
        self._emit("submitted",
                   user_text + ("  [+image]" if image is not None else ""))
        with multimodal_output_scope():
            reply = self._answer(user_text, image)
        if self._force_listen_evt.is_set():
            self._emit("state", "listening")
            return
        decision = decide_output(
            mode=self.config.output_mode,
            input_modality="text" if input_modality == "text" else "speech",
            reply=reply,
        )
        self._remember(command, reply)
        self._emit("latency", "Reply ready", (time.perf_counter() - t_end) * 1000)
        self._emit(
            "session",
            "Output",
            "+".join(decision.channels).upper() if decision.channels else "SILENT",
        )
        self._emit(
            "assistant",
            decision.display_text,
            {
                "display": bool(decision.display_text),
                "channels": decision.channels,
                "source": decision.source,
            },
        )
        if decision.speech_text:
            self._emit("state", "speaking")
            self._speak(decision.speech_text)
            self._emit("latency", "Spoken", (time.perf_counter() - t_end) * 1000)
        else:
            self._emit("latency", "Spoken", None)
        self._emit("state", "listening")
        self._turns += 1
        visible_reply = decision.display_text or decision.speech_text or reply
        win = followup_window(turns=self._turns,
                              agent_asked=agent_asked_question(visible_reply))
        self._followup_deadline = time.time() + win
        self._emit("session", "Mode",
                   f"FOLLOW-UP \u2014 {win:.0f}s, no wake phrase needed")

    def _system_prompt(self) -> str:
        system = SYSTEM_PROMPT + (
            CONTEXT_PROMPT_ADDON
            if ctx.STRUCTURED_CONTEXT and self.audio_mode != "plain" else "")
        if self.extra_prompt:
            system = f"{system}\n{self.extra_prompt}"
        if self.config.output_mode == "dynamic":
            system = f"{system}{DYNAMIC_OUTPUT_PROMPT}"
        return system

    def _answer(self, user_text: str, image) -> str:
        system = self._system_prompt()
        content = self.node_vision.content(user_text, image)
        return self.node_llm.answer(content, system)

    def _remember(self, user_text: str, reply: str) -> None:
        """Fallback history only; the AgentRuntime implementation is a no-op."""
        self.node_llm.remember(user_text, reply)

    @property
    def _history(self) -> list:
        return self.node_llm.history

    def _tick_hold(self) -> None:
        """An abandoned held thought eventually gets its answer (HOLD_MAX_S)."""
        if self._hold["text"] and time.time() >= self._hold["deadline"]:
            text, turns = self._hold["text"], self._hold["turns"]
            self._hold = {"text": "", "deadline": 0.0, "turns": []}
            self._emit("user", text)
            self._emit("live", "")
            self._respond(text, turns=turns)

    def _dismiss(self) -> None:
        """Speak goodbye, then clear state and re-arm the wake gate."""
        if self._closing:
            return
        self._closing = True
        try:
            self._emit("assistant", "Goodbye.")
            self._emit("state", "speaking")
            self._speak("Goodbye.")
            self.node_llm.clear()
            self._turns = 0
            self._followup_deadline = 0.0
            self._hold = {"text": "", "deadline": 0.0, "turns": []}
            if self._agg is not None:
                self._agg.clear()
            if self._seng is not None:
                self._seng.reset()
            self._emit("session", "Mode", "WAKE \u2014 say the wake phrase")
            self._emit("session", "Wake", "\u2014")
            self._emit("state", "listening")
        finally:
            self._closing = False

    def set_paused(self, paused: bool) -> None:
        """Pause or resume input without moving turn policy into a caller."""
        if paused:
            self._paused.set()
            self._in_speech = False
            self._frames = []
            self._residue = np.zeros(0, dtype=np.float32)
            self.drain_input()
            if self._agg is not None:
                self._agg.clear()
        else:
            self.drain_input()
            self._paused.clear()
        self._emit("state", "paused" if paused else "listening")

    def set_barge_mode(self, mode: str) -> None:
        """Set the audio node's per-session floor policy."""
        if mode not in {"stop", "continue"}:
            raise ValueError("barge mode must be 'stop' or 'continue'")
        dxr.BARGE_MODE = mode
        self._emit("session", "Barge", mode)

    def set_agentic_tools(self, enabled: bool) -> None:
        """Apply a mode change atomically at the next turn, not mid-answer."""
        runtime = getattr(self.node_llm, "runtime", None)
        if runtime is None or not hasattr(runtime, "agentic_tools"):
            raise RuntimeError("runtime does not support live agentic/chatbot switching")
        with self._mode_lock:
            self._pending_agentic_mode = bool(enabled)

    def force_listen(self) -> None:
        """Cut current playback/generation and return the floor to input."""
        self._force_listen_evt.set()
        runtime = getattr(self.node_llm, "runtime", None)
        interrupt = getattr(runtime, "interrupt", None)
        if callable(interrupt):
            try:
                interrupt(session_key=self.node_llm.session_key)
            except OSError as exc:
                self._emit("status", f"Agent connection lost during interruption: {exc}")
        if self._io is not None:
            self._io.interrupt_playback()
        elif self.play:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
        self._emit("state", "listening")

    # -- duplex audio pipeline (quasi/full): engine-owned AEC device ------------------
    def _ear_loop_quasi(self) -> None:
        while not self._ear_stop.is_set():
            self._tick_hold()
            try:
                fr = self._io.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._paused.is_set():
                continue
            if self.speaking.is_set():
                continue                    # the speak watcher owns these
            f1 = fr.reshape(-1)
            self._emit("mic", data=f1)
            self._residue = np.concatenate([self._residue, f1])
            while self._residue.size >= self.FRAME:
                piece, self._residue = (self._residue[:self.FRAME],
                                        self._residue[self.FRAME:])
                self._push_frame(piece)

    def _ear_loop_full(self) -> None:
        eng, gov, anchor = self._seng, self._sgov, self._sanchor
        st = {"agg_at": 0.0, "considered": True}
        while not self._ear_stop.is_set():
            try:
                fr = self._io.q.get(timeout=0.2)
                f1 = fr.reshape(-1)
                self._emit("mic", data=f1)
                eng.feed(f1)
                gov.observe(f1)
            except queue.Empty:
                pass
            if self._paused.is_set():
                continue
            if self.speaking.is_set():
                continue
            now = time.monotonic()
            try:
                buf_s = float(eng.buffer_seconds)
            except TypeError:
                buf_s = float(eng.buffer_seconds())
            act = gov.action(now, eng.undecoded_seconds,
                             bool(eng.display_text()), buffer_s=buf_s)
            drift = False
            if act == "wait" and anchor.should_flush(eng, now):
                act, drift = "flush", True
            commits: list = []
            if act == "flush":
                commits = eng.flush()
                eng.reset_audio()
                anchor.reset()
            elif act != "wait":
                commits = eng.decode_pass()
            if act != "wait":
                gov.note_commits(len(commits), now)
                if not commits:
                    self._label_q.clear()
            quiet = (act == "wait" and self._agg.turns()
                     and not st["considered"]
                     and now - st["agg_at"] >= 1.5)
            if commits:
                st["agg_at"], st["considered"] = now, False
            for s_ in commits:
                label = (self._label_q.pop(0) if self._label_q
                         else (self._sann.last or {}))
                if (label.get("energy_db", 0.0) < -30.0
                        and is_stock_hallucination(s_, 0)):
                    continue
                fp = label.get("_fp")
                if fp is not None and is_own_voice_echo(
                        [float(x) for x in fp], time.time()):
                    continue
                self._agg.push(sentence_turn(s_, label))
                self._emit("live", self._agg.text())
            boundary = None
            wake = self._agg.wake() if commits else None
            if wake is not None:
                boundary = "addressed command"
            elif ((act == "flush" and not drift) or quiet)                     and self._agg.turns():
                boundary = "long pause"
                if quiet:
                    st["considered"] = True
            if boundary is None:
                continue
            in_window = time.time() < self._followup_deadline
            if boundary == "addressed command":
                if not in_window and len(self._agg.items) > 1:
                    self._agg.items = self._agg.items[-1:]
            elif not in_window:
                self._agg.clear()
                continue
            elif not self._agg.items[-1].get("complete"):
                continue
            utt = self._agg.text()
            turns = list(self._agg.turns())
            if wake is not None and turns:
                turns[-1]["wake"] = wake[0]
            self._agg.clear()
            self._emit("live", "")
            self._emit("user", utt)
            if closes_conversation(utt):
                self._dismiss()
                continue
            self._respond(utt, turns=turns)

    def _speak_duplex(self, text: str) -> None:
        """03/04's continuous-watch speak on the engine-owned device: mic
        LIVE throughout, barge per dxr.BARGE_MODE, self-voice fingerprinted."""
        if self._force_listen_evt.is_set():
            return
        self._last_spoken = text
        self._last_spoken_at = time.time()
        self.speaking.set()
        io = self._io
        io.clear_barge()
        monitor = BargeMonitor()
        played: list[np.ndarray] = []
        state = {"barged": False, "stop": False}

        def _watch() -> None:
            while not state["stop"]:
                try:
                    fr = io.q.get(timeout=0.05)
                except queue.Empty:
                    continue
                if (
                    not self._closing
                    and not self._paused.is_set()
                    and self.audio_mode == "full"
                    and self._seng is not None
                ):
                    f1 = fr.reshape(-1)
                    self._seng.feed(f1)
                    self._sgov.observe(f1)
                if (not self._closing and not self._paused.is_set()
                        and dxr.BARGE_MODE == "stop"
                        and not state["barged"]
                        and monitor.feed(fr)):
                    io.interrupt_playback()
                    state["barged"] = True

        w = threading.Thread(target=_watch, daemon=True)
        w.start()
        try:
            for chunk24 in self.node_tts.synth(text):
                if state["barged"] or self._force_listen_evt.is_set():
                    break
                played.append(chunk24)
                self._emit("audio", text, chunk24)
                if self.play:
                    io.play_chunk(chunk24)
            while (self.play and io.is_playing() and not state["barged"]
                   and not self._force_listen_evt.is_set()):
                time.sleep(0.02)
            time.sleep(0.1)
        finally:
            state["stop"] = True
            w.join(timeout=0.5)
            if played:
                try:
                    from scipy.signal import resample_poly
                except ImportError as exc:
                    raise RuntimeError(
                        "scipy is required for duplex self-voice rejection; "
                        "install jaeger-agent"
                    ) from exc
                a16 = resample_poly(np.concatenate(played), up=2, down=3)
                _SELF_VOICE["fp"] = TurnAnnotator.fingerprint(
                    a16.astype(np.float32))
                _SELF_VOICE["until"] = time.time() + SELF_ECHO_WINDOW_S
            self.speaking.clear()
            self._last_spoken_at = time.time()

    # -- output 2: audio ---------------------------------------------------
    def _speak(self, text: str) -> None:
        """Faithful port of the shipped companion's speak() — the solved setup.

        Everything here exists because its absence was once a live bug:

        * capture closes for SYNTHESIS as well as playback (`paused_capture`
          wrapped the whole generator) — the flag goes up before Kokoro runs;
        * the input queue is DRAINED on entry and again on exit, so audio that
          leaked in around the closure is discarded, not transcribed later —
          the backlog behind the self-conversation loop;
        * chunk N plays while chunk N+1 is still generating, which is the
          difference between speech that starts in ~1s and a mute app that is
          "synthesising";
        * 120 ms after the last sample, because the room keeps saying it after
          the speaker stops.
        """
        if not text or self._force_listen_evt.is_set():
            return
        if self._io is not None:
            return self._speak_duplex(text)
        self._last_spoken = text
        self._last_spoken_at = time.time()
        self.speaking.set()
        self.drain_input()
        started = False
        try:
            if self.play:
                try:
                    import sounddevice as sd
                except ImportError as exc:
                    raise RuntimeError(
                        "sounddevice is required for playback; "
                        "install jaeger-agent"
                    ) from exc
            for chunk in self.node_tts.synth(text):
                if self._force_listen_evt.is_set():
                    break
                self._emit("audio", text, chunk)
                if self.play:
                    if started:
                        sd.wait()          # chunk N finishes while N+1 was made
                    sd.play(chunk, TTS_RATE)
                    started = True
            if started and self.play:
                sd.wait()
                time.sleep(0.12)           # let the speaker and the room drain
        finally:
            self._in_speech = False
            self._frames = []
            self._residue = np.zeros(0, dtype=np.float32)
            self.drain_input()
            self.speaking.clear()
            self._last_spoken_at = time.time()

    def close(self) -> None:
        """Stop owned workers/devices and close the injected runtime."""
        self._ear_stop.set()
        self._preview_stop.set()
        if self._ear_thread is not None:
            self._ear_thread.join(timeout=1.0)
        if self._preview_thread is not None:
            self._preview_thread.join(timeout=1.0)
        if self._io is not None:
            self._io.__exit__(None, None, None)
            self._io = None
        # The mmproj MTMD context is a native child of the llama model and
        # must be released first.  llama-cpp-python's handler has no public
        # close method, so the vision node owns this lifecycle boundary.
        close_vision = getattr(self.node_vision, "close", None)
        if callable(close_vision):
            close_vision()
        close = getattr(self.node_llm, "close", None)
        if callable(close):
            close()

    def _is_self_echo(self, heard: str) -> bool:
        """Ours or theirs? Half duplex should never need this — but a file
        replay, a shared output device, or a future full-duplex caller can all
        deliver our own voice back, and answering yourself does not stop."""
        if not self._last_spoken or not heard.strip():
            return False
        if (time.time() - self._last_spoken_at > self.SELF_ECHO_GRACE_S
                and not self.speaking.is_set()):
            return False

        def norm(t: str) -> str:
            return " ".join("".join(c for c in t.lower()
                                    if c.isalnum() or c.isspace()).split())

        a, b = norm(heard), norm(self._last_spoken)
        if not a:
            return False
        return a in b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.65

MultimodalAgent = GemmaMultimodal

__all__ = ["AgentRuntimeBrain", "GemmaMultimodal", "MultimodalAgent", "Event"]
