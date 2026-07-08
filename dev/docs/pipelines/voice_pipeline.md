# Pipeline: Voice (mic → STT → brain → TTS → speaker)

**What it is:** the always-on spoken loop. A spoken turn is just text-in /
text-out for the brain (STT → agent → TTS), identical to a typed turn — the
transport-agnostic brain never learns voice exists. All ambient-speech
filtering (wake word, VAD, non-speech, self-speech) lives in the INPUT layer,
never in the brain prompt (the in-brain LLM `<reply>`/`<ignore>` gate was
removed 2026-06-16 because it shared the model with tool-calling and
suppressed it; `voice_loop.py:4-8`).

Orchestrator: `jaeger_os/plugins/voice_loop.py` (a daemon, not a plugin —
same role as `messaging_gateway.py`). Reached via `python -m jaeger_os --voice`
(`main.py:4189-4192`) or a bare `./run.sh --instance NAME` when
`config.interaction.default_mode == "voice"` (`main.py:4315-4337`).

## The flow

```
mic ─► AudioSessionNode (own STT thread) ─► /sense/transcript ─► voice_loop
 │        core/audio/session.py::AudioSession                     _phrase_queue
 │        Whisper engine (two_pass | continuous)                       │
 │        VAD (webrtcvad) → phrase → wake-word gate → 2nd-pass          │
 │        deterministic filters: non_speech, self_speech                │
 │        also PUB /sense/user_speech_start (barge-in) +                │
 │            /sense/gate_decision (activity log)                       │
 │                                                                      ▼
 │                                              _on_transcript: drop non-speech,
 │                                              bound queue (maxsize=4, drop stale)
 │                                                                      │
 │                                              main loop pulls phrase ◄┘
 │                                                • self-speech filter (difflib)
 │                                                • drop if age > 3.0s
 │                                                • wake chime
 │                                                • mic-pause (unless barge-in)
 │                                                      │
 │                                              turn_runner(phrase)
 │                                              = run_for_voice(client, …)  ← main.py:3070
 │                                                LOCAL Gemma, in-process
 │                                                → {text, spoke_via_tool, elapsed_s}
 │                                                clean_voice_reply(text)
 │                                                      │
 │                                              bus.request(SpeechCommand) ─► /act/speech
 │                                                ack_topic=/sense/spoken, timeout 180s
 │                                                      ▼
 │                                              TTSNode  nodes/kokoro_tts/node.py
 │                                                SUB /act/speech → queue → tick()
 │                                                synthesizer.speak()  (KokoroTTS)
 │                                                PUB /sense/tts_chunk @~30Hz (lip-sync)
 │                                                PUB /act/audio_out (frames) ─► speaker
 └─◄ barge-in: STT sustained-voice cb          PUB /sense/spoken (SpokenAck) ─────┐
     PUB /act/speech_stop ─► TTSNode.stop()                                       │
                                                    bus.request returns ack ◄──────┘
                                                      │
                                              ack.ok? → follow-up chime (wake-gate on)
                                                      → open_followup() window
                                                      → remember_reply() (self-speech)
```

## Key files / functions

- `plugins/voice_loop.py :: main()` — the whole daemon. Loads Gemma
  in-process (`LlamaCppPythonClient`, `voice_loop.py:205`), `init_extensions` +
  `prewarm`, warms Kokoro (`voice_loop.py:270`), builds the STT engine, spawns
  `AudioSessionNode` on a thread (`voice_loop.py:397-406`), then runs the
  phrase-pull loop (`voice_loop.py:449-728`).
- `plugins/voice_loop.py :: turn_runner()` → `main.run_for_voice(client,
  phrase, session_key="voice")` (`voice_loop.py:216-217`, `main.py:3070`) — the
  thin output adapter over `_run_turn`; returns `{text, spoke_via_tool,
  elapsed_s}`.
- `nodes/audio_session/node.py :: AudioSessionNode` — wraps `AudioSession`;
  `setup()` opens mic + starts STT loop and wires callbacks; `tick()` pulls one
  committed phrase via `session.next_phrase()` and PUBs `Transcript` on
  `/sense/transcript` (with `speech_end_pc`/`stt_done_pc` timing);
  also PUBs `UserSpeechStart` (`/sense/user_speech_start`) and `GateDecision`
  (`/sense/gate_decision`).
