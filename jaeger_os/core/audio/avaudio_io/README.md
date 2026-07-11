# `avaudio_io` — Apple-native audio I/O for the Python voice loop

PyObjC `AVAudioEngine` wrappers exposed with the **same call surface
as sounddevice's** `InputStream` / `OutputStream` so they're a
drop-in replacement at the existing call sites in
`nodes/whisper_stt/engine/_base.py` and `nodes/kokoro_tts/engine.py`.

## Why

The 0.2.x audio path is:

    Kokoro / pywhispercpp  →  sounddevice  →  PortAudio  →  CoreAudio

PortAudio's CoreAudio backend is the source of the wedging bugs the
operator has hit repeatedly — the BenQ-AUHAL stall, the
`kAudioHardwareUnspecifiedError` ('what') that breaks YouTube
playback after a failed mic-engine start, etc. Apple's own
`AVAudioEngine` doesn't suffer from these.

Replacing **only the I/O layer** keeps everything else the same:

- Same Kokoro voice quality (the synthesizer is unchanged)
- Same pywhispercpp accuracy (the recognizer is unchanged)
- Same Python codebase (no Swift required for headless / CLI users)
- Built-in voice processing mode supplies AEC + NS + AGC — retires
  the optional `speexdsp` dependency for AEC barge-in

## Status — what works (smoke tests all pass)

| | What | Verified |
|---|---|---|
| `InputStream` | mic capture, system input, blocksize-correct chunks, scipy resampling | ✅ |
| `InputStream` voice processing | `voice_processing=True` → built-in AEC+NS+AGC | ✅ |
| `OutputStream` | playback via player node + worker-thread scheduling | ✅ |
| Loopback | capture for 5s, play it back | ✅ |
| API parity | drop-in for `sd.InputStream` / `sd.OutputStream` constructors | ✅ |

Run the smoke suite:

```bash
PYTHONPATH=<repo> .venv/bin/python -m jaeger_os.core.audio.avaudio_io.smoke_test --input
PYTHONPATH=<repo> .venv/bin/python -m jaeger_os.core.audio.avaudio_io.smoke_test --output
PYTHONPATH=<repo> .venv/bin/python -m jaeger_os.core.audio.avaudio_io.smoke_test --loopback
PYTHONPATH=<repo> .venv/bin/python -m jaeger_os.core.audio.avaudio_io.smoke_test --aec
```

## Status — what's NOT wired in yet (next session)

The module is **standalone** today — it's not used by `whisper_stt` or
`kokoro_tts` yet. The integration is a two-line change at each call
site, but should land alongside an A/B comparison test:

### Step 1 — Add a feature flag

Add `--audio-backend {portaudio,avaudio}` to `voice_loop.py`'s
argparse (default `portaudio` for now so we don't disturb the
existing flow during testing).

### Step 2 — Wire `InputStream` into `whisper_stt/_base.py::_MicStream`

In `_MicStream.__init__`:

```python
# Today
import sounddevice as sd
self._stream = sd.InputStream(
    device=device,
    samplerate=sample_rate,
    channels=1,
    dtype="float32",
    blocksize=frame_samples,
    callback=self._cb,
)

# Becomes
if audio_backend == "avaudio":
    from jaeger_os.core.audio.avaudio_io import InputStream
    self._stream = InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=frame_samples,
        callback=self._cb,
        voice_processing=use_native_aec,  # retires speexdsp when True
    )
else:
    import sounddevice as sd
    self._stream = sd.InputStream(...)  # unchanged
```

### Step 3 — Wire `OutputStream` into `kokoro_tts/node.py::play_async`

Same pattern at the `sd.OutputStream(...)` callsite (~line 378 of
`node.py`).

### Step 4 — Wire `OutputStream` into the blocking `tts.speak()` path

`kokoro_tts/node.py::_play_audio_with_live_device` also uses
sounddevice — same swap.

### Step 5 — Smoke test against a live daemon

Run `./run.sh --voice --instance jros-dev --audio-backend avaudio`
and confirm:

- Mic captures cleanly (wake word fires)
- Kokoro plays cleanly (no wedging during repeated turns)
- BenQ-AUHAL stall doesn't reproduce
- Voice processing mode replaces speexdsp without quality regression

### Step 6 — Flip default

Once the live test holds, default `--audio-backend` to `avaudio` on
macOS.  Keep `portaudio` as an explicit opt-in for Linux / debugging.

## Design notes — for the next session

### Resampling lives in Python, not AVAudioConverter

PyObjC's bridging of AVAudioConverter's input-block (pointer arg)
segfaults the audio render thread. We use `scipy.signal.resample_poly`
on the captured NumPy array instead — well under 1 ms per 20 ms
block on Apple Silicon, and stable.

### No completion handler on `scheduleBuffer`

The 4-arg `scheduleBuffer:atTime:options:completionHandler:` variant
trips PyObjC signature inference on the block argument and crashes
the audio thread. We use the 2-arg
`scheduleBuffer:completionHandler:` with `None` and drive pacing
from a worker thread instead.

### Threading model

- **Input**: tap callback fires on AVAudioEngine's render thread.
  Python work (resample, downmix, deliver to caller's callback) runs
  on that thread. Should be fast.
- **Output**: worker thread pulls from caller's callback, builds
  PCMBuffers, schedules. Player node plays. Pacing is `0.5 *
  block_duration` sleeps; `queue_depth_blocks` pre-warm.

### `objc.varlist`

`AVAudioPCMBuffer.floatChannelData()` returns a tuple of
`objc.varlist` — variable-length C array wrappers. Access via
**slicing**: `varlist[0:n]` returns a tuple of floats that NumPy
accepts; `varlist[0:n] = python_list` writes back.

### Things to consider later

- **Latency**: worker-thread pacing adds ~10 ms of latency vs
  callback-driven sounddevice. Probably invisible for voice, but
  measurable. If it matters, we can investigate `objc.callbackFor`
  on the completion handler with explicit signature annotation.
- **Hardware sample rates**: tested on Mac Studio with 48 kHz / 2-channel
  input. Audio interfaces that report different formats (24-bit
  Float32 vs Float32) might need additional handling.
- **Multiple instances**: each `InputStream` / `OutputStream`
  creates its own `AVAudioEngine`. Should be fine but untested with
  > 2 simultaneous engines.
