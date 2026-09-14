# Silero speech admission model

This is the exact 16 kHz, ONNX opset 15 reference model used by the validated
VoiceLLM/Jaeger speech gate. It is packaged to remove the dependency on a
developer's `~/models/gemma-audio-adapter` directory. Explicit configured paths
remain supported.

- Reference: Jaeger Agent Omni `gates/silero-vad/gate.json`, imported 2026-09-13.
- SHA-256: `b6875a49bacf6d57826a7e0a549d5a05d769ee34405cadcc9ff8b4442544b1f9`
- Size: 1,289,603 bytes.
- Upstream: https://github.com/snakers4/silero-vad
- Copyright 2020-present Silero Team; MIT license in `LICENSE.txt`.

Do not replace this file with an arbitrary newer export: the packaged upstream
6.2.x file has a different checksum and different probabilities on the recorded
reference speech. Changing the model requires repeating speech-admission tests.