- `core/audio/session.py :: AudioSession.next_phrase()` — the deterministic
  input pipeline (`session.py:202-242`): STT phrase → `is_non_speech_marker`
  filter → self-speech filter (`difflib.SequenceMatcher.ratio()`) → accepted.
  The LLM semantic gate is NOT here — it's removed (`session.py:299-315`); the
  brain's own turn is the semantic gate.
- `plugins/whisper_stt/two_pass/pipeline.py` — default STT (`--stt-mode
  two_pass`). `_VadWorker` (`pipeline.py:43`) runs `webrtcvad`
  (aggressiveness 2), closes a phrase on silence hangover (700 ms, or 350 ms
  short-phrase hangover) or max length. Fast model `base.en` gates the wake
  word; accurate model `medium.en` transcribes the committed command. State
  machine `WAKE`→`FOLLOWUP` (`pipeline.py:311, 336-341`).
  `continuous/pipeline.py` is the alternate (`--stt-mode continuous`,
  energy-segmented rolling re-transcription).
- `plugins/whisper_stt/_base.py :: DEFAULT_WAKE_PHRASES` — cartesian product of
  prefixes `("ok","okay","hey")` × names `("jaeger","yeager","yager","jager")`
  (`_base.py:33-35`); fuzzy-matched via `_find_wake_in_text` at threshold 0.78.
- `nodes/kokoro_tts/node.py :: TTSNode` — SUB `/act/speech` + `/act/speech_stop`;
  `tick()` drains one `SpeechCommand`, runs `synthesizer.speak()` (KokoroTTS)
  serially on the node thread, PUBs `SpokenAck` on `/sense/spoken` matched by
  `correlation_id`. Emits `TtsChunk` on `/sense/tts_chunk` at ~30 Hz (sin-wave
  amplitude proxy for lip-sync, `node.py:255-288`). Bounded queue (32);
  overflow → immediate `ok=False, reason="TTS queue full"` ack.
- `nodes/runtime.py :: ensure_tts_node()` / `get_synth()` / `get_bus()` —
  materialises the singleton `TTSNode` on the brain's `InProcBus`
  (`runtime.py:165-196`); `agent/tools/speak.py` routes speech through it.
- `nodes/kokoro_tts/` — `KokoroTTS` synthesizer + `PersistentKokoroPlayer`
  (`persistent_player.py`). Publishes synthesized `AudioOutFrame` on
  `/act/audio_out` (24 kHz float32 PCM).
- `plugins/avaudio_io/{input_stream,output_stream}.py` — default macOS audio
  backend (`InputStream`/`OutputStream`, PyObjC `AVAudioEngine`, sounddevice-
  shaped API). Mic at 16 kHz; `voice_processing=True` enables Apple's built-in
  AEC+NS+AGC. `portaudio` (sounddevice) is the off-macOS default / fallback
  (`voice_loop.py:134-141`).
- `core/audio/` — `AECWrapper` + `aec_available()` (speexdsp, `aec.py`),
  `ReferenceBuffer` (far-end echo reference, `reference_buffer.py`),
  `ChimePlayer` (wake / follow-up earcons, `chimes.py`).
- `core/voice/` — `is_non_speech_marker` (`non_speech.py`), `is_farewell`
  (`farewell.py`), `clean_voice_reply` (`reply_cleaner.py`).
- `core/instance/schemas.py :: VoiceConfig` (`schemas.py:232`) — persisted
  settings: `enabled` (default False), `speak_replies` (True), `wake_word`
  (True), `follow_up` (True), `barge_in` (False), `follow_up_seconds` (10.0),
  `audio_backend` (`sounddevice`|`avaudio`), `self_speech_filter` (True),
  `self_speech_threshold` (0.75).

## Topics

