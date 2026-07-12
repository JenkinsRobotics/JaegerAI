#!/usr/bin/env python3
"""Voice loop — STT → agent → TTS daemon.

The agent brain is transport-agnostic: a spoken turn is just text in /
text out (STT → agent → TTS), identical to a typed turn. Ambient-speech
filtering for the always-on mic lives HERE in the input layer — never in
the brain prompt (the LLM <reply>/<ignore> gate was removed 2026-06-16
because it shared the model with tool-calling and suppressed it).

  Wake word (recommended for always-on rooms)
      Deterministic Whisper wake-phrase match gates which utterances
      become a turn. Without it, every VAD-segmented utterance is
      treated as addressed to the agent.

      Override with ``--wake-word`` or ``--no-wake-word``.

  Mic-pause during TTS by default
      Stable first-run behavior: the mic pauses while the agent speaks
      unless the operator explicitly enables AEC barge-in.

      Override with ``--barge-in`` or ``--no-barge-in``.

STT modes:

  --stt-mode two_pass    (default)
      VAD-segmented STT with fast → accurate Whisper cascade
      (base.en for wake matching, medium.en for the committed
      command). Robust against background noise, slightly higher
      latency on commit.

  --stt-mode continuous
      Energy-segmented STT with rolling re-transcription. Lower
      commit latency, lighter memory footprint, less robust to
      background noise.

Run:

    python -m jaeger_os.plugins.voice_loop
    python -m jaeger_os.plugins.voice_loop --instance work
    python -m jaeger_os.plugins.voice_loop --wake-word
    python -m jaeger_os.plugins.voice_loop --barge-in
    python -m jaeger_os.plugins.voice_loop --no-wake-word
    python -m jaeger_os.plugins.voice_loop --no-barge-in

Or, when ``config.interaction.default_mode`` is set to ``voice``
(via the wizard's Step 4), a bare ``./run.sh --instance NAME``
dispatches here automatically — no flags needed.

This file is NOT a plugin — it's the daemon orchestrator wiring the
kokoro_tts and whisper_stt plugins to the agent. Same role as
plugins/messaging_gateway.py.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid
from typing import Any

from ..main import (
    LlamaCppPythonClient,
    init_extensions,
    prewarm,
    run_for_voice,
    shutdown_extensions,
)
from ..agent import tools as agent_tools
from jaeger_ai.agent.background.cron_runner import CronRunner
from jaeger_ai.core.instance.instance import InstanceLayout, default_instance_name, resolve_instance_dir
from jaeger_ai.core.instance.schemas import Config, load_yaml
from jaeger_ai.agent.prompts.prompts import build_system_prompt


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--stt-mode", choices=["two_pass", "continuous"], default="two_pass",
                   help="Which STT algorithm to use.")
    p.add_argument(
        "--wake-word", dest="wake_word", action="store_true",
        help="Gate utterances behind a wake phrase. Overrides the "
             "instance voice.wake_word setting."
    )
    p.add_argument(
        "--no-wake-word", dest="no_wake_word", action="store_true",
        help="Don't gate utterances behind a wake phrase — every spoken "
             "phrase reaches the LLM gate. Overrides the instance setting."
    )
    p.add_argument(
        "--barge-in", dest="barge_in", action="store_true",
        help="Keep the mic open during TTS and use AEC so the operator "
             "can interrupt mid-speech. Overrides the instance setting."
    )
    p.add_argument(
        "--no-barge-in", dest="no_barge_in", action="store_true",
        help="Pause the mic during TTS instead of running AEC echo "
             "cancellation. Overrides the instance setting."
    )
    p.add_argument("--fast-model", type=str, default="base.en",
                   help="Whisper fast/continuous model name (default: base.en).")
    p.add_argument("--accurate-model", type=str, default="medium.en",
                   help="Whisper accurate model name (two_pass only, default: medium.en).")
    p.add_argument("--no-cron", action="store_true",
                   help="Don't start the cron runner alongside the voice loop.")
    p.add_argument("--no-chimes", action="store_true",
                   help="Disable wake / follow-up audio earcons.")
    # NOTE — the --attach flag (which routed turns through the
    # daemon's chat.send verb to skip an in-process LLM load) was
    # removed 2026-06-14 with the daemon-arch decision (J5C). The
    # voice loop now always runs standalone: it loads its own model
    # and owns its own turn lifecycle. If memory matters, run only
    # one of {voice, messaging, the TUI} at a time.
    # 0.3.0: which audio I/O backend to use for mic capture (Whisper
    # STT) and TTS playback (Kokoro).
    #
    #   avaudio    (default on macOS)
    #       PyObjC AVAudioEngine — Apple-native audio I/O.  Retires
    #       the wedging-CoreAudio bug class entirely.  Voice
    #       processing mode (built-in AEC + NS + AGC) is available
    #       via voice_processing=True in the input stream.
    #
    #   portaudio  (default on non-Darwin, escape hatch on macOS)
    #       Classic sounddevice + PortAudio path — the 0.2.x
    #       behaviour, unchanged.  Kept as a fallback while operators
    #       validate avaudio on diverse hardware; 0.4.0 removes it
    #       on macOS.
    p.add_argument(
        "--audio-backend", choices=["portaudio", "avaudio"],
        default="avaudio" if sys.platform == "darwin" else "portaudio",
        help="Audio I/O backend. 'avaudio' = PyObjC AVAudioEngine, "
             "Apple-native (default on macOS — retires the wedging-"
             "CoreAudio bug class). 'portaudio' = classic sounddevice "
             "(default off-macOS, available as fallback)."
    )
    args = p.parse_args()

    os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")

    # ── Instance + agent setup (mirrors messaging_gateway) ───────────
    instance_name = args.instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(instance_name))
    if not layout.exists():
        print(f"[voice] instance {instance_name!r} not initialized; "
              f"run `./run.sh setup {instance_name}` first.", file=sys.stderr)
        return 2

    config: Config = load_yaml(layout.config_path, Config)
    agent_tools.bind(layout)

    if args.wake_word and args.no_wake_word:
        print("[voice] choose only one of --wake-word / --no-wake-word",
              file=sys.stderr)
        return 2
    if args.barge_in and args.no_barge_in:
        print("[voice] choose only one of --barge-in / --no-barge-in",
              file=sys.stderr)
        return 2

    require_wake_word = bool(config.voice.wake_word)
    if args.wake_word:
        require_wake_word = True
    elif args.no_wake_word:
        require_wake_word = False

    barge_in_requested = bool(config.voice.barge_in)
    if args.barge_in:
        barge_in_requested = True
    elif args.no_barge_in:
        barge_in_requested = False
    barge_in_active = False  # resolved below after we know AEC state

    # Self-speech filter (default ON): drop transcripts too similar
    # to the agent's last reply (mic picked up our own voice).
    self_speech_filter_active = bool(config.voice.self_speech_filter)
    self_speech_threshold = float(config.voice.self_speech_threshold)
    # Drop phrases that sat in the queue too long (queue hygiene).
    pending_turn_max_age_s = 3.0
    # Track the agent's last spoken reply for the self-speech filter.
    _last_reply_text: str = ""

    from ..main import _pipeline
    _pipeline["layout"] = layout
    _pipeline["config"] = config
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = config.display.show_latency
    _pipeline["show_tool_activity"] = config.display.show_tool_activity

    # ── LLM bring-up — local model, always ──────────────────────────
    #
    # Standalone mode: load Gemma into this process, run
    # init_extensions / prewarm, and each turn calls
    # ``run_for_voice(client, phrase)``. (The daemon-attach path was
    # removed 2026-06-14 with the daemon-arch decision — see comment
    # next to the argparse block above.)
    print(f"[voice] loading Gemma in-process ({layout.root.name})...",
          flush=True)
    started = time.perf_counter()
    client = LlamaCppPythonClient(config.model, warmup=True)
    print(f"[voice] loaded in {time.perf_counter() - started:.1f}s",
          flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    prewarm(client)

    def turn_runner(phrase: str) -> dict[str, Any]:
        return run_for_voice(client, phrase, session_key="voice")

    # ── AEC + reference buffer ───────────────────────────────────────
    # 0.2.6: barge-in is request-by-default; we attempt to enable AEC,
    # and only commit to barge-in when AEC is actually available. AEC
    # is the only safe way to barge-in without self-triggering on the
    # agent's own voice — without it we fall back to mic-pause so the
    # operator gets a stable experience instead of a chatty agent that
    # keeps interrupting itself.
    aec = None
    reference_buffer = None
    if barge_in_requested:
        from ..core.audio import AECWrapper, ReferenceBuffer, aec_available
        if aec_available():
            aec = AECWrapper(sample_rate=16000, frame_ms=10, enabled=True)
            reference_buffer = ReferenceBuffer(sample_rate=16000,
                                               capacity_seconds=2.0)
            barge_in_active = True
            print(f"[voice] AEC barge-in enabled ({aec.backend}) — "
                  f"interrupt the agent any time", flush=True)
        else:
            barge_in_active = False
            print("[voice] speexdsp not installed (pip install speexdsp) — "
                  "falling back to mic-pause during TTS. You won't be able "
                  "to interrupt the agent mid-speech.", flush=True)
    else:
        print("[voice] --no-barge-in: mic-pause during TTS", flush=True)

    # ── Chimes (wake + follow-up earcons) ────────────────────────────
    from ..core.audio import ChimePlayer
    chimes = ChimePlayer(
        enabled=not args.no_chimes,
        # Push chime audio into the AEC reference buffer when barge-in is on,
        # so the mic doesn't hear the chime as user speech.
        reference_buffer=reference_buffer,
    )

    # ── Warm TTS (and wire the reference buffer if barge-in is on) ───
    from ..agent.tools.speak import _get_tts
    tts = _get_tts()
    if reference_buffer is not None:
        tts.reference_buffer = reference_buffer
    # 0.3.0: tell the TTS pipeline which audio backend BEFORE warm() —
    # warm() opens the PersistentKokoroPlayer against ``audio_backend``,
    # so setting it later would open the persistent stream against the
    # default (avaudio on macOS) and ignore an operator's
    # ``--audio-backend portaudio`` until the first speak() forced a
    # close+reopen.  Set it here so the player opens against the
    # requested backend on the very first call.
    if hasattr(tts, "audio_backend"):
        tts.audio_backend = args.audio_backend
        print(f"[voice] audio backend = {args.audio_backend}", flush=True)
    print("[voice] warming Kokoro TTS...", flush=True)
    warm_result = tts.warm()
    if warm_result.get("warmed"):
        print(f"[voice] Kokoro ready ({warm_result.get('seconds')}s)", flush=True)
    else:
        print(f"[voice] Kokoro warm failed: {warm_result.get('reason')} "
              f"— continuing; first speak() will pay the cost", flush=True)

    # ── Build STT in the requested mode ──────────────────────────────
    # 0.2.6: followup_window_s=10.0 to match the reference
    # voice_assistant.py canonical UX. Previously the STT default
    # (15s) gave a generous "keep talking" window; 10s feels snappier
    # and matches Google-Home muscle memory.
    # 0.3.0: thread the audio backend choice down to the mic.  Both
    # STT classes accept ``audio_backend`` which they pass through
    # to ``_MicStream`` — when 'avaudio' the mic comes up via
    # AVAudioEngine (PyObjC), otherwise it comes up via sounddevice
    # exactly as in 0.2.x.
    if args.stt_mode == "continuous":
        from .whisper_stt import WhisperSTTContinuous
        stt = WhisperSTTContinuous(
            model_name=args.fast_model,
            require_wake_word=require_wake_word,
            followup_window_s=10.0,
            aec=aec, far_end_buffer=reference_buffer,
            audio_backend=args.audio_backend,
        )
    else:
        from .whisper_stt import WhisperSTTTwoPass
        stt = WhisperSTTTwoPass(
            fast_model_name=args.fast_model,
            accurate_model_name=args.accurate_model,
            require_wake_word=require_wake_word,
            followup_window_s=10.0,
            aec=aec, far_end_buffer=reference_buffer,
            audio_backend=args.audio_backend,
        )

    # 0.4 Track B.3.2.a — STT phrase consumption migrates to the bus.
    # The AudioSessionNode wraps the existing Whisper engine and
    # publishes committed phrases on /sense/transcript.  voice_loop
    # subscribes here + drains via _phrase_queue instead of calling
    # stt.next_phrase() directly.  Engine control methods (set_paused,
    # open_followup, set_on_speech_detected, drain_pending,
    # require_wake_word, in_speech) still go through ``stt`` for now
    # — they're voice-loop-internal coordination and would need
    # /control/* topics that aren't designed yet.  Track B.3.2.b
    # handles those when the TTS path migrates.
    import queue as _queue
    from jaeger_os.transport import topics as _topics
    from jaeger_os.core.voice import clean_voice_reply, is_non_speech_marker
    from jaeger_os.core.audio import AudioSession as _AudioSession
    from jaeger_os.nodes import AudioSessionNode as _AudioSessionNode
    from jaeger_os.nodes import runtime as _runtime
    _bus = _runtime.get_bus()
    _audio_session = _AudioSession(
        adapter=stt,
        aec=aec,
        reference_buffer=reference_buffer,
        barge_in_live=barge_in_active,
        self_speech_filter=self_speech_filter_active,
        self_speech_threshold=self_speech_threshold,
    )
    _phrase_queue: "_queue.Queue[tuple[str, float]]" = _queue.Queue(maxsize=4)
    _gate_log_path = layout.logs_dir / "voice_gate_eval.jsonl"

    def _log_gate_event(
        event: str,
        phrase: str,
        *,
        decision: str,
        reply: str = "",
        age_s: float | None = None,
        reason: str = "",
    ) -> None:
        """Best-effort VoiceLLM-style gate/eval trace."""
        try:
            layout.logs_dir.mkdir(parents=True, exist_ok=True)
            rec: dict[str, Any] = {
                "ts": time.time(),
                "event": event,
                "decision": decision,
                "phrase": phrase,
            }
            if reply:
                rec["reply"] = reply
            if age_s is not None:
                rec["age_s"] = round(age_s, 3)
            if reason:
                rec["reason"] = reason
            with _gate_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def _on_transcript(msg: _topics.Transcript) -> None:
        text = (msg.text or "").strip()
        if is_non_speech_marker(text):
            print(f"[voice] skipped non-speech transcript: {text!r}",
                  flush=True)
            _log_gate_event(
                "transcript",
                text,
                decision="ignore",
                reason="non_speech_marker",
            )
            return
        if _phrase_queue.full():
            try:
                dropped, _dropped_at, _dropped_timing = _phrase_queue.get_nowait()
                print(f"[voice] dropped stale queued phrase: {dropped!r}",
                      flush=True)
                _log_gate_event(
                    "queue",
                    dropped,
                    decision="drop",
                    age_s=time.time() - _dropped_at,
                    reason="queue_full",
                )
            except _queue.Empty:
                pass
        _phrase_queue.put_nowait((text, time.time(), {
            "speech_end": float(getattr(msg, "speech_end_pc", 0.0) or 0.0),
            "stt_done": float(getattr(msg, "stt_done_pc", 0.0) or 0.0),
        }))
        _log_gate_event("transcript", text, decision="queued")

    _bus.subscribe(_topics.SENSE_TRANSCRIPT, _on_transcript)
    _stt_node = _AudioSessionNode(
        bus=_bus,
        session=_audio_session,
        name="audio_session",
        install_signal_handlers=False,
    )
    _stt_thread = threading.Thread(
        target=_stt_node.run, name="voice-stt-node", daemon=True,
    )
    _stt_thread.start()
    # The STT node's setup() calls stt.start() (opens the mic +
    # spawns the Whisper background loop).  Give it a moment so the
    # subscription is live + the mic is hot before we enter the
    # phrase-pull loop.
    time.sleep(0.2)

    # ── Cron runner (optional) ───────────────────────────────────────
    llm_lock = threading.Lock()
    _pipeline["llm_lock"] = llm_lock
    cron_runner: CronRunner | None = None
    if not args.no_cron:
        def _cron_callback(prompt: str, session_key: str | None = None) -> None:
            run_for_voice(client, prompt, session_key=session_key)
        cron_runner = CronRunner(_cron_callback, llm_lock=llm_lock)
        cron_runner.start()
        print("[voice] cron runner started", flush=True)

    mode_msg = f"mode={args.stt_mode}"
    if require_wake_word:
        mode_msg += (
            ", wake-word required (say 'ok jaeger' / 'hey jaeger' / "
            "'okay jaeger'; phonetic variants yeager/yager/jager also "
            "trigger)"
        )
    else:
        mode_msg += ", wake-word disabled (every phrase becomes a command)"
    mode_msg += (
        ", AEC barge-in on" if barge_in_active else ", mic-pause during TTS"
    )
    print(f"[voice] ready. {mode_msg}. Ctrl-C to quit.", flush=True)

    # ── Shutdown handling ────────────────────────────────────────────
    stop = threading.Event()

    def _shutdown(*_: Any) -> None:
        print("\n[voice] shutdown signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Main loop ────────────────────────────────────────────────────
    try:
        while not stop.is_set():
            # 0.4 Track B.3.2.a: phrases come from the bus subscription
            # via _phrase_queue instead of polling stt.next_phrase().
            # Same blocking semantics — wait up to 1.0 s for a phrase.
            try:
                phrase, phrase_queued_at, phrase_timing = _phrase_queue.get(
                    timeout=1.0,
                )
            except _queue.Empty:
                phrase = None
                phrase_timing = {}
            if not phrase:
                continue
            phrase_age_s = time.time() - phrase_queued_at
            if phrase_age_s > pending_turn_max_age_s:
                print(f"[voice] dropped stale phrase after "
                      f"{phrase_age_s:.1f}s: {phrase!r}", flush=True)
                _log_gate_event(
                    "queue",
                    phrase,
                    decision="drop",
                    age_s=phrase_age_s,
                    reason="max_age",
                )
                continue

            # ── Self-speech filter (VoiceLLM M3 pattern) ─────────────
            # When ON, drop phrases too similar to the agent's last
            # spoken reply.  Belt-and-suspenders on top of mic-pause
            # for cases where speaker bleed leaks through.
            if self_speech_filter_active and _last_reply_text:
                import difflib as _difflib
                _ratio = _difflib.SequenceMatcher(
                    None, phrase.lower(), _last_reply_text.lower(),
                ).ratio()
                if _ratio >= self_speech_threshold:
                    print(f"[voice] self-speech filter dropped "
                          f"(sim={_ratio:.2f}): {phrase!r}", flush=True)
                    _log_gate_event(
                        "pre_gate",
                        phrase,
                        decision="ignore",
                        reason=f"self_speech:{_ratio:.2f}",
                    )
                    continue

            print(f"[voice] user: {phrase!r}", flush=True)

            # Wake chime — brief tone tells the user "heard you, processing".
            # Pause mic during chime so it doesn't get picked up as a phrase
            # (skipped when AEC is on; the reference buffer handles it).
            if chimes.enabled("wake"):
                if reference_buffer is None:
                    stt.set_paused(True)
                chimes.play("wake")
                if reference_buffer is None:
                    stt.set_paused(False)

            # In non-barge-in mode, keep the mic paused continuously
            # from agent decode through bus-routed TTS playback. With
            # barge-in, the mic stays open so the AEC + sustained-voice
            # callback can detect interruption mid-TTS.
            if not barge_in_active:
                stt.set_paused(True)

            try:
                # turn_runner = run_for_voice (local LLM).
                result = turn_runner(phrase)
                text = clean_voice_reply(result.get("text") or "")
                spoke_via_tool = result.get("spoke_via_tool", False)
                if is_non_speech_marker(text):
                    print(f"[voice] model returned non-speech marker "
                          f"{text!r} — suppressing TTS", flush=True)
                    _log_gate_event(
                        "model_reply",
                        phrase,
                        decision="ignore",
                        reply=text,
                        reason="non_speech_marker_reply",
                    )
                    stt.open_followup()
                    continue

                # Farewell mirror check (VoiceLLM port): BOTH sides
                # must read as goodbye — user phrase AND reply — so a
                # stray "goodbye" inside a story never closes the loop.
                from jaeger_os.core.voice import is_farewell
                _farewell_close = (
                    bool(text)
                    and is_farewell(phrase)
                    and is_farewell(text)
                )

                if not text or spoke_via_tool:
                    if spoke_via_tool:
                        print("[voice] agent vocalized via tool — skipping "
                              "post-turn speak", flush=True)
                    else:
                        stt.open_followup()
                    # NB: the ``finally`` below will unpause the mic
                    # before we continue around the loop.
                    continue

                # ── Speak the response ───────────────────────────────
                # 0.4 Track B.3.2.b: both sync + barge-in paths now go
                # through the bus.  bus.request(SpeechCommand) blocks
                # until the TTS node publishes /sense/spoken with the
                # matching correlation_id — that returns naturally on
                # completion OR when SpeechStop interrupts the in-
                # flight speak.  Either way, the result is a SpokenAck
                # that mirrors the pre-bus speak_result shape (ok,
                # duration_s, reason).
                # Honest voice latency (VoiceLLM metrics port): the
                # user stopped talking at ``speech_end``; we are about
                # to start talking NOW. This is the number the
                # operator actually feels — everything else is a
                # component of it.
                _speech_end = float(phrase_timing.get("speech_end") or 0.0)
                if _speech_end:
                    _stt_s = max(0.0, float(
                        phrase_timing.get("stt_done") or _speech_end,
                    ) - _speech_end)
                    _agent_s = float(result.get("elapsed_s") or 0.0)
                    _e2e_s = max(0.0, time.perf_counter() - _speech_end)
                    print(f"[voice-latency] stt={_stt_s:.2f}s "
                          f"agent={_agent_s:.2f}s "
                          f"speech-end→speak={_e2e_s:.2f}s", flush=True)
                    _log_gate_event(
                        "latency", phrase, decision="ok",
                        reason=(f"stt={_stt_s:.3f};agent={_agent_s:.3f};"
                                f"e2e={_e2e_s:.3f}"),
                    )

                interrupted = {"flag": False}
                _speech_cid = uuid.uuid4().hex

                if barge_in_active:
                    # Install an STT-thread callback that publishes
                    # SpeechStop instead of calling tts.stop() directly.
                    # Same sub-50ms detection — the publish lands on the
                    # bus delivery thread which calls synth.stop() in
                    # the TTS node.
                    def _on_user_speaks() -> None:
                        if not interrupted["flag"]:
                            interrupted["flag"] = True
                            print("[voice] barge-in detected — publishing "
                                  "SpeechStop", flush=True)
                            _bus.publish(_topics.SpeechStop(
                                reason="user interrupted",
                                node_id="voice_loop",
                                correlation_id=_speech_cid,
                            ))

                    stt.set_on_speech_detected(_on_user_speaks)
                    try:
                        ack = _bus.request(
                            _topics.SpeechCommand(
                                text=text,
                                node_id="voice_loop",
                                correlation_id=_speech_cid,
                            ),
                            ack_topic=_topics.SENSE_SPOKEN,
                            timeout_s=180.0,
                        )
                    finally:
                        stt.set_on_speech_detected(None)
                else:
                    # Sync path: TTS runs with mic paused; same bus
                    # round-trip but no barge-in callback registered.
                    ack = _bus.request(
                        _topics.SpeechCommand(
                            text=text,
                            node_id="voice_loop",
                            correlation_id=_speech_cid,
                        ),
                        ack_topic=_topics.SENSE_SPOKEN,
                        timeout_s=180.0,
                    )

                if ack is None or not ack.ok:
                    # Three possible flavours:
                    #  - ack is None: bus.request hit the 180s timeout
                    #  - ack.ok=False, reason="interrupted": barge-in
                    #    cut the speech mid-stream
                    #  - ack.ok=False with a synth-side reason: Kokoro
                    #    produced no audio (empty text, drain timeout,
                    #    …) so the operator heard nothing.
                    # In all cases skip the follow-up chime; the
                    # operator either heard nothing OR is mid-sentence
                    # interrupting and shouldn't be talked over.  The
                    # ``finally`` below unpauses the mic and we go
                    # around.
                    if ack is None:
                        print("[voice] TTS bus timeout — follow-up skipped",
                              flush=True)
                    elif interrupted["flag"]:
                        # barge-in branch already logged
                        pass
                    else:
                        reason = ack.reason or "unknown"
                        print(f"[voice] follow-up skipped — TTS produced "
                              f"no audio ({reason})", flush=True)
                    continue

                # Drop any phrases that VAD finalized during playback —
                # otherwise a stale buffered utterance becomes the next
                # "user input". Critical in barge-in mode where the mic
                # stayed open; cheap in sync mode where it's a no-op.
                #
                # EXCEPT when barge-in fired: the user's interruption
                # phrase is what they want the agent to hear next,
                # NOT a stale buffer.  Draining here would discard the
                # very phrase that triggered the interrupt, and the
                # follow-up chime would talk over them while they're
                # still mid-sentence.  Skip both and let the next
                # ``next_phrase`` pull the operator's interruption
                # naturally — same as the sustained-voice callback
                # promised the operator when it cut TTS.
                barge_in_fired = (
                    barge_in_active
                    and interrupted.get("flag", False)
                )
                if not barge_in_fired:
                    # 0.4 Track B.3.2.a: drain BOTH the engine's
                    # committed-q AND the bus subscription queue.
                    # Otherwise stale phrases buffered during TTS
                    # playback would still come through the bus
                    # subscription after engine.drain_pending()
                    # already cleared them on its side.
                    stt.drain_pending()
                    while not _phrase_queue.empty():
                        try:
                            _phrase_queue.get_nowait()
                        except _queue.Empty:
                            break

                # Follow-up chime — rising two-note tone tells the user
                # "still listening, no wake word needed for the next
                # phrase". Only play when wake gating is on (otherwise
                # there's no semantic difference between in-window and
                # out-of-window). In barge-in mode the mic is open, so
                # only play when AEC will cancel the chime out; in sync
                # mode the mic is still paused under the outer try,
                # which is safer than the prior pause/unpause dance.
                # Skip the chime entirely when barge-in fired — beeping
                # at someone mid-sentence is the opposite of what
                # "still listening" should feel like.
                if (
                    stt.require_wake_word
                    and chimes.enabled("followup")
                    and not barge_in_fired
                    and not _farewell_close
                ):
                    if barge_in_active:
                        if reference_buffer is not None:
                            chimes.play("followup")
                    else:
                        chimes.play("followup")

                # Farewell exchange (VoiceLLM port): when the user said
                # goodbye AND the reply acknowledged it, don't re-open
                # the follow-up window — the robot was soliciting a
                # reply into an empty room, transcribing scissors. STT
                # stays on; the next real utterance resumes normally.
                if _farewell_close:
                    print("[voice] farewell exchange — follow-up window "
                          "suppressed", flush=True)
                    _log_gate_event(
                        "farewell", phrase,
                        decision="suppress_followup", reply=text,
                    )
                else:
                    stt.open_followup()
                if text:
                    _last_reply_text = text
                    _audio_session.remember_reply(text)
            finally:
                if not barge_in_active:
                    stt.set_paused(False)
    finally:
        try:
            _bus.publish(_topics.SpeechStop(
                reason="voice loop shutdown",
                node_id="voice_loop",
            ))
        except Exception:
            pass
        # 0.4 Track B.3.2.a — STT node teardown.  Stopping the node
        # propagates to stt.stop() through AudioSessionNode.teardown(), and
        # joins the Whisper background thread.  Drop the bus
        # subscription too so a re-entrant voice_loop in the same
        # interpreter doesn't accumulate stale subscribers.
        try:
            _bus.unsubscribe(_topics.SENSE_TRANSCRIPT, _on_transcript)
        except Exception:
            pass
        try:
            _stt_node.stop()
            _stt_thread.join(timeout=3.0)
        except Exception:
            pass
        try:
            _runtime.shutdown()
        except Exception:
            pass
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
