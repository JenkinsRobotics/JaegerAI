#!/usr/bin/env python3
"""Voice loop — STT → agent → TTS daemon, with optional barge-in.

Three runtime modes selected at startup:

  --stt-mode two_pass    (default)
      VAD-segmented STT with fast→accurate Whisper cascade. Robust against
      noise, slightly higher latency on commit.

  --stt-mode continuous
      Energy-segmented STT with rolling re-transcription. Lower commit
      latency, lighter memory footprint, less robust to background noise.

  --barge-in
      Allows the user to interrupt the AI mid-speech. Non-blocking TTS
      playback; STT keeps listening during TTS. If AEC is available
      (speexdsp installed), the AI's own voice is canceled out of the
      mic input. Without AEC, the mic captures playback bleed-through
      and the wake-word matcher may misfire — set_paused() is safer
      when AEC isn't available.

  --no-aec
      Force passthrough even when speexdsp is installed. Useful for
      A/B testing or debugging false-cancellation.

Run:
    python -m jaeger_os.plugins.voice_loop
    python -m jaeger_os.plugins.voice_loop --stt-mode continuous
    python -m jaeger_os.plugins.voice_loop --require-wake-word --barge-in
    python -m jaeger_os.plugins.voice_loop --instance work

This file is NOT a plugin — it's the daemon orchestrator wiring the
kokoro_tts and whisper_stt plugins to the agent. Same role as
plugins/messaging_gateway.py. See docs/VOCABULARY.md.
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
    p.add_argument("--barge-in", action="store_true",
                   help="Allow user to interrupt AI mid-speech (non-blocking TTS).")
    p.add_argument("--no-aec", action="store_true",
                   help="Force AEC passthrough even if speexdsp is installed.")
    p.add_argument("--fast-model", type=str, default="base.en",
                   help="Whisper fast/continuous model name (default: base.en).")
    p.add_argument("--accurate-model", type=str, default="medium.en",
                   help="Whisper accurate model name (two_pass only, default: medium.en).")
    p.add_argument("--no-cron", action="store_true",
                   help="Don't start the cron runner alongside the voice loop.")
    p.add_argument("--no-chimes", action="store_true",
                   help="Disable wake / follow-up audio earcons.")
    args = p.parse_args()

    # 0.2.6: invert the --no-wake-word flag into the require_wake_word
    # bool the STT layer wants. Default behaviour (no flag passed) is
    # wake-word ON — matches the reference voice_assistant.py UX.
    require_wake_word = not args.no_wake_word

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
    from ..main import _pipeline
    _pipeline["layout"] = layout
    _pipeline["config"] = config
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = config.display.show_latency
    _pipeline["show_tool_activity"] = config.display.show_tool_activity

    # ── Load the LLM ─────────────────────────────────────────────────
    print(f"[voice] loading Gemma in-process ({layout.root.name})...", flush=True)
    started = time.perf_counter()
    client = LlamaCppPythonClient(config.model, warmup=True)
    print(f"[voice] loaded in {time.perf_counter() - started:.1f}s", flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    prewarm(client)

    # ── AEC + reference buffer (only when barge-in is requested) ─────
    aec = None
    reference_buffer = None
    if args.barge_in:
        from ..core.audio import AECWrapper, ReferenceBuffer, aec_available
        if not args.no_aec and aec_available():
            aec = AECWrapper(sample_rate=16000, frame_ms=10, enabled=True)
            reference_buffer = ReferenceBuffer(sample_rate=16000, capacity_seconds=2.0)
            print(f"[voice] AEC enabled ({aec.backend}); barge-in via echo cancellation", flush=True)
        else:
            reason = "user-requested" if args.no_aec else "speexdsp not installed"
            print(f"[voice] AEC unavailable ({reason}); barge-in via mic-pause heuristic only", flush=True)

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
    if args.stt_mode == "continuous":
        from .whisper_stt import WhisperSTTContinuous
        stt = WhisperSTTContinuous(
            model_name=args.fast_model,
            require_wake_word=require_wake_word,
            followup_window_s=10.0,
            aec=aec, far_end_buffer=reference_buffer,
        )
    else:
        from .whisper_stt import WhisperSTTTwoPass
        stt = WhisperSTTTwoPass(
            fast_model_name=args.fast_model,
            accurate_model_name=args.accurate_model,
            require_wake_word=require_wake_word,
            followup_window_s=10.0,
            aec=aec, far_end_buffer=reference_buffer,
        )
    stt.start()

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
    if args.barge_in:
        mode_msg += ", barge-in on"
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
            phrase = stt.next_phrase(timeout=1.0)
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
            if not args.barge_in:
                stt.set_paused(True)

            try:
                result = run_for_voice(client, phrase, session_key="voice")
                text = (result.get("text") or "").strip()
                spoke_via_tool = result.get("spoke_via_tool", False)

                if not text or spoke_via_tool:
                    if spoke_via_tool:
                        print("[voice] agent vocalized via tool — skipping "
                              "post-turn speak", flush=True)
                    # NB: the ``finally`` below will unpause the mic
                    # before we continue around the loop.
                    stt.open_followup()
                    continue

                # ── Speak the response ───────────────────────────────
                if args.barge_in:
                    # Install a callback the STT thread fires the moment
                    # it sees sustained voice — sub-50 ms latency, no
                    # polling. Bypasses the main thread entirely so
                    # interruption is snappy.
                    interrupted = {"flag": False}

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
                            print(f"[voice] TTS skipped: "
                                  f"{play_result.get('reason')}", flush=True)
                            stt.open_followup()
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
                    tts.speak(text)

                # Drop any phrases that VAD finalized during playback —
                # otherwise a stale buffered utterance becomes the next
                # "user input". Critical in barge-in mode where the mic
                # stayed open; cheap in sync mode where it's a no-op.
                stt.drain_pending()

                # Follow-up chime — rising two-note tone tells the user
                # "still listening, no wake word needed for the next
                # phrase". Only play when wake gating is on (otherwise
                # there's no semantic difference between in-window and
                # out-of-window). In barge-in mode the mic is open, so
                # only play when AEC will cancel the chime out; in sync
                # mode the mic is still paused under the outer try,
                # which is safer than the prior pause/unpause dance.
                if stt.require_wake_word and chimes.enabled("followup"):
                    if args.barge_in:
                        if reference_buffer is not None:
                            chimes.play("followup")
                    else:
                        chimes.play("followup")

                stt.open_followup()
            finally:
                if not args.barge_in:
                    stt.set_paused(False)
    finally:
        try:
            tts.stop()
        except Exception:
            pass
        stt.stop()
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
