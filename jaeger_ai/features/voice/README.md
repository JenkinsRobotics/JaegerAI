# voice — speak to the resident Entity

```text
microphone → speech detection → STT        stt slot: jaeger-whisper-stt (whisper.cpp)
           → Gateway :8810 → Entity         the same turn path as the WebUI
           → reply → TTS → speaker          tts slot: jaeger-kokoro-tts (Kokoro-82M)
```

Voice is a way into Jaeger, not a second Jaeger. This folder holds no model,
prompt, memory or tool list. A spoken phrase becomes a Gateway turn on a
`voice-…` session, and the Entity decides everything else, exactly as it does
for a typed turn. Something said by voice can be recalled in the WebUI, and
the reverse.

Switch it off by not running it; nothing else depends on this folder.

## Use

```bash
jaeger gateway daemon          # the Entity; voice never starts one
jaeger voice status            # what voice can use on this machine (JSON)
jaeger voice                   # microphone → Entity → speaker
jaeger voice --text            # typed turns, spoken replies
jaeger voice --wav a.wav b.wav # prepared 16 kHz mono WAV instead of the mic
jaeger voice --no-speech       # print replies instead of speaking
```

Each turn prints one JSON line on stderr: what was heard, the request id, the
model the Entity used, and measured latencies (`speech_end_to_transcript`,
`entity_turn`, `speech_end_to_first_audio`, …).

## What it relies on

| Piece | Contract | Owner |
| :--- | :--- | :--- |
| Turn submission | Gateway REST (`jaeger_ai.core.gateway.client`) | Gateway |
| Speech-to-text | `STTAdapter` (`jaeger_os.core.audio`) | stt slot |
| Text-to-speech | `KokoroTTS.speak` / `stop` | tts slot |
| Reply cleanup | `jaeger_os.core.voice.clean_voice_reply` | jaeger-os |
| Capability truth | `jaeger_ai.core.voice.status` (also feeds `/v1/runtime/capabilities` `audio`) | core |

`WavFileListener` and `TypedListener` implement the same `STTAdapter` shape
as the microphone engines, so tests and unattended runs drive the real
session, Gateway and Entity with only the capture swapped.

## Honest limits

* **Microphone permission** belongs to macOS (TCC). `voice status` reports the
  input device; whether capture is allowed is only known when it starts.
* **STT accuracy**: on synthetic speech, `base.en` heard "Orion 4812" as
  "Orion 4, Blackwell"; `medium.en` heard it correctly. Choose with
  `--stt-model`.
* **Latency is dominated by the Entity turn** (≈20–35 s measured with a cloud
  model and the deliberate planner). STT is ≈0.4–0.5 s; TTS starts within
  1 ms of the reply. This is turn-based voice, not real-time conversation.
* **Barge-in**: speech detected while a stoppable speaker is playing calls
  `stop()`. `KokoroTTS.speak` blocks, so the default loop pauses the mic while
  speaking; interruption during playback is **EXPERIMENTAL** and has not been
  exercised with a physical microphone.
* The older `jaeger --voice` / `jaeger_ai/plugins/voice_loop.py` path loads
  its own local model and does not go through the Entity. It is a separate
  assistant and should not be used where continuity matters.