| Topic | Constant | Producer → Consumer |
|---|---|---|
| `/sense/audio_in` | `SENSE_AUDIO_IN` | (`AudioInFrame`, 16 kHz PCM; declared, raw-mic transport) |
| `/sense/transcript` | `SENSE_TRANSCRIPT` | AudioSessionNode → voice_loop (`Transcript`) |
| `/sense/user_speech_start` | `SENSE_USER_SPEECH_START` | AudioSessionNode → (barge-in) (`UserSpeechStart`) |
| `/sense/gate_decision` | `SENSE_GATE_DECISION` | AudioSessionNode → interfaces (`GateDecision`) |
| `/act/speech` | `ACT_SPEECH` | voice_loop → TTSNode (`SpeechCommand`) |
| `/act/speech_stop` | `ACT_SPEECH_STOP` | voice_loop → TTSNode (barge-in) (`SpeechStop`) |
| `/act/audio_out` | `ACT_AUDIO_OUT` | TTS → speaker (`AudioOutFrame`, 24 kHz PCM) |
| `/sense/tts_chunk` | `SENSE_TTS_CHUNK` | TTSNode → animation (lip-sync) (`TtsChunk`) |
| `/sense/spoken` | `SENSE_SPOKEN` | TTSNode → voice_loop ack (`SpokenAck`) |

## Behaviors

- **Wake word** — gates which utterances become a turn (`config.voice.wake_word`
  default True; `--wake-word`/`--no-wake-word` override, `voice_loop.py:166-170`).
  Off = every VAD-segmented phrase is treated as addressed to the agent.
- **VAD** — `webrtcvad` in the two_pass `_VadWorker`; silence hangover closes a
  phrase (700 ms, 350 ms for short phrases).
- **Barge-in** — request-by-default; only ACTIVE when AEC (speexdsp) is
  available (`voice_loop.py:228-243`). When active the mic stays open during
  TTS; the STT sustained-voice callback PUBs `SpeechStop`, which the TTSNode
  turns into `synthesizer.stop()`. Without AEC → falls back to mic-pause
  during TTS.
- **Follow-up** — after a reply, `open_followup()` opens a no-wake-word window
  (`follow_up_seconds`, default 10.0; `voice_loop.py:722`, `session.py:262-267`).
  Suppressed on a farewell exchange (BOTH user phrase AND reply read as
  goodbye, `voice_loop.py:536-541, 714-720`).
- **Self-speech filter** — drops a transcript too similar (difflib ratio ≥
  0.75) to the agent's last spoken reply — defence-in-depth on top of mic-pause
  (`voice_loop.py:480-494`, `session.py:289-297`).
- **Queue hygiene** — bounded phrase queue (maxsize 4); phrases older than 3.0s
  dropped (`voice_loop.py:184, 463-474`); pending phrases drained after
  playback except when barge-in fired (`voice_loop.py:668-684`).
- **Latency** — logs honest `speech-end→speak` (`voice_loop.py:567-581`) from
  the STT `speech_end_pc`/`stt_done_pc` perf_counter stamps carried on the
  `Transcript`.

## Status

- **Done:** full mic→STT→brain→TTS→speaker loop over the in-proc bus; two_pass
  (default) + continuous STT; wake word; VAD; AEC barge-in (when speexdsp
  present) via `/act/speech_stop`; follow-up window; farewell suppression;
  non-speech + self-speech filters; wake/follow-up chimes; avaudio (macOS) +
  portaudio backends; TTS bus node with `/sense/spoken` ack RPC; `/sense/tts_chunk`
  lip-sync events; cron runner alongside the loop.
- **Standalone only:** the daemon-attach path (route turns through a shared
  daemon) was removed 2026-06-14 (J5C) — voice_loop loads its own model and owns
  its turn lifecycle. Run only one of {voice, messaging, TUI} at a time
  (`voice_loop.py:114-119`).
- **Proxy / not-yet-real:** `/sense/tts_chunk` amplitude is a sin-wave
  placeholder, not real RMS from Kokoro's buffer — a 0.5.x follow-up
  (`topics.py:254-268`, `nodes/kokoro_tts/node.py:255-268`).
- **Engine control still direct:** `set_paused` / `open_followup` /
  `set_on_speech_detected` / `drain_pending` still call the `stt` engine
  directly (not via `/control/*` topics — not yet designed; `voice_loop.py:307-316`).
- **In-node LLM gate removed:** semantic gating lives in the brain's turn, not
  the audio session (removed for a 50× KV-cache-thrash slowdown;
  `session.py:299-315`).
