# Production readiness

JaegerWhisperSTT is designed as one replaceable JaegerOS `stt` engine module.
It never opens a microphone: `AudioIONode` owns capture, device recovery, AEC,
and playback coordination, then publishes mono float32 PCM on
`/sense/mic/pcm`.

## Supported operating modes

| Mode | Final boundary | Partials | Engine wake word | Intended use |
|---|---|---:|---:|---|
| `vad_segment` | WebRTC VAD silence | No | Yes | Lightweight commands |
| `two_pass` | WebRTC VAD silence | No | Yes | Shipping voice-assistant default |
| `continuous` | RMS phrase silence | No | Yes | Low-memory phrase recognition |
| `phrase_word` | RMS phrase silence | Yes | Yes | Assistant with a live caption line |
| `window` | Clocked rolling window | Yes | No | Display-only room captions |
| `local_agreement` | Stable word agreement | Yes | No | Trustworthy continuous transcript |

Rolling modes intentionally reject `require_wake_word=true`. A rolling commit
can split “hey Jaeger” and its command into different messages; pretending that
engine gating is reliable would silently drop valid commands. Use `two_pass` or
`phrase_word`, or perform directed-command detection in an app such as the
`always_listening` demo.

## Release gates

Run these from the robot's final Python environment:

```bash
# Dependency and package contract
python -m pip check
pytest -q

# Cache both shipping models and validate that whisper.cpp can load them
jaeger-whisper-stt models --prepare

# Verify the JaegerOS hardware owner without loading Whisper
jaeger-whisper-stt doctor --seconds 10

# Verify the complete microphone -> bus -> VAD -> Whisper -> Transcript path
jaeger-whisper-stt run two_pass --seconds 60

# Soak health, transcript count, queue drops, and driver recovery
python "JaegerOS Demos/whisper stt/production_monitor/main.py" \
  --minutes 30 --min-transcripts 30
```

A deployable image must pass all five gates on the exact microphone, USB audio
interface, speaker, operating system, and room used by the robot. Unit tests and
PCM replay qualify module logic; they cannot qualify a physical audio chain.

## Operational guarantees

- Audio and transcript queues are bounded; newest data wins under overload.
- Malformed PCM, rate mismatch, input staleness, decode failure, queue drops,
  and worker death are visible in node health.
- Recognition workers have guarded entry points and bounded shutdown joins.
- Wake-only speech arms a nonblocking command window in every wake-capable mode.
- Model weights can be prepared during image build; production boot need not
  depend on network access.
- Device enumeration runs in a timeout-bounded child process so a wedged native
  audio service cannot hang the diagnostic CLI.
- Benchmark recording uses the same JaegerOS audio driver as production apps.

## Hardware troubleshooting boundary

If `doctor` fails, investigate the OS audio service, permissions, selected
device, sample rate, USB interface, or JaegerOS `AudioIONode`; Whisper has not
loaded yet. If `doctor` passes but `run two_pass` fails on known speech, inspect
the STT engine health, model cache, VAD tuning, and room acoustics.
