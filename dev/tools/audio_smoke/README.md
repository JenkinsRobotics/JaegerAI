# `dev/tools/audio_smoke/` — standalone voice-pipeline smoke tests

Three single-file demos that exercise the same wake-word → STT →
LLM → TTS pipeline as the production
[`voice_loop.py`](../../jaeger_os/plugins/voice_loop.py), but
without any of the daemon / chat / skill plumbing.  Useful when
something in voice_loop misbehaves and you need to isolate
"is the audio backend OK or is the integration broken?".

Each script is self-contained — boots pywhispercpp, llama-cpp +
Gemma, and Kokoro, then runs a minimal "hey jaeger → reply →
follow-up" loop until you Ctrl-C.

| Script | What it proves |
|---|---|
| [`voice_assistant_avaudio.py`](voice_assistant_avaudio.py) | AVAudioEngine bridge (PyObjC) + persistent SessionPlayer pattern.  The macOS happy path — same backend the production loop uses on macOS by default. |
| [`voice_assistant_persistent.py`](voice_assistant_persistent.py) | sounddevice / PortAudio + persistent OutputStream + queue pattern.  The off-macOS happy path — same backend the production loop falls back to when AVAudioEngine isn't available. |
| [`voice_assistant_legacy.py`](voice_assistant_legacy.py) | **Intentional NEGATIVE reference.**  Per-utterance `sd.play()` / `sd.wait()` — the 0.2.x pattern this whole migration retired.  Kept so the contrast with the two persistent variants stays visible; do not use as a starting point for new work. |

## Run one

From the repo root, with the .venv active:

```bash
# AVAudioEngine path (macOS default)
PYTHONPATH=. .venv/bin/python dev/tools/audio_smoke/voice_assistant_avaudio.py

# sounddevice / PortAudio path
PYTHONPATH=. .venv/bin/python dev/tools/audio_smoke/voice_assistant_persistent.py

# Legacy bad pattern (audible clicks between utterances — diagnostic only)
PYTHONPATH=. .venv/bin/python dev/tools/audio_smoke/voice_assistant_legacy.py
```

Models the scripts expect:

* LLM: `jaeger_os/models/gemma-4-26B-A4B-it-Q4_K_M.gguf` (in-repo path
  is the default; falls back to `~/.lmstudio/models/...`)
* STT: `~/Library/Application Support/pywhispercpp/models/ggml-base.en.bin`
  + `ggml-medium.en.bin` (downloaded on first run by pywhispercpp)
* TTS: Kokoro 82M (downloaded on first run from
  `hexgrad/Kokoro-82M` on HuggingFace)

## When to reach for one

* **Voice loop wedges on barge-in** → run the avaudio script in
  isolation.  If it also wedges, the bug is in the persistent player
  (or PyObjC bridge); if it doesn't, the bug is in voice_loop's
  integration.
* **Clicks / pops between utterances** → A/B the avaudio vs legacy
  scripts.  If clicks only appear in the legacy script, the
  persistent pattern is doing its job in production.  If clicks
  appear in BOTH, the issue is upstream of the playback layer
  (Kokoro chunk sizing, sample-rate mismatch, etc.).
* **Whisper transcribing "BLANK_AUDIO" as commands** → the demos'
  `is_non_speech_marker` filter is the exact filter shape the
  production STT classes inherited.  Reproduce against a known-bad
  audio sample here first.

## Status

These scripts moved here from the repo root on 2026-06-05.  They
were originally written end-to-end to validate the persistent-player
pattern before porting into the production `kokoro_tts/node.py` +
`PersistentKokoroPlayer`.  See the 0.3.0 voice pipeline commit for
the porting history.
