# M3 voice pipeline — measured on Mac Studio, 2026-11-05

Pipeline chosen (modern, Apple-Silicon optimized, no robotic built-in voices):
- STT: **Moonshine ONNX** (`moonshine/tiny` / `moonshine/base`, onnxruntime) AND whisper.cpp base.en (Metal) as fallback in repo listener.
- TTS: **Kokoro-82M ONNX** (`hexgrad/Kokoro-82M`, cached locally), voice af_heart, streams sentence chunks.
- LLM turn: cloud model via Gateway :33418, with the new voice **fast lane** (commit 5cf2ec33) routing conversational turns to DIRECT_RESPONSE.

## Measured today (10 WAV-synthesized exchanges against the LIVE gateway)
- STT Moonshine tiny (onnxruntime): **mean 0.77 s, max 1.06 s** per phrase.
- STT whisper.cpp base.en (Metal): **median 170 ms, max 442 ms** speech_end→transcript.
- TTS Kokoro: pipeline load 3.9 s (one-time), **first audio chunk 0.73–0.80 s**, full 5.8 s sentence synth 0.8 s, playback realtime.
- Entity turn (pre-fast-lane daemon): median 6.7 s; worst cases 315 s/600 s were session-busy artifacts of the sequential WAV loop, not model time.
- 10/10 exchanges submitted on one `voice-m3-seq` session; conversation continuity works (same session, no restart).

## Decision recorded
- Local ONNX STT+TTS on Mac Studio is fast enough: STT ~0.2–1 s, TTS first chunk <1 s. Cloud STT/TTS NOT needed. No robotic system voice used anywhere.
- Remaining latency is the LLM turn; the fast lane (M3a) targets that. Physical-mic barge-in still needs a live session with Matthew.
