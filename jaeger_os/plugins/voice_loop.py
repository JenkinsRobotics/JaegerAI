#!/usr/bin/env python3
"""Voice loop — STT → agent → TTS daemon.

0.2.6 voice UX (two modes, both default-on):

  Wake-word required (default)
      Every utterance ignored until the user says "ok jaeger" / "hey
      jaeger" / "okay jaeger" (with Whisper-mishearing phonetic
      variants: yeager / yager / jager). After a reply, a 10-second
      follow-up window opens — within it, the wake gate drops so the
      user can keep talking without re-prefixing. Same shape as
      Google Home / Siri / Alexa.

      Opt out with ``--no-wake-word``.

  AEC barge-in (default when speexdsp is installed)
      Mic stays open during TTS playback; speexdsp echo cancellation
      removes the agent's own voice from the captured signal so the
      operator can interrupt at any time (sub-50 ms latency). Same
      mechanism as Zoom / FaceTime / Teams.

      Auto-falls-back to mic-pause when speexdsp is missing. Pass
      ``--no-barge-in`` to force mic-pause even when AEC is available.

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
import os
import signal
import sys
import threading
import time
from typing import Any

from ..main import (
    LlamaCppPythonClient,
    init_extensions,
    prewarm,
    run_for_voice,
    shutdown_extensions,
)
from ..core import tools as agent_tools
from jaeger_os.core.background.cron_runner import CronRunner
from jaeger_os.core.instance.instance import InstanceLayout, default_instance_name, resolve_instance_dir
from jaeger_os.core.instance.schemas import Config, load_yaml
from jaeger_os.core.prompts.prompts import build_system_prompt


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--stt-mode", choices=["two_pass", "continuous"], default="two_pass",
                   help="Which STT algorithm to use.")
    # 0.2.6: wake-word required by default. Matches the canonical
    # Google-Home-style UX in the reference voice_assistant.py: every
    # utterance is ignored until the user says "ok jaeger" (or any of
    # the phonetic variants in _ASSISTANT_NAMES). Within the follow-up
    # window after a reply, the gate drops so the user can keep talking
    # without re-saying the wake word.
    p.add_argument(
        "--no-wake-word", dest="no_wake_word", action="store_true",
        help="Don't gate utterances behind a wake phrase — every spoken "
             "phrase becomes a command. Default is wake-word required."
    )
    # 0.2.6: two voice modes, period.
    #
    #   barge-in (default when speexdsp is installed)
    #     mic stays open during TTS, echo cancellation removes the
    #     agent's voice from the captured signal, operator can
    #     interrupt at any time. Same mechanism as Zoom / FaceTime.
    #
    #   --no-barge-in (or auto-fallback when speexdsp is missing)
    #     mic paused for the duration of TTS playback. Safe, no
    #     self-echo possible, but you can't talk over the agent.
    #
    # ``--no-aec`` was a 0.2.0-era A/B-testing knob — it forced the
    # 'barge-in without AEC' middle path which would self-trigger on
    # the agent's own voice. Dropped in 0.2.6 because there is no
    # practical use case for that mode.
    p.add_argument(
        "--no-barge-in", dest="no_barge_in", action="store_true",
        help="Pause the mic during TTS instead of running AEC echo "
             "cancellation. Safe, but you can't interrupt the agent "
             "mid-speech. Default: barge-in enabled when speexdsp is "
             "present, otherwise auto-fallback to this mode."
    )
    p.add_argument("--fast-model", type=str, default="base.en",
                   help="Whisper fast/continuous model name (default: base.en).")
    p.add_argument("--accurate-model", type=str, default="medium.en",
                   help="Whisper accurate model name (two_pass only, default: medium.en).")
    p.add_argument("--no-cron", action="store_true",
                   help="Don't start the cron runner alongside the voice loop.")
    p.add_argument("--no-chimes", action="store_true",
                   help="Disable wake / follow-up audio earcons.")
    # 0.2.6: --attach mode. When the daemon is running for this
    # instance (``./run.sh start``), pass --attach to skip the
    # in-process LLM load and route turns through the daemon's
    # ``chat.send`` verb instead. Saves one full model in RAM at the
    # cost of a socket round-trip per turn. Default OFF so existing
    # standalone behaviour is preserved exactly; the tray's "Open
    # Voice" launcher will pass --attach when it detects a running
    # daemon in a later patch.
    p.add_argument(
        "--attach", action="store_true",
        help="Skip in-process LLM load; route turns through a running "
             "daemon's chat.send verb. Requires the daemon to be up — "
             "the voice loop exits with a clear error otherwise."
    )
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

    # 0.2.6: invert the --no-wake-word flag into the require_wake_word
    # bool the STT layer wants. Default behaviour (no flag passed) is
    # wake-word ON — matches the reference voice_assistant.py UX.
    require_wake_word = not args.no_wake_word

    # 0.2.6: barge-in default. Operator asked for the "video-call"
    # interruption model — AEC keeps the mic open and subtracts TTS
    # from the captured signal. We DEFAULT to it when speexdsp is
    # installed; otherwise we fall back to the safer mic-pause path
    # rather than running barge-in without AEC (which would
    # self-trigger on the agent's own voice). ``--no-barge-in``
    # forces pause mode regardless.
    barge_in_requested = not args.no_barge_in
    barge_in_active = False  # resolved below after we know AEC state

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

    # LLM-gated speech: when enabled, the system prompt picks up the
    # ``VOICE_LLM_GATE_RULE`` block via the JAEGER_VOICE_GATE env var.
    # Has to land BEFORE ``build_system_prompt`` below so the rule is
    # baked into the prompt the agent reads on turn 1.
    voice_gate_active = bool(getattr(config.voice, "llm_gate", False))
    if voice_gate_active:
        os.environ["JAEGER_VOICE_GATE"] = "1"
        print("[voice] LLM-gated speech ON — replies prefixed "
              "<reply>/<ignore>; <ignore> suppresses TTS", flush=True)

    from ..main import _pipeline
    _pipeline["layout"] = layout
    _pipeline["config"] = config
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = config.display.show_latency
    _pipeline["show_tool_activity"] = config.display.show_tool_activity

    # ── LLM bring-up: either local or via daemon attach ──────────────
    #
    # Local (default): same as 0.2.0+. Loads Gemma into this process,
    # runs init_extensions / prewarm, and each turn calls
    # ``run_for_voice(client, phrase)``.
    #
    # --attach: skips the local model entirely. Each turn calls
    # ``Client.call('chat.send', ...)`` against the daemon's socket.
    # Saves ~16 GB RAM when the daemon is also up; round-trips one
    # socket-RPC per turn (~ms, dwarfed by the LLM decode latency).
    daemon_client = None
    client = None  # the local LLM client; populated in non-attach mode
    if args.attach:
        from jaeger_os.daemon.client import Client, DaemonNotRunning
        sock_path = layout.root / "run" / "jaeger.sock"
        if not sock_path.exists():
            print(f"[voice] --attach: daemon socket missing at {sock_path}.",
                  file=sys.stderr)
            print("        Start the daemon first: ./run.sh start"
                  f" --instance {instance_name}", file=sys.stderr)
            return 2
        try:
            daemon_client = Client(socket_path=sock_path, call_timeout=600.0)
            daemon_client.__enter__()
        except DaemonNotRunning as exc:
            print(f"[voice] --attach: cannot connect to daemon — {exc}.",
                  file=sys.stderr)
            print("        Start the daemon first: ./run.sh start"
                  f" --instance {instance_name}", file=sys.stderr)
            return 2
        print(f"[voice] attached to daemon at {sock_path}", flush=True)

        def turn_runner(phrase: str) -> dict[str, Any]:
            """Route the spoken phrase to the daemon's chat.send.
            Adapts the response shape to what the loop expects from
            ``run_for_voice``. ``skipped_final`` from the daemon maps
            to ``spoke_via_tool`` here — same semantic ("agent already
            vocalised via a tool call, skip the post-turn speak")."""
            assert daemon_client is not None
            resp = daemon_client.call(
                "chat.send", text=phrase, session_key="voice",
            )
            data = getattr(resp, "data", None) or {}
            return {
                "text": data.get("text", "") or "",
                "tool_activity": data.get("tool_activity") or [],
                "spoke_via_tool": bool(data.get("skipped_final", False)),
                "elapsed_s": data.get("elapsed_s"),
                "skipped_final": bool(data.get("skipped_final", False)),
                "error": data.get("error"),
            }
    else:
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
            """Local LLM path — the 0.2.0 default."""
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
    from ..core.tools.speak import _get_tts
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
    # The STTNode wraps the existing WhisperSTTContinuous engine and
    # publishes committed phrases on /sense/transcript.  voice_loop
    # subscribes here + drains via _phrase_queue instead of calling
    # stt.next_phrase() directly.  Engine control methods (set_paused,
    # open_followup, set_on_speech_detected, drain_pending,
    # require_wake_word, in_speech) still go through ``stt`` for now
    # — they're voice-loop-internal coordination and would need
    # /control/* topics that aren't designed yet.  Track B.3.2.b
    # handles those when the TTS path migrates.
    import queue as _queue
    from jaeger_os import topics as _topics
    from jaeger_os.nodes import STTNode as _STTNode
    from jaeger_os.nodes import runtime as _runtime
    _bus = _runtime.get_bus()
    _phrase_queue: "_queue.Queue[str]" = _queue.Queue()

    def _on_transcript(msg: _topics.Transcript) -> None:
        _phrase_queue.put(msg.text)

    _bus.subscribe(_topics.SENSE_TRANSCRIPT, _on_transcript)
    _stt_node = _STTNode(
        bus=_bus, adapter=stt, name="stt", install_signal_handlers=False,
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
    # In --attach mode the daemon already runs cron; spinning up a
    # second runner here would fire each scheduled prompt twice.
    # Skip silently in attach mode.
    llm_lock = threading.Lock()
    _pipeline["llm_lock"] = llm_lock
    cron_runner: CronRunner | None = None
    if not args.no_cron and not args.attach:
        def _cron_callback(prompt: str, session_key: str | None = None) -> None:
            assert client is not None  # local mode only
            run_for_voice(client, prompt, session_key=session_key)
        cron_runner = CronRunner(_cron_callback, llm_lock=llm_lock)
        cron_runner.start()
        print("[voice] cron runner started", flush=True)
    elif args.attach:
        print("[voice] cron runner skipped (daemon owns the schedules)",
              flush=True)

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
                phrase = _phrase_queue.get(timeout=1.0)
            except _queue.Empty:
                phrase = None
            if not phrase:
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

            # 0.2.6: in non-barge-in mode, keep the mic paused continuously
            # from agent decode THROUGH TTS playback. Previously the
            # decode was wrapped in mic-pause but tts.speak() ran with
            # the mic open, so speaker bleed-through could pollute the
            # phrase queue and either misfire the follow-up window or
            # trigger a bogus wake match. The reference
            # voice_assistant.py wraps the whole speak call in
            # mic-pause; we now do the same. With barge-in, the mic
            # stays open so the AEC + sustained-voice callback can
            # detect interruption mid-TTS.
            if not barge_in_active:
                stt.set_paused(True)

            try:
                # 0.2.6: turn_runner is either run_for_voice (local LLM)
                # or the daemon attach path; both return the same shape.
                result = turn_runner(phrase)
                text = (result.get("text") or "").strip()
                spoke_via_tool = result.get("spoke_via_tool", False)

                # LLM-gate: when config.voice.llm_gate is on, the
                # system prompt told the agent to begin its reply
                # with <reply> or <ignore>.  Parse + strip the tag
                # before we hand the text to TTS.
                gated_out = False
                if voice_gate_active and text and not spoke_via_tool:
                    from jaeger_os.core.voice import parse_gate
                    should_speak, gated_text = parse_gate(text)
                    if not should_speak:
                        print(f"[voice] LLM gate: <ignore> on phrase "
                              f"{phrase!r} — suppressing TTS", flush=True)
                        gated_out = True
                    else:
                        text = gated_text

                if not text or spoke_via_tool or gated_out:
                    if spoke_via_tool:
                        print("[voice] agent vocalized via tool — skipping "
                              "post-turn speak", flush=True)
                    # NB: the ``finally`` below will unpause the mic
                    # before we continue around the loop.
                    stt.open_followup()
                    continue

                # ── Speak the response ───────────────────────────────
                # Hoisted out of the barge-in branch so the post-speak
                # cleanup below (drain_pending / follow-up chime) can
                # read it on every path.  On the sync path the flag
                # never flips; on the barge-in path the STT callback
                # sets it from the VAD thread.
                interrupted = {"flag": False}
                if barge_in_active:
                    # Install a callback the STT thread fires the moment
                    # it sees sustained voice — sub-50 ms latency, no
                    # polling. Bypasses the main thread entirely so
                    # interruption is snappy.

                    def _on_user_speaks() -> None:
                        if not interrupted["flag"]:
                            interrupted["flag"] = True
                            print("[voice] barge-in detected — stopping TTS",
                                  flush=True)
                            tts.stop()

                    stt.set_on_speech_detected(_on_user_speaks)
                    try:
                        play_result = tts.play_async(text)
                        if not play_result.get("started"):
                            # Symmetric with the sync ``speak`` skip
                            # path below: the operator heard nothing,
                            # so opening a follow-up window they can't
                            # perceive would just confuse the flow.
                            # Back to WAKE; the next thing they say
                            # will need a wake word.
                            reason = play_result.get("reason", "unknown")
                            print(f"[voice] follow-up skipped — TTS "
                                  f"did not start ({reason})", flush=True)
                            continue
                        # Block until TTS naturally ends OR barge-in
                        # fires (which calls tts.stop() and causes wait
                        # to return).
                        tts.wait_until_done()
                    finally:
                        stt.set_on_speech_detected(None)
                else:
                    # Sync path: TTS runs with mic paused; reference
                    # voice_assistant's pattern. Followup chime fires
                    # before unpause so it doesn't bleed in either.
                    speak_result = tts.speak(text)
                    if not speak_result.get("spoken", False):
                        # Kokoro produced no audio (empty text, synth
                        # failure, drain timeout, …) — the operator
                        # heard nothing, so opening a follow-up window
                        # they can't perceive would just confuse the
                        # flow.  Back to WAKE; the ``finally`` below
                        # unpauses the mic and we go around.
                        reason = speak_result.get("reason", "unknown")
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
                ):
                    if barge_in_active:
                        if reference_buffer is not None:
                            chimes.play("followup")
                    else:
                        chimes.play("followup")

                stt.open_followup()
            finally:
                if not barge_in_active:
                    stt.set_paused(False)
    finally:
        try:
            tts.stop()
        except Exception:
            pass
        # 0.3.0: release the persistent output stream too — without
        # this, repeated voice_loop invocations within the same
        # interpreter (tests, daemon re-attach) leak audio device
        # handles in CoreAudio.  ``shutdown`` is a no-op if the player
        # was never opened or already closed.
        try:
            shutdown = getattr(tts, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception:
            pass
        # 0.4 Track B.3.2.a — STT node teardown.  Stopping the node
        # propagates to stt.stop() through STTNode.teardown(), and
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
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        # 0.2.6: release the daemon socket cleanly in attach mode.
        # Skipping shutdown_extensions there too — the daemon owns the
        # extensions, this process never initialised them.
        if daemon_client is not None:
            try:
                daemon_client.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        else:
            shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
