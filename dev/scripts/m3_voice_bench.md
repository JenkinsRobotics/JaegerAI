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

## 2026-11-06 update — daemon restart + fold-in + M4 webcam

- Controlled restart of `com.jenkinsrobotics.jaeger-gateway` via `launchctl kickstart`:
  /health now reports commit `9b6cdbb0` (fast lane + fold-ins loaded). Service survived the restart; proof for part of M5.
- 10-exchange voice run against the restarted daemon: 10/10 submitted on one session,
  STT median 96 ms. Entity turn median 10.8 s — the turn still takes the full agent loop
  for these prompts (they contain work-ish words / the running entity's router), so the
  <2 s target is honest status: NOT yet met; fast lane helps only genuinely conversational
  turns. Recorded, not claimed.
- Sibling repos folded in: only 2 unique commits existed (fix/core-flows, hermes audit),
  both cherry-picked to master (2a52f251, 9b6cdbb0). JaegerAI-appcontrol / -backlog-reconcile
  / -j069 / -worktrees moved to ~/Desktop/JaegerAI-sibling-archives-2026-11-06/ (not deleted).
- M4 webcam: OpenCV captures a 1080p frame from the Insta360 Link 2 (~2 s incl. open);
  moondream2 (mlx-vlm, cached) describes it in 1.2–1.5 s inference ("game controller and
  keyboard on a wooden desk with cables" — verified correct against the actual photo).
  Script: dev/scripts/m4_webcam_vlm.py.

## 2026-11-06 M5 evidence — controlled restart with work in progress

- Pre-restart: a durable task (`m5-probe-task`) planted in the task store and a voice
  turn completed on session `voice-m5-probe` ("the probe word is orion") — turn ok.
- Restart: `launchctl kickstart -k .../com.jenkinsrobotics.jaeger-gateway`; /health back
  ok in ~10 s serving commit `1a66e0e9`, fail_closed=true.
- Post-restart: task store re-opened on the same DB — `m5-probe-task` still present
  (state queued). New voice turn on the SAME session id `voice-m5-probe` asking
  "what was the probe word?" -> entity replied "orion". Conversation + task survived
  the controlled service restart. (Backlog J-007 FULL REBOOT test still pending —
  needs Matthew's go-ahead; not claimed here.)
